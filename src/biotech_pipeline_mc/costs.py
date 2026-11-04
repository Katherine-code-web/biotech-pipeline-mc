"""Stage 3 of the model: clinical trial direct cost (臨床試驗直接花費), fixed per phase (not sampled).

A phase's cost is paid on entering the phase, whether it then succeeds or fails: Phase 2 always,
Phase 3 only after passing Phase 2. Submission/review is not charged (ASSUMPTION_SUBMISSION_COST_EXCLUDED).
Asset cost = trials_per_phase x overhead_multiplier x cpi_factor x sum of the phase costs it entered.
All values are read from data/assumptions.csv by param_id; units are USD million (ASPE nominal, 2004-2012).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

import numpy as np

from .params import ASSUMPTIONS_CSV, load_value

# Phase cost rows per cost case: Table 2 means (base) or Table 1 therapeutic-area extremes (sensitivity).
PHASE_COST_IDS: dict[str, dict[str, str]] = {
    "base": {"PHASE2": "ASPE14_COST_P2_MEAN", "PHASE3": "ASPE14_COST_P3_MEAN"},
    "low_area": {"PHASE2": "ASPE14_COST_P2_MIN_AREA", "PHASE3": "ASPE14_COST_P3_MIN_AREA"},
    "high_area": {"PHASE2": "ASPE14_COST_P2_MAX_AREA", "PHASE3": "ASPE14_COST_P3_MAX_AREA"},
}
MULTIPLIER_IDS = {
    "trials_per_phase": "ASSUMPTION_TRIALS_PER_PHASE",
    "overhead_multiplier": "ASSUMPTION_OVERHEAD_MULTIPLIER",
    "cpi_factor": "ASSUMPTION_CPI_FACTOR",
}
# Which phase's cost is paid on entering each gate (None = not charged).
GATE_COST_PHASE = {"P2_P3": "PHASE2", "P3_NDA": "PHASE3", "P3_APP": "PHASE3", "NDA_APP": None}


@dataclass(frozen=True)
class CostInputs:
    phase2: float  # USD million per trial
    phase3: float
    trials_per_phase: float
    overhead_multiplier: float
    cpi_factor: float

    @property
    def multiplier(self) -> float:
        return self.trials_per_phase * self.overhead_multiplier * self.cpi_factor


def load_cost_inputs(cost_case: str = "base", path: Path = ASSUMPTIONS_CSV, **overrides: float) -> CostInputs:
    """Phase costs (SOURCED rows only) and multipliers (ASSUMPTION defaults), read by param_id.

    overrides replace multipliers by name, e.g. trials_per_phase=2 for a sensitivity run.
    """
    ids = PHASE_COST_IDS[cost_case]
    phase = {ph: load_value(pid, "value_usd_m", ("SOURCED",), path) for ph, pid in ids.items()}
    mult = {name: load_value(pid, "value", ("ASSUMPTION", "DECIDED"), path) for name, pid in MULTIPLIER_IDS.items()}
    unknown = set(overrides) - set(MULTIPLIER_IDS)
    if unknown:
        raise ValueError(f"unknown cost multipliers {sorted(unknown)}")
    costs = replace(CostInputs(phase["PHASE2"], phase["PHASE3"], **mult), **overrides)
    for name in ("phase2", "phase3", *MULTIPLIER_IDS):
        if not getattr(costs, name) >= 0:
            raise ValueError(f"{name} must be >= 0: {getattr(costs, name)}")
    return costs


def gate_costs(gate_names: Sequence[str], costs: CostInputs) -> np.ndarray:
    """Cost paid on entering each gate, multipliers applied (USD million per asset)."""
    unknown = set(gate_names) - set(GATE_COST_PHASE)
    if unknown:
        raise ValueError(f"no cost rule for gates {sorted(unknown)}")
    per_phase = {"PHASE2": costs.phase2, "PHASE3": costs.phase3, None: 0.0}
    return costs.multiplier * np.array([per_phase[GATE_COST_PHASE[g]] for g in gate_names])


def asset_costs(stopped_at: np.ndarray, gate_cost: np.ndarray) -> np.ndarray:
    """Cost of each asset: every gate it entered, up to and including the one where it stopped."""
    k = len(gate_cost)
    return np.cumsum(gate_cost)[np.minimum(stopped_at, k - 1)]


def analytic_expected_asset_cost(gate_probs: Sequence[float], gate_cost: np.ndarray) -> float:
    """E[cost] = sum over gates of P(reach gate) x gate cost (Phase 2 + P(pass Phase 2) x Phase 3)."""
    reach = np.cumprod(np.concatenate([[1.0], np.asarray(gate_probs, dtype=float)[:-1]]))
    return float(reach @ np.asarray(gate_cost))


def analytic_cost_distribution(gate_probs: Sequence[float], gate_cost: np.ndarray,
                               n_assets: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact distribution of a portfolio's total cost (n_assets independent assets).

    Returns (totals, P(total), P(total and zero approvals)), sorted by total.
    """
    p = np.asarray(gate_probs, dtype=float)
    k = len(p)
    reach = np.cumprod(np.concatenate([[1.0], p[:-1]]))
    cum = np.cumsum(np.asarray(gate_cost, dtype=float))
    # per-asset outcomes: (cost, approved, probability); stop at gate j, or approved
    outcomes = [(cum[j], False, reach[j] * (1 - p[j])) for j in range(k)] + [(cum[-1], True, float(np.prod(p)))]
    levels = sorted({c for c, _, _ in outcomes})  # distinct asset costs
    # state = (number of assets at each cost level, any approved); no float keys, so no rounding
    states = {(tuple(0 for _ in levels), False): 1.0}
    for _ in range(n_assets):
        nxt: dict[tuple[tuple[int, ...], bool], float] = {}
        for (counts, any_app), pr in states.items():
            for c, app, q in outcomes:
                i = levels.index(c)
                key = (counts[:i] + (counts[i] + 1,) + counts[i + 1:], any_app or app)
                nxt[key] = nxt.get(key, 0) + pr * q
        states = nxt
    by_total: dict[tuple[int, ...], list[float]] = {}
    for (counts, any_app), pr in states.items():
        both = by_total.setdefault(counts, [0, 0])
        both[0] += pr
        if not any_app:
            both[1] += pr
    rows = sorted((float(np.dot(counts, levels)), both[0], both[1]) for counts, both in by_total.items())
    totals, prob, zero = (np.array(col) for col in zip(*rows))
    return totals, prob, zero


def discrete_quantile(values: np.ndarray, probs: np.ndarray, level: float) -> float:
    """Smallest value with P(X <= value) >= level (same rule as np.quantile method='inverted_cdf')."""
    cdf = np.cumsum(probs) / np.sum(probs)
    tol = np.finfo(float).eps * cdf.size  # cumulative rounding error
    return float(np.asarray(values)[np.searchsorted(cdf, level - tol)])


def discrete_var_cvar(values: np.ndarray, probs: np.ndarray, alpha: float) -> tuple[float, float]:
    """VaR and CVaR of a discrete cost distribution; same definitions as var_cvar."""
    w = np.asarray(probs) / np.sum(probs)
    var = discrete_quantile(values, w, alpha)
    return var, var + float(w @ np.maximum(np.asarray(values) - var, 0)) / (1 - alpha)


def var_cvar(x: np.ndarray, alpha: float) -> tuple[float, float]:
    """VaR and CVaR of a cost (high = bad) at level alpha.

    VaR = smallest x with P(X <= x) >= alpha. CVaR = VaR + E[(X - VaR)+] / (1 - alpha)
    (Rockafellar-Uryasev), which is the mean of the worst (1 - alpha) tail even when X has atoms.
    """
    x = np.asarray(x, dtype=float)
    var = float(np.quantile(x, alpha, method="inverted_cdf"))
    return var, var + float(np.maximum(x - var, 0).mean()) / (1 - alpha)
