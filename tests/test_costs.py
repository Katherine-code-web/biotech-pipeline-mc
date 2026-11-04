import ast
import csv
import shutil
from math import comb
from pathlib import Path

import numpy as np
import pytest

import biotech_pipeline_mc.costs as costs_module
from biotech_pipeline_mc.costs import (
    analytic_cost_distribution,
    analytic_expected_asset_cost,
    discrete_quantile,
    discrete_var_cvar,
    asset_costs,
    gate_costs,
    load_cost_inputs,
    var_cvar,
)
from biotech_pipeline_mc.gates import DEFAULT_SEED, simulate_asset
from biotech_pipeline_mc.params import (
    ASSUMPTIONS_CSV,
    SCENARIOS,
    load_gate_probs,
    load_sensitivity_values,
    load_value,
)
from biotech_pipeline_mc.timing import load_timing_inputs, simulate_portfolio_assets


def rng(offset=0):
    return np.random.default_rng(DEFAULT_SEED + offset)


def _copy_csv_with(tmp_path, param_id, **changes):
    path = tmp_path / "assumptions.csv"
    shutil.copy(ASSUMPTIONS_CSV, path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = reader.fieldnames, list(reader)
    for r in rows:
        if r["param_id"] == param_id:
            r.update(changes)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path


# --- expected cost per asset = Phase 2 cost + P(pass Phase 2) x Phase 3 cost ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_mean_asset_cost_matches_analytic(scenario):
    gates = load_gate_probs(scenario)
    costs = load_cost_inputs()
    gc = gate_costs(gates.names, costs)
    n = 1_000_000
    cost = asset_costs(simulate_asset(gates.probs, n, rng()).stopped_at, gc)
    expected = costs.phase2 + gates.probs[0] * costs.phase3
    assert analytic_expected_asset_cost(gates.probs, gc) == pytest.approx(expected)
    se = cost.std(ddof=1) / np.sqrt(n)
    assert abs(cost.mean() - expected) <= 3 * se


# --- bounds: N x Phase 2 <= total <= N x (Phase 2 + Phase 3) ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("n_assets", [1, 3, 10])
def test_portfolio_cost_bounds(scenario, n_assets):
    gates = load_gate_probs(scenario)
    costs = load_cost_inputs()
    assets = simulate_portfolio_assets(gates.names, gates.probs, n_assets, 50_000, load_timing_inputs(), 0.5, rng())
    total = asset_costs(assets.stopped_at, gate_costs(gates.names, costs)).sum(axis=1)
    assert (total >= n_assets * costs.phase2 - 1e-9).all()
    assert (total <= n_assets * (costs.phase2 + costs.phase3) + 1e-9).all()
    if n_assets == 1:  # both bounds are reached (for large N, all passing Phase 2 is too rare to observe)
        assert np.isclose(total.min(), costs.phase2)
        assert np.isclose(total.max(), costs.phase2 + costs.phase3)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("n_assets", [1, 3, 10])
def test_zero_approval_cost_at_least_n_phase2(scenario, n_assets):
    gates = load_gate_probs(scenario)
    costs = load_cost_inputs()
    assets = simulate_portfolio_assets(gates.names, gates.probs, n_assets, 50_000, load_timing_inputs(), 0.5, rng())
    total = asset_costs(assets.stopped_at, gate_costs(gates.names, costs)).sum(axis=1)
    zero = ~assets.approved.any(axis=1)
    assert zero.sum() > 0
    assert (total[zero] >= n_assets * costs.phase2 - 1e-9).all()


# --- which costs are paid ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_cost_by_stopping_gate(scenario):
    names = load_gate_probs(scenario).names
    costs = load_cost_inputs()
    gc = gate_costs(names, costs)
    k = len(names)
    stopped = np.arange(k + 1)  # failed at each gate, then approved
    got = asset_costs(stopped, gc)
    assert got[0] == pytest.approx(costs.phase2)  # Phase 2 failure: Phase 2 only
    assert np.allclose(got[1:], costs.phase2 + costs.phase3)  # later failures and approvals: no review cost


def test_multipliers_scale_total():
    base = load_cost_inputs()
    scaled = load_cost_inputs(trials_per_phase=2, overhead_multiplier=1.5, cpi_factor=1.2)
    names = load_gate_probs("BIO").names
    assert np.allclose(gate_costs(names, scaled), 2 * 1.5 * 1.2 * gate_costs(names, base))


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("n_assets", [1, 5])
def test_portfolio_cost_distribution_is_binomial(scenario, n_assets):
    # each asset pays Phase 3 iff it passes Phase 2, so total = N*c2 + K*c3 with K ~ Binomial(N, p_P2)
    gates = load_gate_probs(scenario)
    costs = load_cost_inputs()
    n = 200_000
    assets = simulate_portfolio_assets(gates.names, gates.probs, n_assets, n, load_timing_inputs(), 0.5, rng())
    total = asset_costs(assets.stopped_at, gate_costs(gates.names, costs)).sum(axis=1)
    k = np.rint((total - n_assets * costs.phase2) / costs.phase3).astype(int)
    p = gates.probs[0]
    for j in range(n_assets + 1):
        q = comb(n_assets, j) * p**j * (1 - p) ** (n_assets - j)
        assert abs((k == j).mean() - q) <= 3 * np.sqrt(q * (1 - q) / n) + 1e-12


# --- values come from assumptions.csv ---

def test_cost_inputs_read_from_assumptions():
    c = load_cost_inputs()
    assert (c.phase2, c.phase3) == (load_value("ASPE14_COST_P2_MEAN", "value_usd_m", ("SOURCED",)),
                                    load_value("ASPE14_COST_P3_MEAN", "value_usd_m", ("SOURCED",)))
    assert c.trials_per_phase == load_value("ASSUMPTION_TRIALS_PER_PHASE", "value", ("ASSUMPTION",))
    assert load_sensitivity_values("ASSUMPTION_TRIALS_PER_PHASE") == (1.0, 2.0)
    assert load_sensitivity_values("ASSUMPTION_OVERHEAD_MULTIPLIER") == (1.5, 2.0)
    low, high = load_cost_inputs("low_area"), load_cost_inputs("high_area")
    assert low.phase2 < c.phase2 < high.phase2 and low.phase3 < c.phase3 < high.phase3


def test_changed_csv_value_is_used(tmp_path):
    path = _copy_csv_with(tmp_path, "ASPE14_COST_P3_MEAN", value_usd_m="99.0")
    assert load_cost_inputs(path=path).phase3 == 99.0


@pytest.mark.parametrize("pid, changes", [
    ("ASPE14_COST_P2_MEAN", {"status": "CANDIDATE"}),
    ("ASSUMPTION_CPI_FACTOR", {"value": ""}),
    ("ASSUMPTION_OVERHEAD_MULTIPLIER", {"value": "-1"}),
])
def test_bad_cost_rows_rejected(tmp_path, pid, changes):
    with pytest.raises(ValueError):
        load_cost_inputs(path=_copy_csv_with(tmp_path, pid, **changes))


def test_costs_module_has_no_numeric_inputs():
    # every model number comes from assumptions.csv; only 0 and 1 may appear as structural constants
    tree = ast.parse(Path(costs_module.__file__).read_text(encoding="utf-8"))
    nums = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
    assert nums <= {0, 1}


# --- exact cost distribution ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("n_assets", [1, 5, 10])
def test_analytic_distribution_matches_closed_forms(scenario, n_assets):
    gates = load_gate_probs(scenario)
    costs = load_cost_inputs()
    gc = gate_costs(gates.names, costs)
    totals, prob, zero = analytic_cost_distribution(gates.probs, gc, n_assets)
    p_app = float(np.prod(gates.probs))
    assert prob.sum() == pytest.approx(1.0)
    assert zero.sum() == pytest.approx((1 - p_app) ** n_assets)
    assert totals @ prob == pytest.approx(n_assets * analytic_expected_asset_cost(gates.probs, gc))
    p2 = gates.probs[0]
    expected = [comb(n_assets, j) * p2**j * (1 - p2) ** (n_assets - j) for j in range(n_assets + 1)]
    assert np.allclose(totals, n_assets * costs.phase2 + np.arange(n_assets + 1) * costs.phase3)
    assert np.allclose(prob, expected)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_analytic_distribution_matches_simulation(scenario):
    gates = load_gate_probs(scenario)
    gc = gate_costs(gates.names, load_cost_inputs())
    n, n_assets = 200_000, 5
    assets = simulate_portfolio_assets(gates.names, gates.probs, n_assets, n, load_timing_inputs(), 0.5, rng())
    total = asset_costs(assets.stopped_at, gc).sum(axis=1)
    zero_sim = ~assets.approved.any(axis=1)
    totals, prob, zero = analytic_cost_distribution(gates.probs, gc, n_assets)
    for t, q, z in zip(totals, prob, zero):
        at = np.isclose(total, t)
        for sim, exact in ((at.mean(), q), ((at & zero_sim).mean(), z)):
            assert abs(sim - exact) <= 3 * np.sqrt(exact * (1 - exact) / n) + 1e-12


def test_discrete_var_cvar_matches_sample_version():
    values, probs = np.array([1.0, 2.0, 5.0, 9.0]), np.array([0.5, 0.3, 0.17, 0.03])
    sample = np.repeat(values, (probs * 100).astype(int))
    assert discrete_var_cvar(values, probs, 0.95) == pytest.approx(var_cvar(sample, 0.95))
    assert discrete_quantile(values, probs, 0.5) == 1.0
    assert discrete_quantile(values, probs, 0.8) == 2.0


# --- VaR / CVaR ---

def test_var_cvar_known_values():
    var, cvar = var_cvar(np.arange(100), 0.95)
    assert (var, cvar) == (94.0, pytest.approx(97.0))  # mean of the worst 5: 95..99
    var, cvar = var_cvar(np.array([0.0] * 90 + [10.0] * 10), 0.95)  # atom at the tail
    assert (var, cvar) == (10.0, pytest.approx(10.0))


# --- reproducibility ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_outcomes_and_cost_do_not_depend_on_p_priority(scenario):
    gates = load_gate_probs(scenario)
    timing = load_timing_inputs()
    a = simulate_portfolio_assets(gates.names, gates.probs, 5, 20_000, timing, 0.0, rng())
    b = simulate_portfolio_assets(gates.names, gates.probs, 5, 20_000, timing, 1.0, rng())
    assert np.array_equal(a.stopped_at, b.stopped_at)


def test_same_seed_same_cost():
    gates = load_gate_probs("BIO")
    gc = gate_costs(gates.names, load_cost_inputs())
    runs = [asset_costs(simulate_portfolio_assets(gates.names, gates.probs, 5, 20_000, load_timing_inputs(), 0.5,
                                                  rng()).stopped_at, gc).sum(axis=1) for _ in range(2)]
    assert np.array_equal(*runs)
