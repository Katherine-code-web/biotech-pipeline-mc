"""Clinical trial direct cost and risk report for N = 1..10 assets, BIO vs Wong.

Every model input is read from data/assumptions.csv by param_id: gate probabilities, durations,
review months, phase costs, cost multipliers, gap_months / review_extra_months defaults, and the
sensitivity values (p_priority, trials_per_phase, overhead_multiplier).

Outputs:
  data/processed/cost_results.csv          cost metrics per cost case, N and scenario
  data/processed/cost_approval_within.csv  P(>=1 approved within X years) per p_priority, N and scenario
  data/processed/cost_distribution.csv     base-case distribution of total cost per N and scenario
  docs/cost_results.md

Usage: python scripts/run_costs.py
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from biotech_pipeline_mc.costs import (
    MULTIPLIER_IDS,
    PHASE_COST_IDS,
    analytic_cost_distribution,
    analytic_expected_asset_cost,
    discrete_quantile,
    discrete_var_cvar,
    asset_costs,
    gate_costs,
    load_cost_inputs,
    var_cvar,
)
from biotech_pipeline_mc.gates import DEFAULT_SEED, analytic_approval
from biotech_pipeline_mc.params import SCENARIOS, load_gate_probs, load_sensitivity_values, load_value
from biotech_pipeline_mc.timing import load_timing_inputs, simulate_portfolio_assets, summarize_portfolio

ROOT = Path(__file__).resolve().parents[1]
COST_CSV = ROOT / "data" / "processed" / "cost_results.csv"
WITHIN_CSV = ROOT / "data" / "processed" / "cost_approval_within.csv"
DIST_CSV = ROOT / "data" / "processed" / "cost_distribution.csv"
MD_OUT = ROOT / "docs" / "cost_results.md"

# Reporting settings (not model inputs)
N_SIMS = 200_000
PORTFOLIO_SIZES = range(1, 11)
ALPHA = 0.95
HORIZONS_YEARS = [5, 7, 10]
SENS_SIZES = [1, 5, 10]

TITLE = "Clinical trial direct cost"
UNIT = "US$ million (nominal, mixed years 2004–2012)"


def q(x: np.ndarray, level: float) -> float:
    # inverted_cdf: always an attainable value (costs take only a few distinct values)
    return float(np.quantile(x, level, method="inverted_cdf"))


def cost_cases() -> list[tuple[str, str, dict]]:
    """(label, cost_case, multiplier overrides): base, the Table 1 range, then multipliers one at a time."""
    cases = [("base", "base", {})] + [(c, c, {}) for c in PHASE_COST_IDS if c != "base"]
    defaults = load_cost_inputs()
    for name, pid in MULTIPLIER_IDS.items():
        for v in load_sensitivity_values(pid):
            if v != getattr(defaults, name):
                cases.append((f"{name}={v:g}", "base", {name: v}))
    return cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-sims", type=int, default=N_SIMS)
    args = ap.parse_args()

    timing = load_timing_inputs()
    p_values = load_sensitivity_values("ASSUMPTION_P_PRIORITY")
    gap = load_value("ASSUMPTION_GAP_MONTHS", "value_months", ("ASSUMPTION", "DECIDED"))
    gap_values = sorted({gap, *load_sensitivity_values("ASSUMPTION_GAP_MONTHS")})
    review_extra = load_value("ASSUMPTION_REVIEW_EXTRA_MONTHS", "value_months", ("ASSUMPTION", "DECIDED"))
    cases = cost_cases()
    case_inputs = {label: load_cost_inputs(cc, **ov) for label, cc, ov in cases}

    cost_rows, within_rows, dist_rows = [], [], []
    for n_assets in PORTFOLIO_SIZES:
        for i, scenario in enumerate(SCENARIOS):
            gates = load_gate_probs(scenario)
            p_app = analytic_approval(gates.probs)
            stopped_at = None
            for gap_run in gap_values:
                for p_priority in p_values:
                    # same seed as run_timed.py; gate outcomes depend on neither p_priority nor gap
                    rng = np.random.default_rng([DEFAULT_SEED, n_assets, i])
                    assets = simulate_portfolio_assets(gates.names, gates.probs, n_assets, args.n_sims, timing,
                                                       p_priority, rng, gap_months=gap_run,
                                                       review_extra_months=review_extra)
                    port = summarize_portfolio(assets)
                    t = np.nan_to_num(port.first_approval_months, nan=np.inf)
                    # time-based probabilities have no closed form: simulation only
                    within_rows.append({"p_priority": p_priority, "gap_months": gap_run, "n_assets": n_assets,
                                        "scenario": scenario,
                                        **{f"p_approved_within_{y}y": round(float((t <= 12 * y).mean()), 4)
                                           for y in HORIZONS_YEARS}})
                    if stopped_at is None:
                        stopped_at, n_approved = assets.stopped_at, port.n_approved
                    assert np.array_equal(stopped_at, assets.stopped_at)

            zero = n_approved == 0
            for label, cost_case, overrides in cases:
                costs = case_inputs[label]
                gc = gate_costs(gates.names, costs)
                e_asset = analytic_expected_asset_cost(gates.probs, gc)
                # exact (analytic) distribution: the reported values
                totals, prob, zprob = analytic_cost_distribution(gates.probs, gc, n_assets)
                a_var, a_cvar = discrete_var_cvar(totals, prob, ALPHA)
                exact = {
                    "mean": n_assets * e_asset,
                    "median": discrete_quantile(totals, prob, 0.5),
                    "p95": discrete_quantile(totals, prob, ALPHA),
                    "var95": a_var, "cvar95": a_cvar,
                    "p_zero_approved": (1 - p_app) ** n_assets,
                    "p_at_least_one": 1 - (1 - p_app) ** n_assets,
                    "zero_approved_median": discrete_quantile(totals, zprob, 0.5),
                    "zero_approved_p95": discrete_quantile(totals, zprob, ALPHA),
                    "cost_per_approval": e_asset / p_app,
                }
                # simulation: verification only
                total = asset_costs(stopped_at, gc).sum(axis=1)
                s_var, s_cvar = var_cvar(total, ALPHA)
                sim = {
                    "mean": float(total.mean()), "median": q(total, 0.5), "p95": q(total, ALPHA),
                    "var95": s_var, "cvar95": s_cvar,
                    "p_zero_approved": float(zero.mean()), "p_at_least_one": float(1 - zero.mean()),
                    "zero_approved_median": q(total[zero], 0.5), "zero_approved_p95": q(total[zero], ALPHA),
                    # total cost summed over all runs / approvals summed over all runs
                    "cost_per_approval": float(total.sum() / n_approved.sum()),
                }
                row = {"case": label, "cost_case": cost_case,
                       "phase2_usd_m": costs.phase2, "phase3_usd_m": costs.phase3,
                       "trials_per_phase": costs.trials_per_phase,
                       "overhead_multiplier": costs.overhead_multiplier, "cpi_factor": costs.cpi_factor,
                       "n_assets": n_assets, "scenario": scenario}
                for m in exact:
                    row[f"{m}_analytic"] = round(exact[m], 6)
                    row[f"{m}_sim"] = round(sim[m], 6)
                cost_rows.append(row)
                if label == "base":
                    for t_, pr, zp in zip(totals, prob, zprob):
                        at = np.isclose(total, t_)
                        dist_rows.append({"n_assets": n_assets, "scenario": scenario, "total_usd_m": round(t_, 6),
                                          "probability_analytic": round(pr, 6),
                                          "probability_sim": round(float(at.mean()), 6),
                                          "probability_and_zero_approved_analytic": round(zp, 6),
                                          "probability_and_zero_approved_sim": round(float((at & zero).mean()), 6)})

    for path, rows in ((COST_CSV, cost_rows), (WITHIN_CSV, within_rows), (DIST_CSV, dist_rows)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    scen = list(SCENARIOS)

    def get(case, n_assets):
        return {r["scenario"]: r for r in cost_rows if r["case"] == case and r["n_assets"] == n_assets}

    def pair(r, key, fmt="{:.1f}"):
        return " / ".join(fmt.format(r[s][key]) if r[s][key] != "" else "—" for s in scen)

    base = case_inputs["base"]
    vs = " / ".join(scen)
    L = [
        f"# {TITLE}: BIO vs Wong",
        "",
        "Generated by `scripts/run_costs.py`. Do not edit by hand.",
        "",
        f"- Run at (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Runs per cell: {args.n_sims:,}; seed {DEFAULT_SEED} (per cell: [seed, N, scenario index], same as "
        f"run_timed.py); numpy {np.__version__}",
        f"- Unit: **{UNIT}**. Only Phase 2 and Phase 3 trial costs are counted; submission and review are not.",
        f"- Base-case phase costs (SOURCED, ASPE 2014 Table 2 weighted mean, per trial): "
        f"Phase 2 {base.phase2:g}, Phase 3 {base.phase3:g}.",
        f"- Multipliers (ASSUMPTION defaults): trials_per_phase = {base.trials_per_phase:g}, "
        f"overhead_multiplier = {base.overhead_multiplier:g}, cpi_factor = {base.cpi_factor:g}.",
        "- Rule: a phase's cost is paid on entering the phase, whether it then succeeds or fails; Phase 2 always, "
        "Phase 3 only after passing Phase 2. Costs are not sampled; spending varies only with how far each "
        "drug gets.",
        "- So the cost of N drugs takes only N+1 values: N × Phase 2 + K × Phase 3, K = number of drugs passing "
        "Phase 2. Quantiles are attainable values (inverted CDF).",
        "- VaR95 = 95th percentile of cost (high cost is the bad tail, so VaR95 equals the 95th percentile); "
        "CVaR95 = mean cost in the worst 5% (Rockafellar–Uryasev definition, which handles the jumps of a "
        "discrete distribution).",
        "- Expected trial cost per approved drug = expected cost ÷ expected approvals = (Phase 2 + P(pass "
        "Phase 2) × Phase 3) ÷ P(approval).",
        "- **Probabilities and costs in the tables are analytic** (closed-form or exact discrete "
        "distribution); simulated values are used only for verification (section 5). Exception: approval "
        "within X years depends on durations, has no closed form, and is simulated.",
        f"- Timing settings: gap_months = {gap:g}, review_extra_months = {review_extra:g} (ASSUMPTION "
        "defaults). Cost does not depend on p_priority (same seed, same gate outcomes).",
        "",
        f"## 1. Distribution of {TITLE.lower()} (base case)",
        "",
        f"Each cell is {vs}.",
        "",
        "| N | Expected cost | Median | 95th percentile (= VaR95) | CVaR95 |",
        "|---|---|---|---|---|",
    ]
    for n_assets in PORTFOLIO_SIZES:
        r = get("base", n_assets)
        L.append(f"| {n_assets} | {pair(r, 'mean_analytic')} | {pair(r, 'median_analytic')} | "
                 f"{pair(r, 'p95_analytic')} | {pair(r, 'cvar95_analytic')} |")
    L += [
        "",
        f"## 2. Zero approvals and {TITLE.lower()} per approved drug (base case)",
        "",
        f"Each cell is {vs}.",
        "",
        "| N | P(zero approvals) | Median cost given zero approvals | 95th percentile given zero approvals "
        "| Expected cost ÷ expected approvals |",
        "|---|---|---|---|---|",
    ]
    for n_assets in PORTFOLIO_SIZES:
        r = get("base", n_assets)
        L.append(f"| {n_assets} | {pair(r, 'p_zero_approved_analytic', '{:.3f}')} | "
                 f"{pair(r, 'zero_approved_median_analytic')} | {pair(r, 'zero_approved_p95_analytic')} | "
                 f"{pair(r, 'cost_per_approval_analytic')} |")
    L += [
        "",
        "## 3. P(at least one drug approved within X years)",
        "",
        f"Each cell is {vs}. **Simulated** (time-based probabilities have no closed form). gap_months = {gap:g}; "
        "p_priority takes the ASSUMPTION_P_PRIORITY sensitivity values. The gap sensitivity is in "
        "`cost_approval_within.csv`.",
        "",
    ]
    for p_priority in p_values:
        L += [f"**p_priority = {p_priority:g}**", "",
              "| N | " + " | ".join(f"Within {y} years" for y in HORIZONS_YEARS) + " |",
              "|---|" + "---|" * len(HORIZONS_YEARS)]
        for n_assets in PORTFOLIO_SIZES:
            r = {w["scenario"]: w for w in within_rows if w["p_priority"] == p_priority
                 and w["gap_months"] == gap and w["n_assets"] == n_assets}
            L.append(f"| {n_assets} | " + " | ".join(pair(r, f"p_approved_within_{y}y", "{:.3f}")
                                                    for y in HORIZONS_YEARS) + " |")
        L.append("")
    L += [
        "## 4. Sensitivity (one factor at a time)",
        "",
        f"Each cell is {vs}. low_area / high_area are the lowest / highest therapeutic-area values in ASPE "
        "Table 1 (the Phase 2 and Phase 3 extremes come from different areas). Multipliers scale every cost "
        "measure proportionally; P(zero approvals) does not change.",
        "",
        "| Case | Phase 2 / Phase 3 cost | Multiplier | N | Expected cost | 95th percentile | CVaR95 "
        "| Expected cost ÷ expected approvals |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label, _, _ in cases:
        c = case_inputs[label]
        for n_assets in SENS_SIZES:
            r = get(label, n_assets)
            L.append(f"| {label} | {c.phase2:g} / {c.phase3:g} | {c.multiplier:g} | {n_assets} | "
                     f"{pair(r, 'mean_analytic')} | {pair(r, 'p95_analytic')} | {pair(r, 'cvar95_analytic')} | "
                     f"{pair(r, 'cost_per_approval_analytic')} |")
    metrics = [k[:-len("_analytic")] for k in cost_rows[0] if k.endswith("_analytic")]
    L += ["", "## 5. Verification: analytic vs simulated", "",
          f"Largest |analytic − simulated| over all cases, N = 1–10, BIO and Wong ({args.n_sims:,} runs per "
          "cell). Quantile measures are discrete, so simulated and analytic values are usually identical; but "
          "when the exact CDF lies right at the quantile level, simulation error (about ±0.001) picks the "
          "neighbouring value, a difference of one Phase 3 cost. This happens for the median cost given zero "
          "approvals (conditional CDF 0.4994 for Wong N = 7 and 0.5002 for BIO N = 10), which is why the "
          "report uses analytic values.", "",
          "| Measure | Largest absolute difference |", "|---|---|"]
    for m in metrics:
        L.append(f"| {m} | {max(abs(r[f'{m}_analytic'] - r[f'{m}_sim']) for r in cost_rows):.4f} |")
    L += ["", "Full values for N = 1–10 are in `data/processed/cost_results.csv` and "
          "`data/processed/cost_approval_within.csv`.", ""]
    MD_OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
