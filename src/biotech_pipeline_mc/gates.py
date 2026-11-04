"""Single-asset gate model: one Bernoulli draw per gate, stop at the first failure.

Stage 1 of the model: gates only (no durations, no costs).
"""
from __future__ import annotations

from typing import NamedTuple, Sequence

import numpy as np

DEFAULT_SEED = 20261028


class AssetSim(NamedTuple):
    stopped_at: np.ndarray  # int, shape (n,): index of the failed gate, or len(gate_probs) if approved
    approved: np.ndarray  # bool, shape (n,)


def _check_probs(gate_probs: Sequence[float]) -> np.ndarray:
    p = np.asarray(gate_probs, dtype=float)
    if p.ndim != 1 or p.size == 0:
        raise ValueError("gate_probs must be a non-empty 1-D sequence")
    if np.any((p < 0) | (p > 1)) or np.any(np.isnan(p)):
        raise ValueError(f"gate probabilities must be in [0, 1]: {p}")
    return p


def simulate_asset(gate_probs: Sequence[float], n: int, rng: np.random.Generator) -> AssetSim:
    """Simulate n independent runs of one asset through its gates.

    Each run draws one uniform per gate; gate i is passed if u < p_i. The run stops at the
    first failed gate. All gates are drawn up front (vectorised), so the random stream used
    does not depend on outcomes.
    """
    p = _check_probs(gate_probs)
    if n < 0:
        raise ValueError("n must be >= 0")
    passed = rng.random((n, p.size)) < p
    approved = passed.all(axis=1)
    # argmin finds the first False (failed gate); approved runs get len(p)
    stopped_at = np.where(approved, p.size, np.argmin(passed, axis=1))
    return AssetSim(stopped_at, approved)


def simulate_portfolio(gate_probs: Sequence[float], n_assets: int, n: int, rng: np.random.Generator) -> np.ndarray:
    """Number of approved assets in each of n runs, for n_assets independent assets."""
    sim = simulate_asset(gate_probs, n * n_assets, rng)
    return sim.approved.reshape(n, n_assets).sum(axis=1)


def analytic_approval(gate_probs: Sequence[float]) -> float:
    return float(np.prod(_check_probs(gate_probs)))


def analytic_stop_distribution(gate_probs: Sequence[float]) -> np.ndarray:
    """P(stop at gate i) for each gate, then P(approved) as the last element."""
    p = _check_probs(gate_probs)
    reach = np.concatenate([[1.0], np.cumprod(p)])  # P(reach gate i)
    return np.concatenate([reach[:-1] * (1 - p), reach[-1:]])


def analytic_at_least_one(gate_probs: Sequence[float], n_assets: int) -> float:
    return 1 - (1 - analytic_approval(gate_probs)) ** n_assets
