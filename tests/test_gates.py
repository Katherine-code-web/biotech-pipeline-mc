import csv
import shutil

import numpy as np
import pytest

from biotech_pipeline_mc.gates import (
    DEFAULT_SEED,
    analytic_approval,
    analytic_at_least_one,
    analytic_stop_distribution,
    simulate_asset,
    simulate_portfolio,
)
from biotech_pipeline_mc.params import ASSUMPTIONS_CSV, SCENARIOS, load_gate_probs

N_SIMS = 1_000_000
N_PORTFOLIO_SIMS = 200_000


def se(p: float, n: int) -> float:
    return np.sqrt(p * (1 - p) / n)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_approval_rate_matches_product_within_3se(scenario):
    gates = load_gate_probs(scenario)
    rng = np.random.default_rng(DEFAULT_SEED)
    sim = simulate_asset(gates.probs, N_SIMS, rng)
    p = analytic_approval(gates.probs)
    assert abs(sim.approved.mean() - p) < 3 * se(p, N_SIMS)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_stop_distribution_matches_analytic_within_3se(scenario):
    gates = load_gate_probs(scenario)
    sim = simulate_asset(gates.probs, N_SIMS, np.random.default_rng(DEFAULT_SEED))
    counts = np.bincount(sim.stopped_at, minlength=len(gates.probs) + 1) / N_SIMS
    for observed, expected in zip(counts, analytic_stop_distribution(gates.probs)):
        assert abs(observed - expected) < 3 * se(expected, N_SIMS)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("n_assets", [1, 3, 5, 10])
def test_at_least_one_approval_matches_formula(scenario, n_assets):
    gates = load_gate_probs(scenario)
    rng = np.random.default_rng(DEFAULT_SEED + n_assets)
    approved = simulate_portfolio(gates.probs, n_assets, N_PORTFOLIO_SIMS, rng)
    p = analytic_at_least_one(gates.probs, n_assets)
    assert abs((approved > 0).mean() - p) < 3 * se(p, N_PORTFOLIO_SIMS)


@pytest.mark.parametrize("probs", [[0.0], [0.0, 1.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0], [0.5, 0.0]])
def test_zero_probability_gate_never_approves(probs):
    sim = simulate_asset(probs, 10_000, np.random.default_rng(DEFAULT_SEED))
    assert not sim.approved.any()
    first_zero = probs.index(0.0)
    assert (sim.stopped_at <= first_zero).all()


@pytest.mark.parametrize("probs", [[1.0], [1.0, 1.0], [1.0, 1.0, 1.0]])
def test_all_gates_probability_one_always_approves(probs):
    sim = simulate_asset(probs, 10_000, np.random.default_rng(DEFAULT_SEED))
    assert sim.approved.all()
    assert (sim.stopped_at == len(probs)).all()


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_same_seed_gives_identical_results(scenario):
    gates = load_gate_probs(scenario)
    a = simulate_asset(gates.probs, 100_000, np.random.default_rng(DEFAULT_SEED))
    b = simulate_asset(gates.probs, 100_000, np.random.default_rng(DEFAULT_SEED))
    assert np.array_equal(a.stopped_at, b.stopped_at)
    assert np.array_equal(a.approved, b.approved)
    c = simulate_asset(gates.probs, 100_000, np.random.default_rng(DEFAULT_SEED + 1))
    assert not np.array_equal(a.stopped_at, c.stopped_at)


def test_invalid_probabilities_rejected():
    rng = np.random.default_rng(DEFAULT_SEED)
    for bad in ([1.1], [-0.1], [], [float("nan")]):
        with pytest.raises(ValueError):
            simulate_asset(bad, 10, rng)


# --- parameters come from assumptions.csv, by name ---

def test_gate_probs_read_from_csv_by_param_id():
    with ASSUMPTIONS_CSV.open(newline="", encoding="utf-8") as f:
        rows = {r["param_id"]: r for r in csv.DictReader(f)}
    for scenario, gates in SCENARIOS.items():
        loaded = load_gate_probs(scenario)
        assert loaded.param_ids == tuple(pid for _, pid in gates)
        assert loaded.probs == tuple(float(rows[pid]["value_pct"]) / 100 for _, pid in gates)
    assert len(load_gate_probs("BIO").probs) == 3
    assert len(load_gate_probs("Wong").probs) == 2


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


def test_changing_csv_value_changes_loaded_probability(tmp_path):
    path = _copy_csv_with(tmp_path, "BIO21_POS_P2_P3_ALL_INDICATIONS", value_pct="50.0")
    assert load_gate_probs("BIO", path).probs[0] == 0.5


def test_non_sourced_row_is_rejected(tmp_path):
    path = _copy_csv_with(tmp_path, "WONG19_ALL_P2_P3_OVERALL", status="DO_NOT_USE")
    with pytest.raises(ValueError, match="DO_NOT_USE"):
        load_gate_probs("Wong", path)
