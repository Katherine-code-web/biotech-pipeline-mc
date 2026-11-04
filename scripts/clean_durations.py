"""Filter CT.gov Phase 2/3 trials and compute trial durations (start -> primary completion).

Common filters: interventional -> industry lead sponsor -> COMPLETED (TERMINATED kept for a sensitivity).
Then four date rules are compared (counts for every step go to docs/filter_log.md):
  a  start and primary completion dates present; type ACTUAL or untyped (untyped treated as actual)
  b  both dates typed ACTUAL (strict)
  c  rule a + start year 2011-2020
  d  rule a + start year 2010-2019
Within each rule: single-phase PHASE2/PHASE3 kept, combined phases set aside for sensitivity,
then durations <= 0, < 1 month, or > 180 months are excluded (saved for audit).

Outputs (data/processed/):
  durations_main.csv                  resampling vector: rule d, completed (phase, duration_months, ...)
  durations_rule_{a,b,c}.csv          resampling vectors for sensitivity (completed; rule a = all years)
  durations_phase2_phase3.csv         kept single-phase trials (completed + terminated), all rule flags
  durations_combined_sensitivity.csv  kept PHASE1+PHASE2 / PHASE2+PHASE3 trials, same flags
  durations_excluded.csv              trials dropped by a duration rule, with reason
  duration_summary.csv                n / median / P25 / P75 / min / max by rule x phase (completed)
  duration_terminated_sensitivity.csv same stats incl. terminated trials, and terminated only
  duration_short_exclusion.csv        medians before vs after the < 1 month rule
  duration_by_era.csv                 rule a, by start-year era
and docs/filter_log.md.

Standard library only. Usage:
  python scripts/clean_durations.py                       # newest complete snapshot
  python scripts/clean_durations.py --snapshot data/raw/ctgov_phase2_3_<ts>.jsonl.gz
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"
LOG_PATH = ROOT / "docs" / "filter_log.md"

MAIN_PHASES = ("PHASE2", "PHASE3")
IMPUTED_DAY = 15  # day used when CT.gov gives only YYYY-MM
DAYS_PER_MONTH = 365.25 / 12
MIN_MONTHS = 1
MAX_MONTHS = 180  # 15 years
RULE_C_YEARS = (2011, 2020)
RULE_D_YEARS = (2010, 2019)
MAIN_RULE = "d"  # written to durations_main.csv (per project instruction); choice still open
ERAS = [("before 2005", None, 2004), ("2005-09", 2005, 2009), ("2010-14", 2010, 2014),
        ("2015-19", 2015, 2019), ("2020+", 2020, None)]

RULES = {
    "a": "Completed; untyped dates treated as ACTUAL",
    "b": "Completed; both dates typed ACTUAL (strict)",
    "c": f"Rule a + start year {RULE_C_YEARS[0]}-{RULE_C_YEARS[1]}",
    "d": f"Rule a + start year {RULE_D_YEARS[0]}-{RULE_D_YEARS[1]}",
}
REASONS = [
    ("non_positive_duration", "duration ≤ 0 months", "Completion on/before start: data-entry error"),
    ("under_1_month", f"0 < duration < {MIN_MONTHS} month",
     "Too short to represent a Phase 2/3 efficacy trial (mostly single-dose / PK-type studies)"),
    ("over_15_years", f"duration > {MAX_MONTHS} months", "Implausible for a single trial; usually a wrong date"),
]

ROW_FIELDS = [
    "nct_id", "phase", "status", "start_date", "start_date_type", "primary_completion_date",
    "primary_completion_date_type", "start_day_imputed", "completion_day_imputed",
    "start_year", "duration_months", "in_rule_a", "in_rule_b", "in_rule_c", "in_rule_d", "exclusion_reason",
]
VECTOR_FIELDS = ["phase", "duration_months", "nct_id", "start_year"]


def latest_snapshot() -> Path:
    for manifest in sorted(RAW_DIR.glob("ctgov_phase2_3_*.manifest.json"), reverse=True):
        m = json.loads(manifest.read_text())
        fields = m["params"]["fields"].split(",")
        if m.get("complete") and {"LeadSponsorClass", "StudyType"} <= set(fields):
            return RAW_DIR / m["output_file"]
    raise SystemExit("No complete snapshot with LeadSponsorClass/StudyType; run scripts/fetch_ctgov.py")


def parse_date(s: str) -> tuple[date, bool]:
    """Return (date, day_imputed)."""
    parts = s.split("-")
    if len(parts) == 3:
        return date(int(parts[0]), int(parts[1]), int(parts[2])), False
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), IMPUTED_DAY), True
    raise ValueError(f"unexpected date format: {s}")


def flatten(study: dict) -> dict:
    p = study["protocolSection"]
    status = p.get("statusModule", {})
    start = status.get("startDateStruct", {})
    pcd = status.get("primaryCompletionDateStruct", {})
    return {
        "nct_id": p["identificationModule"]["nctId"],
        "phase": "+".join(p.get("designModule", {}).get("phases", [])),
        "study_type": p.get("designModule", {}).get("studyType"),
        "sponsor_class": p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("class"),
        "status": status.get("overallStatus"),
        "start_date": start.get("date"),
        "start_type": start.get("type"),
        "pcd": pcd.get("date"),
        "pcd_type": pcd.get("type"),
    }


def rule_flags(r: dict) -> dict[str, bool]:
    has_dates = bool(r["start_date"] and r["pcd"])
    a = has_dates and r["start_type"] in ("ACTUAL", None) and r["pcd_type"] in ("ACTUAL", None)
    b = has_dates and r["start_type"] == "ACTUAL" and r["pcd_type"] == "ACTUAL"
    year = int(r["start_date"][:4]) if r["start_date"] else None
    c = a and RULE_C_YEARS[0] <= year <= RULE_C_YEARS[1]
    d = a and RULE_D_YEARS[0] <= year <= RULE_D_YEARS[1]
    return {"a": a, "b": b, "c": c, "d": d}


def with_duration(r: dict, flags: dict[str, bool]) -> dict:
    s, s_imp = parse_date(r["start_date"])
    c, c_imp = parse_date(r["pcd"])
    months = (c - s).days / DAYS_PER_MONTH
    reason = ""
    if months <= 0:
        reason = "non_positive_duration"
    elif months < MIN_MONTHS:
        reason = "under_1_month"
    elif months > MAX_MONTHS:
        reason = "over_15_years"
    return {
        "nct_id": r["nct_id"], "phase": r["phase"], "status": r["status"],
        "start_date": r["start_date"], "start_date_type": r["start_type"] or "",
        "primary_completion_date": r["pcd"], "primary_completion_date_type": r["pcd_type"] or "",
        "start_day_imputed": s_imp, "completion_day_imputed": c_imp,
        "start_year": s.year, "duration_months": round(months, 2),
        **{f"in_rule_{k}": v for k, v in flags.items()},
        "exclusion_reason": reason,
    }


def summarize(rows: list[dict]) -> dict:
    x = sorted(r["duration_months"] for r in rows)
    if len(x) < 2:
        return {"n": len(x)}
    q1, med, q3 = statistics.quantiles(x, n=4, method="inclusive")
    return {"n": len(x), "median": round(med, 2), "p25": round(q1, 2), "p75": round(q3, 2),
            "min": x[0], "max": x[-1]}


def era_of(year: int) -> str:
    for label, lo, hi in ERAS:
        if (lo is None or year >= lo) and (hi is None or year <= hi):
            return label
    raise ValueError(year)


def by_phase(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["phase"]] = out.get(r["phase"], 0) + 1
    return dict(sorted(out.items()))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, default=None)
    args = ap.parse_args()
    snap = args.snapshot or latest_snapshot()

    with gzip.open(snap, "rt", encoding="utf-8") as f:
        rows = [flatten(json.loads(line)) for line in f]

    common: list[tuple[str, list[dict]]] = [("Snapshot (Phase 2/3 query)", rows)]
    for label, pred in [
        ("Study type = INTERVENTIONAL", lambda r: r["study_type"] == "INTERVENTIONAL"),
        ("Lead sponsor class = INDUSTRY", lambda r: r["sponsor_class"] == "INDUSTRY"),
        ("Overall status = COMPLETED or TERMINATED", lambda r: r["status"] in ("COMPLETED", "TERMINATED")),
    ]:
        common.append((label, [r for r in common[-1][1] if pred(r)]))
    for label, rs in common:
        print(f"{label}: {len(rs)}")

    # Every completed/terminated trial that passes rule a (the widest rule; b, c, d are subsets).
    all_records = []
    for r in common[-1][1]:
        flags = rule_flags(r)
        if flags["a"] or flags["b"]:
            all_records.append(with_duration(r, flags))
    assert all(r["in_rule_a"] for r in all_records if r["in_rule_b"] or r["in_rule_c"] or r["in_rule_d"])
    completed = [r for r in common[-1][1] if r["status"] == "COMPLETED"]
    records = [r for r in all_records if r["status"] == "COMPLETED"]

    def in_rule(k: str, rs: list[dict]) -> list[dict]:
        return [r for r in rs if r[f"in_rule_{k}"]]

    main_rows = [r for r in records if r["phase"] in MAIN_PHASES]
    comb_rows = [r for r in records if r["phase"] not in MAIN_PHASES]
    kept = lambda rs: [r for r in rs if not r["exclusion_reason"]]
    # "before" the < 1 month rule = only the hard-invalid rules applied
    valid = lambda rs: [r for r in rs if r["exclusion_reason"] in ("", "under_1_month")]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_main = [r for r in all_records if r["phase"] in MAIN_PHASES]
    write_csv(OUT_DIR / "durations_phase2_phase3.csv", kept(all_main), ROW_FIELDS)
    write_csv(OUT_DIR / "durations_combined_sensitivity.csv", kept(comb_rows), ROW_FIELDS)
    for k in RULES:
        name = "durations_main.csv" if k == MAIN_RULE else f"durations_rule_{k}.csv"
        vec = [{f: r[f] for f in VECTOR_FIELDS} for r in kept(in_rule(k, main_rows))]
        write_csv(OUT_DIR / name, vec, VECTOR_FIELDS)
    write_csv(OUT_DIR / "durations_excluded.csv",
              [r for r in records if r["exclusion_reason"]], ROW_FIELDS)
    (OUT_DIR / "durations_excluded_outliers.csv").unlink(missing_ok=True)  # superseded

    summary, short_cmp, eras = [], [], []
    for k in RULES:
        for set_name, rs in (("main", main_rows), ("sensitivity_combined", comb_rows)):
            rk = in_rule(k, rs)
            for ph in sorted({r["phase"] for r in rk}):
                rp = [r for r in rk if r["phase"] == ph]
                summary.append({"rule": k, "set": set_name, "phase": ph, **summarize(kept(rp))})
                if set_name == "main":
                    b, a = summarize(valid(rp)), summarize(kept(rp))
                    short_cmp.append({
                        "rule": k, "phase": ph,
                        "n_before": b["n"], "median_before": b["median"],
                        "n_under_1_month": b["n"] - a["n"],
                        "n_after": a["n"], "median_after": a["median"],
                        "median_diff": round(a["median"] - b["median"], 2),
                    })
    term = []
    for k in RULES:
        for ph in MAIN_PHASES:
            rp = kept([r for r in in_rule(k, all_main) if r["phase"] == ph])
            for subset, rs in (("completed", [r for r in rp if r["status"] == "COMPLETED"]),
                               ("completed+terminated", rp),
                               ("terminated only", [r for r in rp if r["status"] == "TERMINATED"])):
                term.append({"rule": k, "statuses": subset, "phase": ph, **summarize(rs)})
    for label, _, _ in ERAS:
        for ph in MAIN_PHASES:
            rp = [r for r in kept(in_rule("a", main_rows)) if r["phase"] == ph and era_of(r["start_year"]) == label]
            eras.append({"rule": "a", "era": label, "phase": ph, **summarize(rp)})

    stat_fields = ["n", "median", "p25", "p75", "min", "max"]
    write_csv(OUT_DIR / "duration_summary.csv", summary, ["rule", "set", "phase"] + stat_fields)
    write_csv(OUT_DIR / "duration_short_exclusion.csv", short_cmp, list(short_cmp[0]))
    write_csv(OUT_DIR / "duration_by_era.csv", eras, ["rule", "era", "phase"] + stat_fields)
    write_csv(OUT_DIR / "duration_terminated_sensitivity.csv", term, ["rule", "statuses", "phase"] + stat_fields)
    for s in summary:
        print(s)

    write_log(snap, common, completed, records, main_rows, comb_rows, summary, short_cmp, eras, term)
    print(f"log -> {LOG_PATH}")


def fmt(v) -> str:
    if v is None or v == "":
        return ""
    return f"{v:,}" if isinstance(v, int) else f"{v}"


def write_log(snap, common, completed, records, main_rows, comb_rows, summary, short_cmp, eras, term) -> None:
    manifest = json.loads((snap.parent / snap.name.replace(".jsonl.gz", ".manifest.json")).read_text())
    phases = sorted({r["phase"] for r in common[0][1]})

    L = [
        "# Filter log: trial durations",
        "",
        "Generated by `scripts/clean_durations.py`. Do not edit by hand.",
        "",
        f"- Run at (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Snapshot: `data/raw/{snap.name}`",
        f"- Snapshot fetched at (UTC): {manifest['fetched_at_utc']}; API data timestamp: {manifest['api_data_timestamp']}",
        "",
        "## Date rules compared",
        "",
        "| Rule | Definition |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in RULES.items()],
        "",
        "Dates typed ESTIMATED are excluded under every rule. No main scenario has been chosen; "
        f"`durations_main.csv` currently holds rule {MAIN_RULE} per project instruction.",
        "",
        "## Common filter steps",
        "",
        "| # | Step | Remaining | Dropped | " + " | ".join(phases) + " |",
        "|---|---|---|---|" + "---|" * len(phases),
    ]
    prev = None
    for i, (label, rs) in enumerate(common):
        bp = by_phase(rs)
        dropped = "" if prev is None else f"{prev - len(rs):,}"
        L.append(f"| {i} | {label} | {len(rs):,} | {dropped} | " + " | ".join(f"{bp.get(p, 0):,}" for p in phases) + " |")
        prev = len(rs)

    L += [
        "",
        "## Steps by date rule",
        "",
        f"Starting from the {len(completed):,} **completed** industry trials "
        f"({len(common[-1][1]) - len(completed):,} terminated trials are used only in the sensitivity section below).",
        "",
        "| Step | " + " | ".join(f"Rule {k}" for k in RULES) + " |",
        "|---|" + "---|" * len(RULES),
    ]

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(f"{fn(k):,}" for k in RULES) + " |")

    def count(k, rs, reason=None):
        rk = [r for r in rs if r[f"in_rule_{k}"]]
        return len(rk) if reason is None else sum(r["exclusion_reason"] == reason for r in rk)

    row("Date rule applied", lambda k: count(k, records))
    row("Combined phases set aside (sensitivity)", lambda k: count(k, comb_rows))
    row("Single-phase PHASE2/PHASE3", lambda k: count(k, main_rows))
    for code, rule, _ in REASONS:
        row(f"− excluded: {rule}", lambda k, c=code: count(k, main_rows, c))
    row("**Single-phase kept**", lambda k: sum(1 for r in main_rows if r[f"in_rule_{k}"] and not r["exclusion_reason"]))
    for code, rule, _ in REASONS:
        row(f"Combined set − excluded: {rule}", lambda k, c=code: count(k, comb_rows, c))
    row("**Combined set kept**", lambda k: sum(1 for r in comb_rows if r[f"in_rule_{k}"] and not r["exclusion_reason"]))

    def decade_counts(rs):
        out: dict[str, int] = {}
        for r in rs:
            d = (r.get("start_date") or "")[:3]
            key = f"{d}0s" if d else "missing"
            out[key] = out.get(key, 0) + 1
        return out

    before = decade_counts(completed)
    after = {k: decade_counts([r for r in records if r[f"in_rule_{k}"]]) for k in ("a", "b")}  # c, d are year cuts of a
    L += [
        "",
        "## Coverage check: start decade of completed industry trials kept by each rule",
        "",
        "Older CT.gov records often have no date `type`; rule b drops them, rule a keeps them.",
        "",
        "| Start decade | Completed | Rule a | Rule a % | Rule b | Rule b % |",
        "|---|---|---|---|---|---|",
    ]
    for d in sorted(set(before) | set(after["a"]) | set(after["b"])):
        b = before.get(d, 0)
        cells = []
        for k in ("a", "b"):
            n = after[k].get(d, 0)
            cells += [f"{n:,}", f"{n / b:.0%}" if b else ""]
        L.append(f"| {d} | {b:,} | " + " | ".join(cells) + " |")

    L += [
        "",
        "## Duration definition",
        "",
        "- Duration = primary completion date − start date, in months (days / 30.4375).",
        f"- When CT.gov gives only `YYYY-MM`, day {IMPUTED_DAY} is imputed (mid-month).",
        "- This is **trial** duration, not **phase** duration.",
        "",
        "## Outlier handling",
        "",
        "Rows are **excluded** (not winsorized) and saved to `data/processed/durations_excluded.csv`. "
        "Rules are checked in this order; each row gets one reason.",
        "",
        "| Rule | Reason |",
        "|---|---|",
        *[f"| {rule} | {why} |" for _, rule, why in REASONS],
        "",
        "## Duration summary by rule (completed trials, months, after all exclusions)",
        "",
        "Quantiles: `statistics.quantiles(method='inclusive')` (same as NumPy's default linear method).",
        "",
        "| Rule | Set | Phase | n | Median | P25 | P75 | Min | Max |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        L.append("| " + " | ".join(fmt(s.get(c)) for c in
                                     ("rule", "set", "phase", "n", "median", "p25", "p75", "min", "max")) + " |")

    L += [
        "",
        f"## Effect of the < {MIN_MONTHS} month exclusion (single-phase set)",
        "",
        "\"Before\" = after removing ≤ 0 and > 15 year durations only.",
        "",
        "| Rule | Phase | n before | Median before | Excluded (< 1 mo) | n after | Median after | Δ median |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in short_cmp:
        L.append("| " + " | ".join(fmt(s[c]) for c in s) + " |")

    L += [
        "",
        "## Sensitivity: including TERMINATED trials (single-phase set)",
        "",
        "Same date rules and duration exclusions; terminated trials use their (actual or untyped, per rule) "
        "primary completion date, i.e. when they stopped.",
        "",
        "| Rule | Statuses | Phase | n | Median | P25 | P75 |",
        "|---|---|---|---|---|---|---|",
        *["| " + " | ".join(fmt(t.get(c)) for c in ("rule", "statuses", "phase", "n", "median", "p25", "p75")) + " |"
          for t in term],
        "",
        "## Rule a: duration by start-year era (single-phase set)",
        "",
        "Caveat: only **completed** trials are included, so recent eras are right-censored — long trials "
        "started recently have not finished yet and are missing, which pulls recent medians down.",
        "",
        "| Era | Phase | n | Median | P25 | P75 |",
        "|---|---|---|---|---|---|",
    ]
    for e in eras:
        L.append("| " + " | ".join(fmt(e.get(c)) for c in ("era", "phase", "n", "median", "p25", "p75")) + " |")
    L.append("")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
