"""Stage 2 of the model: gates plus durations (no costs).

Each gate has a duration; an asset's clock runs to the end of the gate where it stops
(the last gate if approved). Gate durations by gate name:
  P2_P3   Phase 2 trial duration (resampled)
  P3_NDA  gap + Phase 3 trial duration (resampled)                         -- BIO
  NDA_APP gap + review time + review_extra                                 -- BIO
  P3_APP  gap + Phase 3 duration + gap + review time + review_extra        -- Wong
review time = priority months w.p. p_priority, else standard months.
gap = gap_months (ASSUMPTION_GAP_MONTHS), review_extra = review_extra_months
(ASSUMPTION_REVIEW_EXTRA_MONTHS); both default 0. No resubmission cycles.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Sequence

import numpy as np

from .gates import simulate_asset
from .params import ASSUMPTIONS_CSV, DURATIONS_MAIN_CSV, load_duration_vectors, load_review_months


@dataclass(frozen=True)
class TimingInputs:
    phase2: np.ndarray  # resampling vector, months
    phase3: np.ndarray
    review_priority: float  # months
    review_standard: float


def load_timing_inputs(durations_path: Path = DURATIONS_MAIN_CSV,
                       assumptions_path: Path = ASSUMPTIONS_CSV) -> TimingInputs:
    vectors = load_duration_vectors(durations_path)
    priority, standard = load_review_months(assumptions_path)
    return TimingInputs(vectors["PHASE2"], vectors["PHASE3"], priority, standard)


class TimedAssetSim(NamedTuple):
    stopped_at: np.ndarray  # index of the failed gate, or n_gates if approved
    approved: np.ndarray  # bool
    time_months: np.ndarray  # cumulative time to the end of the stopping gate


class PortfolioSim(NamedTuple):
    n_approved: np.ndarray  # (n,) number of approved assets per run
    first_approval_months: np.ndarray  # (n,) time of the first approval; NaN if none approved


def sample_review(n: int, p_priority: float, timing: TimingInputs, rng: np.random.Generator) -> np.ndarray:
    if not 0 <= p_priority <= 1:
        raise ValueError(f"p_priority must be in [0, 1]: {p_priority}")
    priority = rng.random(n) < p_priority
    return np.where(priority, timing.review_priority, timing.review_standard)


def sample_gate_durations(gate_names: Sequence[str], n: int, timing: TimingInputs, p_priority: float,
                          rng: np.random.Generator, gap_months: float = 0.0,
                          review_extra_months: float = 0.0) -> np.ndarray:
    """(n, n_gates) matrix of durations in months, one column per gate."""
    for name, v in (("gap_months", gap_months), ("review_extra_months", review_extra_months)):
        if not v >= 0:
            raise ValueError(f"{name} must be >= 0: {v}")
    phase2 = rng.choice(timing.phase2, size=n, replace=True)
    phase3 = gap_months + rng.choice(timing.phase3, size=n, replace=True)
    review = gap_months + review_extra_months + sample_review(n, p_priority, timing, rng)
    by_gate = {
        "P2_P3": phase2,
        "P3_NDA": phase3,
        "NDA_APP": review,
        "P3_APP": phase3 + review,
    }
    unknown = set(gate_names) - set(by_gate)
    if unknown:
        raise ValueError(f"no duration rule for gates {sorted(unknown)}")
    return np.column_stack([by_gate[g] for g in gate_names])


def simulate_asset_timed(gate_probs: Sequence[float], gate_durations: np.ndarray,
                         rng: np.random.Generator) -> TimedAssetSim:
    """Gate outcomes as in simulate_asset, plus time to the end of the stopping gate."""
    d = np.asarray(gate_durations, dtype=float)
    n, k = d.shape
    if k != len(gate_probs):
        raise ValueError(f"gate_durations has {k} columns but there are {len(gate_probs)} gates")
    sim = simulate_asset(gate_probs, n, rng)
    last_gate = np.minimum(sim.stopped_at, k - 1)  # approved assets ran through every gate
    time = np.cumsum(d, axis=1)[np.arange(n), last_gate]
    return TimedAssetSim(sim.stopped_at, sim.approved, time)


def simulate_portfolio_assets(gate_names: Sequence[str], gate_probs: Sequence[float], n_assets: int, n: int,
                              timing: TimingInputs, p_priority: float,
                              rng: np.random.Generator, gap_months: float = 0.0,
                              review_extra_months: float = 0.0) -> TimedAssetSim:
    """n runs of n_assets independent assets that all start Phase 2 at time 0; arrays shaped (n, n_assets)."""
    total = n * n_assets
    durations = sample_gate_durations(gate_names, total, timing, p_priority, rng,
                                      gap_months, review_extra_months)
    sim = simulate_asset_timed(gate_probs, durations, rng)
    return TimedAssetSim(*(a.reshape(n, n_assets) for a in sim))


def summarize_portfolio(assets: TimedAssetSim) -> PortfolioSim:
    approval_time = np.where(assets.approved, assets.time_months, np.inf)
    first = approval_time.min(axis=1)
    return PortfolioSim(assets.approved.sum(axis=1), np.where(np.isinf(first), np.nan, first))


def simulate_portfolio_timed(gate_names: Sequence[str], gate_probs: Sequence[float], n_assets: int, n: int,
                             timing: TimingInputs, p_priority: float,
                             rng: np.random.Generator, gap_months: float = 0.0,
                             review_extra_months: float = 0.0) -> PortfolioSim:
    """n runs of n_assets independent assets that all start Phase 2 at time 0."""
    return summarize_portfolio(simulate_portfolio_assets(gate_names, gate_probs, n_assets, n, timing, p_priority,
                                                         rng, gap_months, review_extra_months))
