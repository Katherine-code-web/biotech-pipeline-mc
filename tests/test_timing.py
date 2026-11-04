import inspect

import numpy as np
import pytest

from biotech_pipeline_mc.gates import DEFAULT_SEED
from biotech_pipeline_mc.params import SCENARIOS, load_assumptions, load_duration_vectors, load_gate_probs
from biotech_pipeline_mc.timing import (
    TimingInputs,
    load_timing_inputs,
    sample_gate_durations,
    sample_review,
    simulate_asset_timed,
    simulate_portfolio_timed,
)

FIXED = TimingInputs(phase2=np.array([10.0]), phase3=np.array([20.0]), review_priority=8.0, review_standard=12.0)


def rng(offset=0):
    return np.random.default_rng(DEFAULT_SEED + offset)


# --- fixed durations: approved total = sum of gate durations ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("p_priority, review", [(0.0, 12.0), (1.0, 8.0)])
def test_fixed_durations_approved_time_is_sum_of_gates(scenario, p_priority, review):
    names = load_gate_probs(scenario).names
    d = sample_gate_durations(names, 1_000, FIXED, p_priority, rng())
    sim = simulate_asset_timed([1.0] * len(names), d, rng())
    assert sim.approved.all()
    # Phase 2 + Phase 3 + review, whether review is its own gate (BIO) or inside P3_APP (Wong)
    assert np.allclose(sim.time_months, 10.0 + 20.0 + review)


def test_fixed_matrix_time_is_cumulative_sum_to_stopping_gate():
    d = np.tile([10.0, 20.0, 12.0], (6, 1))
    probs = [1.0, 1.0, 1.0]
    assert np.allclose(simulate_asset_timed(probs, d, rng()).time_months, 42.0)
    for gate, expected in [(0, 10.0), (1, 30.0), (2, 42.0)]:
        probs = [1.0] * 3
        probs[gate] = 0.0
        sim = simulate_asset_timed(probs, d, rng())
        assert (sim.stopped_at == gate).all() and not sim.approved.any()
        assert np.allclose(sim.time_months, expected)


# --- failure in Phase 2 counts Phase 2 time only ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_phase2_failure_time_is_phase2_duration_only(scenario):
    gates = load_gate_probs(scenario)
    timing = load_timing_inputs()
    d = sample_gate_durations(gates.names, 100_000, timing, 0.5, rng())
    sim = simulate_asset_timed(gates.probs, d, rng(1))
    failed_p2 = sim.stopped_at == 0
    assert failed_p2.sum() > 0
    assert np.array_equal(sim.time_months[failed_p2], d[failed_p2, 0])
    # and Phase 2 durations come from the Phase 2 vector
    assert np.isin(d[:, 0], timing.phase2).all()


# --- resampled medians match the input data ---

@pytest.mark.parametrize("phase", ["PHASE2", "PHASE3"])
def test_resampled_median_matches_input_median(phase):
    vectors = load_duration_vectors()
    timing = load_timing_inputs()
    d = sample_gate_durations(("P2_P3", "P3_NDA", "NDA_APP"), 200_000, timing, 0.5, rng())
    col = {"PHASE2": 0, "PHASE3": 1}[phase]
    assert abs(np.median(d[:, col]) - np.median(vectors[phase])) < 0.25  # months


# --- p_priority: a parameter, not a constant ---

def test_p_priority_has_no_default():
    for fn in (sample_review, sample_gate_durations, simulate_portfolio_timed):
        assert inspect.signature(fn).parameters["p_priority"].default is inspect.Parameter.empty


@pytest.mark.parametrize("p", [0.0, 0.3, 1.0])
def test_review_priority_share_matches_p_priority(p):
    n = 200_000
    review = sample_review(n, p, FIXED, rng())
    share = (review == FIXED.review_priority).mean()
    assert set(np.unique(review)) <= {8.0, 12.0}
    assert abs(share - p) <= 3 * np.sqrt(p * (1 - p) / n) + 1e-12


def test_invalid_p_priority_rejected():
    with pytest.raises(ValueError):
        sample_review(10, 1.5, FIXED, rng())


def test_review_months_read_from_assumptions():
    timing = load_timing_inputs()
    assert (timing.review_priority, timing.review_standard) == (8.0, 12.0)


# --- gap_months / review_extra_months ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("gap, extra", [(0.0, 0.0), (3.0, 0.0), (6.0, 2.0)])
def test_gap_and_review_extra_added_to_approved_time(scenario, gap, extra):
    names = load_gate_probs(scenario).names
    d = sample_gate_durations(names, 1_000, FIXED, 0.0, rng(), gap_months=gap, review_extra_months=extra)
    sim = simulate_asset_timed([1.0] * len(names), d, rng())
    # two gaps on the path (Phase 2 -> 3, Phase 3 -> submission) in both scenarios
    assert np.allclose(sim.time_months, 10.0 + 20.0 + 12.0 + 2 * gap + extra)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_gap_does_not_change_phase2_failure_time(scenario):
    names = load_gate_probs(scenario).names
    d = sample_gate_durations(names, 100, FIXED, 0.0, rng(), gap_months=6.0, review_extra_months=2.0)
    probs = [0.0] + [1.0] * (len(names) - 1)
    assert np.allclose(simulate_asset_timed(probs, d, rng()).time_months, 10.0)


def test_bio_phase3_failure_includes_one_gap():
    d = sample_gate_durations(("P2_P3", "P3_NDA", "NDA_APP"), 100, FIXED, 0.0, rng(), gap_months=3.0)
    assert np.allclose(simulate_asset_timed([1.0, 0.0, 1.0], d, rng()).time_months, 10.0 + 3.0 + 20.0)


def test_zero_gap_matches_default_draws():
    names = load_gate_probs("BIO").names
    timing = load_timing_inputs()
    a = sample_gate_durations(names, 1_000, timing, 0.5, rng())
    b = sample_gate_durations(names, 1_000, timing, 0.5, rng(), gap_months=0.0, review_extra_months=0.0)
    assert np.array_equal(a, b)


def test_gap_defaults_match_assumptions_csv():
    rows = load_assumptions()
    for fn in (sample_gate_durations, simulate_portfolio_timed):
        params = inspect.signature(fn).parameters
        for arg, pid in (("gap_months", "ASSUMPTION_GAP_MONTHS"),
                         ("review_extra_months", "ASSUMPTION_REVIEW_EXTRA_MONTHS")):
            assert rows[pid]["status"] == "ASSUMPTION"
            assert params[arg].default == float(rows[pid]["value_months"])


@pytest.mark.parametrize("kw", [{"gap_months": -1.0}, {"review_extra_months": -0.5}, {"gap_months": float("nan")}])
def test_negative_gap_or_extra_rejected(kw):
    with pytest.raises(ValueError):
        sample_gate_durations(("P2_P3",), 10, FIXED, 0.5, rng(), **kw)


# --- reproducibility ---

@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_same_seed_gives_identical_portfolio(scenario):
    gates = load_gate_probs(scenario)
    timing = load_timing_inputs()
    a = simulate_portfolio_timed(gates.names, gates.probs, 5, 20_000, timing, 0.5, rng())
    b = simulate_portfolio_timed(gates.names, gates.probs, 5, 20_000, timing, 0.5, rng())
    assert np.array_equal(a.n_approved, b.n_approved)
    assert np.array_equal(a.first_approval_months, b.first_approval_months, equal_nan=True)


# --- portfolio bookkeeping ---

def test_first_approval_is_nan_iff_zero_approved():
    gates = load_gate_probs("BIO")
    res = simulate_portfolio_timed(gates.names, gates.probs, 3, 50_000, load_timing_inputs(), 0.5, rng())
    assert np.array_equal(np.isnan(res.first_approval_months), res.n_approved == 0)


def test_first_approval_equals_min_over_approved_assets():
    names = ("P2_P3", "P3_NDA", "NDA_APP")
    timing = TimingInputs(np.array([5.0, 30.0]), np.array([10.0, 40.0]), 8.0, 12.0)
    res = simulate_portfolio_timed(names, [1.0, 1.0, 1.0], 10, 1_000, timing, 1.0, rng())
    # with 10 always-approved assets, the first approval is almost surely the shortest path 5+10+8
    assert (res.n_approved == 10).all()
    assert np.allclose(res.first_approval_months.min(), 23.0)
    assert (res.first_approval_months >= 23.0).all() and (res.first_approval_months <= 78.0).all()
