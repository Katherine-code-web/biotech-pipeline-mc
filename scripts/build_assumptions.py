"""Build data/assumptions.csv by parsing the source documents in data/sources/.

Values are parsed directly from the source files (no hand transcription):
  - BIO 2011-2020 report PDF  -> Figure 2 (p.7) and Figure 5b (p.11)
  - Wong et al. 2019 JATS XML -> Table 2 (path-by-path POS by therapeutic group)
Rows for model inputs without an official source are appended with
status=DECIDED (project decision + rationale) or status=ASSUMPTION (undecided, empty value).
Wong's "All without oncology" rows are status=DO_NOT_USE until checked against the PDF.

Usage: python scripts/build_assumptions.py   (requires pypdf)
"""
from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "sources"
OUT = ROOT / "data" / "assumptions.csv"

BIO_PDF = SRC / "bio_2011_2020.pdf"
WONG_XML = SRC / "wong2019_epmc.xml"

BIO_CITE = (
    "Thomas D, Chancellor D, Micklus A, et al. Clinical Development Success Rates "
    "and Contributing Factors 2011-2020. BIO / Informa Pharma Intelligence / QLS Advisors, Feb 2021"
)
WONG_CITE = (
    "Wong CH, Siah KW, Lo AW. Estimation of clinical trial success rates and related "
    "parameters. Biostatistics 2019;20(2):273-286. doi:10.1093/biostatistics/kxx069"
)

COLUMNS = [
    "param_id", "status", "source", "citation", "locator", "page", "page_verified",
    "scope", "therapeutic_area", "transition", "value_pct", "value_months", "value_usd_m", "value",
    "sensitivity_values", "role", "se_pct", "n",
    "method", "data_period", "notes", "rationale",
]
# value: dimensionless model input (counts, multipliers).
# sensitivity_values: ';'-separated values to run as sensitivity, in the row's own unit.
# role: for cost rows, base = base-case input, sensitivity = sensitivity range only, reference = not a model input.

ROW_RE = re.compile(r"^(.+?)(\*?)\s+((?:\d+\s+\d+\.\d%\s*){4})$")


def parse_bio_table(page_no: int, transitions: list[str], locator: str, metric: str) -> list[dict]:
    text = PdfReader(BIO_PDF).pages[page_no - 1].extract_text()
    # Guard: printed page number must match PDF page index.
    assert text.startswith(f"{page_no}/"), f"page header mismatch on PDF p.{page_no}"
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        area, starred = m.group(1).strip(), m.group(2)
        nums = m.group(3).split()
        for i, tr in enumerate(transitions):
            n, pct = nums[2 * i], nums[2 * i + 1].rstrip("%")
            notes = []
            if tr == "NDA_APP":
                notes.append("NDA/BLA->approval includes resubmissions")
            if area == "Gastroenterology":
                notes.append("Defined as non-IBD (p.7)")
            if starred:
                notes.append("Marked * in source; footnote text not found in extracted page")
            rows.append({
                "param_id": f"BIO21_{metric}_{tr}_{slug(area)}",
                "status": "SOURCED",
                "source": "BIO2021",
                "citation": BIO_CITE,
                "locator": locator,
                "page": page_no,
                "page_verified": "yes",
                "scope": "all indications, all modalities",
                "therapeutic_area": area,
                "transition": tr,
                "value_pct": pct,
                "se_pct": "",
                "n": n,
                "method": "phase-by-phase (advanced / (advanced+suspended)); Biomedtracker",
                "data_period": "2011-2020",
                "notes": "; ".join(notes),
            })
    assert len(rows) == 16 * len(transitions), f"expected 16 areas on p.{page_no}, got {len(rows)//4}"
    return rows


def parse_wong_table2() -> list[dict]:
    root = ET.parse(WONG_XML).getroot()
    tw = next(t for t in root.iter("table-wrap") if t.get("id") == "T2")
    trs = [[" ".join("".join(c.itertext()).split()) for c in tr] for tr in tw.iter("tr")]

    rows, section, i = [], None, 0
    while i < len(trs):
        cells = trs[i]
        if len(cells) == 1 or (cells and "indications" in cells[0].lower() and not any(cells[1:])):
            section = cells[0]
            i += 1
            continue
        if len(cells) == 9 and re.fullmatch(r"[\d ]+", cells[1] or "x"):
            se = trs[i + 1]
            area = (cells[0] + (" " + se[0] if se[0] else "")).replace("/ ", "/")
            area = area.replace("Infectious Disease", "Infectious disease")  # source is inconsistent
            n12, p12, n23, p23, p2a, n3a, p3a, p1a = (c.replace(" ", "") for c in cells[1:])
            s12, s23, s2a, s3a, s1a = (se[k].strip("()") for k in (2, 4, 5, 7, 8))
            lead = section.lower().startswith("lead")
            for tr, val, sev, n in [
                ("P1_P2", p12, s12, n12), ("P2_P3", p23, s23, n23), ("P2_APP", p2a, s2a, ""),
                ("P3_APP", p3a, s3a, n3a), ("P1_APP", p1a, s1a, ""),
            ]:
                notes, status, rationale = [], "SOURCED", ""
                if area == "All without oncology":
                    status = "DO_NOT_USE"
                    rationale = "Row withheld until checked against the journal PDF"
                    if tr in ("P2_P3", "P2_APP"):
                        notes.append("As printed: POS(2->3) equals POS(2->APP); likely a typesetting error in source - verify before use")
                if area == "Overall" and not lead and tr in ("P2_P3", "P2_APP"):
                    notes.append("As printed: SE looks inconsistent with n (same as Ophthalmology SE) - verify before use")
                rows.append({
                    "param_id": f"WONG19_{'LEAD' if lead else 'ALL'}_{tr}_{slug(area)}",
                    "status": status,
                    "source": "Wong2019",
                    "citation": WONG_CITE,
                    "locator": f"Table 2 ({section})",
                    "page": "273-286 (article range)",
                    "page_verified": "no",
                    "scope": section,
                    "therapeutic_area": area,
                    "transition": tr,
                    "value_pct": val,
                    "se_pct": sev,
                    "n": n,
                    "method": "path-by-path; Citeline Trialtrove/Pharmaprojects; no separate NDA stage (P3_APP covers Phase 3 -> approval)",
                    "data_period": "2000-01-01 to 2015-10-31",
                    "notes": "; ".join(notes),
                    "rationale": rationale,
                })
            i += 2
            continue
        i += 1
    assert len(rows) == 2 * 11 * 5, f"unexpected Wong row count {len(rows)}"
    return rows


# (param_id, status, description, notes, rationale)
# status: DECIDED = a project decision with a stated rationale;
#         ASSUMPTION = no official data and not yet decided (value left empty).
# param_ids keep their original ASSUMPTION_ prefix so references stay stable.
DUR = "data/processed/duration_summary.csv; docs/filter_log.md"
ASSUMPTIONS = [
    ("ASSUMPTION_CTGOV_PHASE2_3_COMBINED", "DECIDED",
     "How to treat ClinicalTrials.gov trials labelled PHASE2+PHASE3 (seamless)",
     "Excluded from the main duration set; kept in data/processed/durations_combined_sensitivity.csv",
     "A seamless trial's duration cannot be attributed to Phase 2 or Phase 3 alone; keeping it separate "
     "lets us test sensitivity without contaminating single-phase estimates"),
    ("ASSUMPTION_CTGOV_PHASE1_2_COMBINED", "DECIDED",
     "How to treat ClinicalTrials.gov trials labelled PHASE1+PHASE2",
     "Excluded from the main duration set; kept in data/processed/durations_combined_sensitivity.csv",
     "Same reason as PHASE2+PHASE3; Phase 1/2 trials also include a safety component not present in Phase 2"),
    ("ASSUMPTION_SPONSOR_SCOPE", "DECIDED",
     "Restrict CT.gov trials to industry sponsors",
     "Lead sponsor class = INDUSTRY; collaborators are ignored",
     "BIO and Wong (industry tables) measure industry programs; matching the sponsor scope keeps durations "
     "and success rates describing the same population"),
    ("ASSUMPTION_DATE_TYPE_ACTUAL_ONLY", "DECIDED",
     "Which date rule defines the main duration sample",
     "Main: rule d = completed, untyped dates treated as ACTUAL, start year 2010-2019 "
     "(data/processed/durations_main.csv). Sensitivity: rules a (all years), b (strict ACTUAL), c (2011-2020) "
     "in durations_rule_{a,b,c}.csv, and completed+terminated (docs/filter_log.md). ESTIMATED dates excluded under all",
     "Rule d medians lie between rules a and b; no era trend across 2005-2019; excluding 2020+ starts avoids "
     "right-censoring (long recent trials not yet completed)"),
    ("ASSUMPTION_DATE_DAY_IMPUTATION", "DECIDED",
     "Day used when CT.gov gives only YYYY-MM",
     "Day 15 imputed; imputed counts in docs/filter_log.md",
     "Mid-month minimises the maximum error (about +/-0.5 month) and is unbiased if the true day is uniform"),
    ("ASSUMPTION_DURATION_OUTLIER_RULE", "DECIDED",
     "Handling of implausible trial durations",
     "Exclude duration <= 0 months, < 1 month, or > 180 months (15 years); excluded rows saved to "
     "data/processed/durations_excluded.csv",
     "Non-positive durations are data-entry errors; < 1 month is too short for a Phase 2/3 efficacy trial "
     "(mostly single-dose/PK studies); >15 years is implausible for one Phase 2/3 trial. "
     "Exclusion (not winsorizing) because these values are errors, not extreme-but-real observations"),
    ("ASSUMPTION_PHASE_DURATION", "DECIDED",
     "Phase 2 and Phase 3 durations",
     "Method: trial duration = primary completion - start, completed industry single-phase trials, "
     f"resampled in the simulation. Values in {DUR}. Date rule d (ASSUMPTION_DATE_TYPE_ACTUAL_ONLY)",
     "Only public source of observed start/completion dates at scale. Trial duration is a proxy for phase "
     "duration (see ASSUMPTION_TRIAL_TO_PROGRAM)"),
    ("ASSUMPTION_TRIAL_TO_PROGRAM", "ASSUMPTION",
     "Mapping from individual CT.gov trials to drug development programs",
     "CT.gov is trial-level; BIO and Wong rates are program-level. No official crosswalk. "
     "Trial duration is used as a proxy for phase duration, which ignores parallel trials and gaps between trials",
     ""),
    ("ASSUMPTION_NDA_REVIEW_DURATION", "DECIDED",
     "Duration of the submission/review step (BIO NDA_APP gate) and of review time inside Wong P3_APP",
     "Review time = FDA_PDUFA_PRIORITY_NME (8 months) with probability p_priority, else FDA_PDUFA_STANDARD_NME "
     "(12 months). p_priority is ASSUMPTION_P_PRIORITY. Wong P3_APP time = Phase 3 duration + review time",
     "CT.gov has no regulatory review dates; PDUFA goals are the official FDA targets. "
     "Goals are met for 90% of applications and are targets, not observed review times"),
    ("ASSUMPTION_P_PRIORITY", "ASSUMPTION",
     "Share of applications receiving priority review (p_priority)",
     "Value not filled. Sensitivity range: p_priority in {0, 0.5, 1}. Passed to the model as a parameter, "
     "never hard-coded. Reference (not a model input): FDA CDER 'New Drug Therapy Approvals 2023' "
     "(https://www.fda.gov/media/175253/download) printed p.11 (PDF p.13): "
     "'31 of the 55 drugs (56%) approved in 2023 were designated as Priority Review'. "
     "Two biases if used: (1) share among APPROVED novel drugs, not among submissions (rejected applications "
     "are missing); (2) CDER only, CBER biologics excluded. "
     "The yearly web lists (Novel Drug Approvals for YYYY) have no priority-review column",
     ""),
    ("ASSUMPTION_NO_RESUBMISSION_CYCLE", "ASSUMPTION",
     "Complete-response letters and resubmission cycles",
     "Not modelled: one review period per submission. BIO NDA_APP (90.6%) counts eventual approval including "
     "resubmissions, so approved timelines that needed a resubmission are understated",
     ""),
    ("ASSUMPTION_GAP_MONTHS", "ASSUMPTION",
     "gap_months: time between phases, added twice on the path (Phase 2 end -> Phase 3 start, "
     "Phase 3 end -> submission)",
     "Default 0 (base case, timelines biased short). Sensitivity range: gap_months in {0, 3, 6}. No source used",
     ""),
    ("ASSUMPTION_REVIEW_EXTRA_MONTHS", "ASSUMPTION",
     "review_extra_months: extra time added to every review period on top of the PDUFA goal",
     "Default 0. No sensitivity range set. No source used",
     ""),
    ("ASSUMPTION_FAILURE_TIMING", "DECIDED",
     "When a failing asset stops accruing time",
     "Cumulative time runs to the end of the gate at which it fails (e.g. Phase 2 failure = Phase 2 duration only)",
     "Project instruction; the failure is observed when the phase's trial reads out"),
    ("ASSUMPTION_PHASE_COST", "DECIDED",
     "Cost per phase (clinical trial direct cost)",
     "Base case: ASPE14_COST_P2_MEAN and ASPE14_COST_P3_MEAN (Table 2 weighted means, role=base). Sensitivity: "
     "Table 1 lowest/highest therapeutic area (ASPE14_COST_P{2,3}_{MIN,MAX}_AREA, role=sensitivity). "
     "Costs are fixed, not sampled. A phase's cost is paid on entering the phase, whether it then succeeds or "
     "fails: Phase 2 always, Phase 3 only after passing Phase 2. Total = trials_per_phase x "
     "overhead_multiplier x cpi_factor x sum of phase costs",
     "ASPE does not publish trial-level variance (its SD is across therapeutic-area means), so there is no "
     "sourced distribution to sample from. Spending varies through which gate each asset reaches"),
    ("ASSUMPTION_SUBMISSION_COST_EXCLUDED", "DECIDED",
     "Cost of the submission/review step",
     "Not counted: no cost is charged at NDA_APP (BIO) or for the review part of P3_APP (Wong). "
     "ASPE14_COST_NDA_FEE (PDUFA filing fee only) stays CANDIDATE / reference",
     "Project decision: the cost scope is clinical trial direct cost"),
    ("ASSUMPTION_TRIALS_PER_PHASE", "ASSUMPTION",
     "trials_per_phase: number of trials run per phase (ASPE costs are per trial)",
     "Default 1. Sensitivity: 1 and 2. No source used", ""),
    ("ASSUMPTION_CPI_FACTOR", "ASSUMPTION",
     "cpi_factor: price-level adjustment applied to ASPE nominal 2004-2012 dollars",
     "Default 1.0 (no adjustment: results in mixed-year nominal dollars). No source used", ""),
    ("ASSUMPTION_OVERHEAD_MULTIPLIER", "ASSUMPTION",
     "overhead_multiplier: sponsor costs not captured by ASPE trial costs",
     "Default 1.0. Sensitivity: 1.5 and 2.0. No source used", ""),
    ("ASSUMPTION_SUCCESS_RATE_SOURCE", "DECIDED",
     "Which source provides the base-case phase transition probabilities",
     "BIO 2011-2020 is the main scenario; Wong 2019 is the sensitivity scenario. Never mixed within one run",
     "BIO has a separate submission->approval gate and a period (2011-2020) closer to the CT.gov duration "
     "sample; Wong uses a different method (path-by-path) and database, so it serves as a robustness check"),
    ("ASSUMPTION_WONG_NDA_SPLIT", "DECIDED",
     "Split of Wong P3_APP into Phase3->NDA and NDA->approval",
     "No split: Wong scenario uses two gates, Phase 2->3 (P2_P3) and Phase 3->approval (P3_APP)",
     "Wong reports Phase 3->approval only; splitting it would add an input with no source. "
     "Project scope defines the Wong scenario as two gates"),
    ("ASSUMPTION_PHASE_INDEPENDENCE", "ASSUMPTION",
     "Independence of phase outcomes and of programs within a pipeline",
     "Each transition is treated as independent given the program reached that phase; programs sharing a "
     "target, platform or company are treated as independent of one another",
     ""),
    ("ASSUMPTION_RATE_STATIONARITY", "ASSUMPTION",
     "Historical success rates apply to future programs",
     "Both sources are historical (2000-2015, 2011-2020); applying them forward is an assumption",
     ""),
]


# Default and sensitivity values the project set for ASSUMPTION rows (still ASSUMPTION: no source).
ASSUMPTION_VALUES = {
    "ASSUMPTION_P_PRIORITY": {"sensitivity_values": "0;0.5;1"},
    "ASSUMPTION_GAP_MONTHS": {"value_months": 0, "sensitivity_values": "0;3;6"},
    "ASSUMPTION_REVIEW_EXTRA_MONTHS": {"value_months": 0},
    "ASSUMPTION_TRIALS_PER_PHASE": {"value": 1, "sensitivity_values": "1;2"},
    "ASSUMPTION_CPI_FACTOR": {"value": 1.0},
    "ASSUMPTION_OVERHEAD_MULTIPLIER": {"value": 1.0, "sensitivity_values": "1.5;2.0"},
}


def assumption_rows() -> list[dict]:
    return [
        {**{c: "" for c in COLUMNS}, "param_id": pid, "status": status,
         "source": "DECISION" if status == "DECIDED" else "ASSUMPTION",
         "scope": desc, **ASSUMPTION_VALUES.get(pid, {}),
         "notes": note, "rationale": why}
        for pid, status, desc, note, why in ASSUMPTIONS
    ]


FDA_LETTER_URL = "https://www.fda.gov/media/151712/download"
FDA_PRIORITY_URL = ("https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-"
                    "priority-review/priority-review")
FDA_CITE = ("FDA. PDUFA Reauthorization Performance Goals and Procedures, Fiscal Years 2023 Through 2027 "
            f"(PDUFA VII commitment letter). {FDA_LETTER_URL}")
# (param_id, status, description, months from submission, goal as written on p.4)
PDUFA_GOALS = [
    ("FDA_PDUFA_STANDARD_NME", "DECIDED", "Standard review, NME NDA / original BLA", 12,
     "10 months of the 60-day filing date"),
    ("FDA_PDUFA_PRIORITY_NME", "DECIDED", "Priority review, NME NDA / original BLA", 8,
     "6 months of the 60-day filing date"),
    ("FDA_PDUFA_STANDARD_NON_NME", "ASSUMPTION", "Standard review, non-NME original NDA", 10,
     "10 months of receipt"),
    ("FDA_PDUFA_PRIORITY_NON_NME", "ASSUMPTION", "Priority review, non-NME original NDA", 6,
     "6 months of receipt"),
]


def pdufa_rows() -> list[dict]:
    """FDA review-time goals. NME rows are model inputs (DECIDED); non-NME rows are reference only."""
    rows = []
    for pid, status, desc, months, goal in PDUFA_GOALS:
        derived = "60-day filing period + " if "filing" in goal else ""
        rows.append({
            **{c: "" for c in COLUMNS},
            "param_id": pid, "status": status, "source": "FDA",
            "citation": FDA_CITE,
            "locator": "Sec. I.A.1 (NDA/BLA submissions and resubmissions)",
            "page": 4, "page_verified": "yes",
            "scope": desc, "transition": "NDA_APP", "value_months": months,
            "method": "PDUFA goal date (target), not an observed review time",
            "data_period": "FY2023-FY2027",
            "notes": (f"Source text: 'Review and act on 90 percent of ... within {goal}'. "
                      f"value_months = {derived}{goal.split(' of')[0]} from submission. "
                      f"Consistent with FDA priority review page ({FDA_PRIORITY_URL}): "
                      "'within 6 months (compared to 10 months under standard review)'; page content current as of 01/04/2018. "
                      "Source files: data/sources/fda_pdufa_vii_commitment_letter.pdf, fda_priority_review_page.html"),
            "rationale": ("Project decision: record standard 12 / priority 8 months as the review-time inputs. "
                          "Model does not include resubmission cycles (ASSUMPTION_NO_RESUBMISSION_CYCLE)"
                          if status == "DECIDED" else "Reference only (novel drugs are NME/original BLA)"),
        })
    return rows


ASPE_URL = "https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf"
ASPE_PAGE_URL = "https://aspe.hhs.gov/reports/examination-clinical-trial-costs-barriers-drug-development"
ASPE_CITE = ("Sertkaya A, Birkenbach A, Berlind A, Eyraud J (Eastern Research Group). Examination of Clinical "
             "Trial Costs and Barriers for Drug Development. Report to HHS ASPE, July 25, 2014. " + ASPE_URL)
ASPE_DEFINITION = (
    "Per-study cost: one trial per phase, NOT a whole program, and NOT inclusive of failures "
    "(p.3-2, PDF p.29; Table 1 note [b]). Includes 25% site overhead and a 30% 'All Other Costs' "
    "extrapolation; undiscounted. "
    # (a) what the SD is
    "SD DEFINITION: p.3-4 (PDF p.31): 'we computed a weighted mean cost ... and its weighted standard deviation "
    "... where the weights are the total number of contracts'; the formula runs over therapeutic-area means "
    "(sum over therapeutic areas of the reported mean minus the across-area average). Table 2 note (p.3-6): "
    "'the reported numbers represent weighted average costs and standard deviations'. So the SD is the "
    "contract-weighted spread of therapeutic-area MEAN costs across areas: neither the SD between individual "
    "trials nor the standard error of the mean. Trial-level variances were supplied by Medidata (p.2-9) but "
    "are not reported. "
    # (b) what 'not inclusive of failures' means
    "FAILURES: p.3-2 (PDF p.29): 'Table 1 presents the total costs for each of the therapeutic areas included "
    "in our model by clinical trial phase (assuming one trial per phase and not inclusive of failures).' "
    "Meaning: the figure is the cost of one trial and is not grossed up for the trials of programs that fail "
    "(contrast p.4-1: DiMasi et al. estimates 'represent fully capitalized costs and are inclusive of failures'). "
    "Sample: the report does not say the trials completed or succeeded. Costs are built from negotiated "
    "contracts (PICAS/CROCAS, p.2-9) times PLANNED patients and sites (p.3-1), i.e. budgeted cost per trial "
    "regardless of outcome; whether early-stopped trials are in the database is not stated. "
    # (c) currency and cost year
    "CURRENCY/YEAR: nominal US dollars, mixed years. p.2-9: 'The data are from 2004 and later and have not been "
    "adjusted for inflation by Medidata ... we were unable to adjust them for inflation'; p.2-10 gives the "
    "range of the itemized cost data as 2004-2012 (only the revenue figures were inflated to 2008 dollars). "
    "U.S. trials only (p.2-9). "
    f"Report landing page: {ASPE_PAGE_URL}")
ASPE_BASE_NOTE = ("One trial; nominal US dollars; 2004-2012 contract data; U.S. trials; "
                  "no allocation of failed programs' costs")
ASPE_SENS_NOTE = ("Sensitivity range only (lowest/highest therapeutic-area mean in Table 1). The Phase 2 and "
                  "Phase 3 extremes come from different therapeutic areas")
# (param_id, status, role, transition, value $M, locator, printed page, pdf page, scope, extra note)
ASPE_COSTS = [
    ("ASPE14_COST_P2_MEAN", "SOURCED", "base", "P2", 13.35, "Table 2, 'Total (in $ Million)' row", "3-6", 33,
     "All therapeutic areas, contract-weighted mean",
     ASPE_BASE_NOTE + ". SD $2.51M (weighted SD across therapeutic-area means; see SD DEFINITION)"),
    ("ASPE14_COST_P3_MEAN", "SOURCED", "base", "P3", 19.89, "Table 2, 'Total (in $ Million)' row", "3-6", 33,
     "All therapeutic areas, contract-weighted mean",
     ASPE_BASE_NOTE + ". SD $8.59M (weighted SD across therapeutic-area means; see SD DEFINITION)"),
    ("ASPE14_COST_P2_MIN_AREA", "SOURCED", "sensitivity", "P2", 7.0, "Table 1, Phase 2 column", "3-3", 30,
     "Lowest therapeutic area (Cardiovascular)", ASPE_SENS_NOTE),
    ("ASPE14_COST_P2_MAX_AREA", "SOURCED", "sensitivity", "P2", 19.6, "Table 1, Phase 2 column", "3-3", 30,
     "Highest therapeutic area (Hematology)", ASPE_SENS_NOTE),
    ("ASPE14_COST_P3_MIN_AREA", "SOURCED", "sensitivity", "P3", 11.5, "Table 1, Phase 3 column", "3-3", 30,
     "Lowest therapeutic area (Dermatology)", ASPE_SENS_NOTE),
    ("ASPE14_COST_P3_MAX_AREA", "SOURCED", "sensitivity", "P3", 52.9, "Table 1, Phase 3 column", "3-3", 30,
     "Highest therapeutic area (Pain and Anesthesia)", ASPE_SENS_NOTE),
    ("ASPE14_COST_NDA_FEE", "CANDIDATE", "reference", "NDA", 2.0, "Table 1, 'FDA NDA/BLA Review Phase' column",
     "3-3", 30, "All therapeutic areas",
     "This is the PDUFA filing fee only (Table 1 note [c]), not sponsor review costs. "
     "Not counted (ASSUMPTION_SUBMISSION_COST_EXCLUDED)"),
]
ASPE_RATIONALE = {
    "base": "Base-case phase cost (ASSUMPTION_PHASE_COST)",
    "sensitivity": "Sensitivity range for phase cost (ASSUMPTION_PHASE_COST); not the base case",
    "reference": "Reference only; not used by the model",
}


def aspe_rows() -> list[dict]:
    """Phase cost rows: Table 2 means are the base case, Table 1 extremes the sensitivity range."""
    return [{
        **{c: "" for c in COLUMNS},
        "param_id": pid, "status": status, "source": "ASPE2014", "citation": ASPE_CITE,
        "locator": loc, "page": f"{printed} (PDF p.{pdf})", "page_verified": "yes",
        "scope": scope, "transition": tr, "value_usd_m": val, "role": role,
        "method": "Per-study cost from itemized Medidata contract data",
        "data_period": "2004-2012 contract data, nominal USD (not inflation-adjusted); published 2014",
        "notes": "; ".join(x for x in (extra, ASPE_DEFINITION) if x),
        "rationale": ASPE_RATIONALE[role],
    } for pid, status, role, tr, val, loc, printed, pdf, scope, extra in ASPE_COSTS]


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").upper()


def main() -> None:
    rows = (
        parse_bio_table(7, ["P1_P2", "P2_P3", "P3_NDA", "NDA_APP"], "Figure 2", "POS")
        + parse_bio_table(11, ["P1_APP", "P2_APP", "P3_APP", "NDA_APP"], "Figure 5b", "LOA")
        + parse_wong_table2()
        + assumption_rows()
        + pdufa_rows()
        + aspe_rows()
    )
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
