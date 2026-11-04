"""Clinical trial direct cost (臨床試驗直接花費) and risk report for N = 1..10 assets, BIO vs Wong.

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

TITLE = "臨床試驗直接花費"
UNIT = "百萬美元(名目,2004–2012 混合年份)"


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
            for gap in gap_values:
                for p_priority in p_values:
                    # same seed as run_timed.py; gate outcomes depend on neither p_priority nor gap
                    rng = np.random.default_rng([DEFAULT_SEED, n_assets, i])
                    assets = simulate_portfolio_assets(gates.names, gates.probs, n_assets, args.n_sims, timing,
                                                       p_priority, rng, gap_months=gap,
                                                       review_extra_months=review_extra)
                    port = summarize_portfolio(assets)
                    t = np.nan_to_num(port.first_approval_months, nan=np.inf)
                    # time-based probabilities have no closed form: simulation only
                    within_rows.append({"p_priority": p_priority, "gap_months": gap, "n_assets": n_assets,
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
        f"# {TITLE}:BIO 與 Wong 並排",
        "",
        "由 `scripts/run_costs.py` 產生,請勿手動編輯。",
        "",
        f"- 執行時間(UTC):{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- 每格模擬 {args.n_sims:,} 次;種子 {DEFAULT_SEED}(每格 [seed, N, 情境索引],與 run_timed.py 相同);"
        f"numpy {np.__version__}",
        f"- 單位:**{UNIT}**。只計二期、三期的{TITLE};送件與審查不計費用。",
        f"- 基準情境的階段成本(SOURCED,ASPE 2014 Table 2 加權平均,每個試驗):"
        f"二期 {base.phase2:g}、三期 {base.phase3:g}。",
        f"- 乘數(ASSUMPTION 預設值):trials_per_phase = {base.trials_per_phase:g}、"
        f"overhead_multiplier = {base.overhead_multiplier:g}、cpi_factor = {base.cpi_factor:g}。",
        "- 發生規則:進入一個階段就付該階段的成本(不論成功或失敗);二期必付,三期只在通過二期後才付。"
        "成本不做隨機抽樣,花費的變異只來自「每個藥物走到哪一關」。",
        "- 因此 N 個藥物的花費只有 N+1 種可能值:N × 二期 + K × 三期,K = 通過二期的藥物數。"
        "分位數取實際可達的值(inverted CDF)。",
        f"- VaR95 = 花費的 95 分位(「壞」的一端是花費高,所以 VaR95 與 95 分位相同);"
        "CVaR95 = 最差 5% 情境的平均花費(Rockafellar–Uryasev 定義,處理離散分佈的跳點)。",
        "- 每個核准藥物的預期試驗花費 = 預期花費 ÷ 預期核准數 = (二期 + 通過二期機率 × 三期)÷ 核准機率。",
        "- **表中的機率與花費一律為解析值**(封閉公式或精確離散分佈);模擬值只用於驗證(第 5 節)。"
        "例外:「X 年內核准」與時程有關,沒有封閉解,為模擬值。",
        f"- 時程設定:gap_months = {gap:g}、review_extra_months = {review_extra:g}(ASSUMPTION 預設值)。"
        "花費與 p_priority 無關(同一種子下,關卡結果相同)。",
        "",
        f"## 1. {TITLE}的分佈(基準情境)",
        "",
        f"每格為 {vs}。",
        "",
        "| N | 預期花費 | 中位數 | 95 分位(= VaR95) | CVaR95 |",
        "|---|---|---|---|---|",
    ]
    for n_assets in PORTFOLIO_SIZES:
        r = get("base", n_assets)
        L.append(f"| {n_assets} | {pair(r, 'mean_analytic')} | {pair(r, 'median_analytic')} | "
                 f"{pair(r, 'p95_analytic')} | {pair(r, 'cvar95_analytic')} |")
    L += [
        "",
        f"## 2. 零核准與每個核准藥物的{TITLE}(基準情境)",
        "",
        f"每格為 {vs}。",
        "",
        "| N | P(零核准) | 零核准時花費中位數 | 零核准時花費 95 分位 | 預期花費 ÷ 預期核准數 |",
        "|---|---|---|---|---|",
    ]
    for n_assets in PORTFOLIO_SIZES:
        r = get("base", n_assets)
        L.append(f"| {n_assets} | {pair(r, 'p_zero_approved_analytic', '{:.3f}')} | "
                 f"{pair(r, 'zero_approved_median_analytic')} | {pair(r, 'zero_approved_p95_analytic')} | "
                 f"{pair(r, 'cost_per_approval_analytic')} |")
    L += [
        "",
        "## 3. P(至少一個藥物在 X 年內核准)",
        "",
        f"每格為 {vs}。**模擬值**(與時間有關的機率沒有封閉解)。gap_months = {gap:g};"
        "p_priority 取 ASSUMPTION_P_PRIORITY 的敏感度值。gap 敏感度見 `cost_approval_within.csv`。",
        "",
    ]
    for p_priority in p_values:
        L += [f"**p_priority = {p_priority:g}**", "",
              "| N | " + " | ".join(f"{y} 年內" for y in HORIZONS_YEARS) + " |",
              "|---|" + "---|" * len(HORIZONS_YEARS)]
        for n_assets in PORTFOLIO_SIZES:
            r = {w["scenario"]: w for w in within_rows if w["p_priority"] == p_priority
                 and w["gap_months"] == gap and w["n_assets"] == n_assets}
            L.append(f"| {n_assets} | " + " | ".join(pair(r, f"p_approved_within_{y}y", "{:.3f}")
                                                    for y in HORIZONS_YEARS) + " |")
        L.append("")
    L += [
        f"## 4. 敏感度(一次改一項)",
        "",
        f"每格為 {vs}。low_area / high_area 為 ASPE Table 1 治療領域的最小 / 最大值"
        "(二期與三期的極值來自不同領域)。乘數只會等比例放大所有花費指標,P(零核准)不變。",
        "",
        "| 情境 | 二期 / 三期成本 | 乘數 | N | 預期花費 | 95 分位 | CVaR95 | 預期花費 ÷ 預期核准數 |",
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
    L += ["", "## 5. 驗證:解析值 vs 模擬值", "",
          f"所有情境、N = 1–10、BIO 與 Wong 中,|解析值 − 模擬值| 的最大值(模擬每格 {args.n_sims:,} 次)。"
          "分位數類指標是離散值,模擬與解析值通常完全相同;但若精確 CDF 剛好落在分位水準附近,"
          "模擬誤差(約 ±0.001)就會取到相鄰的離散值,差距等於一個三期成本。"
          "零核准時的中位數即是如此(Wong N = 7 的條件 CDF 為 0.4994,BIO N = 10 為 0.5002),"
          "所以報告採用解析值。", "",
          "| 指標 | 最大絕對差 |", "|---|---|"]
    for m in metrics:
        L.append(f"| {m} | {max(abs(r[f'{m}_analytic'] - r[f'{m}_sim']) for r in cost_rows):.4f} |")
    L += ["", "N = 1–10 的完整數值見 `data/processed/cost_results.csv` 與 `data/processed/cost_approval_within.csv`。", ""]
    MD_OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
