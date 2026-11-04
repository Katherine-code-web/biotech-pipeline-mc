"""Load model inputs from data/assumptions.csv by param_id (no values hard-coded here)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ASSUMPTIONS_CSV = ROOT / "data" / "assumptions.csv"
DURATIONS_MAIN_CSV = ROOT / "data" / "processed" / "durations_main.csv"

REVIEW_PRIORITY_ID = "FDA_PDUFA_PRIORITY_NME"
REVIEW_STANDARD_ID = "FDA_PDUFA_STANDARD_NME"

# Gate sequence per scenario, starting from a Phase 2 asset: (gate name, param_id).
SCENARIOS: dict[str, list[tuple[str, str]]] = {
    # BIO 2011-2020, all indications: Phase 2 -> 3 -> NDA/BLA submission -> approval
    "BIO": [
        ("P2_P3", "BIO21_POS_P2_P3_ALL_INDICATIONS"),
        ("P3_NDA", "BIO21_POS_P3_NDA_ALL_INDICATIONS"),
        ("NDA_APP", "BIO21_POS_NDA_APP_ALL_INDICATIONS"),
    ],
    # Wong 2019 Table 2, all indications (industry), Overall: Phase 2 -> 3 -> approval
    "Wong": [
        ("P2_P3", "WONG19_ALL_P2_P3_OVERALL"),
        ("P3_APP", "WONG19_ALL_P3_APP_OVERALL"),
    ],
}


@dataclass(frozen=True)
class GateSet:
    scenario: str
    names: tuple[str, ...]
    param_ids: tuple[str, ...]
    probs: tuple[float, ...]


def load_assumptions(path: Path = ASSUMPTIONS_CSV) -> dict[str, dict]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return {row["param_id"]: row for row in csv.DictReader(f)}


def load_gate_probs(scenario: str, path: Path = ASSUMPTIONS_CSV) -> GateSet:
    """Return the gate probabilities for a scenario, read from assumptions.csv.

    Only rows with status SOURCED are accepted (DO_NOT_USE / ASSUMPTION rows raise).
    """
    rows = load_assumptions(path)
    names, ids, probs = [], [], []
    for name, pid in SCENARIOS[scenario]:
        if pid not in rows:
            raise KeyError(f"{pid} not found in {path}")
        row = rows[pid]
        if row["status"] != "SOURCED":
            raise ValueError(f"{pid} has status {row['status']}; only SOURCED rows can be used as gate probabilities")
        p = float(row["value_pct"]) / 100
        if not 0 <= p <= 1:
            raise ValueError(f"{pid}: probability {p} out of [0, 1]")
        names.append(name)
        ids.append(pid)
        probs.append(p)
    return GateSet(scenario, tuple(names), tuple(ids), tuple(probs))


def load_review_months(path: Path = ASSUMPTIONS_CSV) -> tuple[float, float]:
    """Return (priority, standard) review months, read from assumptions.csv.

    Only SOURCED or DECIDED rows are accepted.
    """
    rows = load_assumptions(path)
    out = []
    for pid in (REVIEW_PRIORITY_ID, REVIEW_STANDARD_ID):
        if pid not in rows:
            raise KeyError(f"{pid} not found in {path}")
        row = rows[pid]
        if row["status"] not in ("SOURCED", "DECIDED"):
            raise ValueError(f"{pid} has status {row['status']}; only SOURCED/DECIDED rows can be used")
        out.append(float(row["value_months"]))
    return out[0], out[1]


def load_value(pid: str, column: str, allowed_status: tuple[str, ...], path: Path = ASSUMPTIONS_CSV) -> float:
    """One numeric cell of assumptions.csv, by param_id and column. Empty cells and other statuses raise."""
    rows = load_assumptions(path)
    if pid not in rows:
        raise KeyError(f"{pid} not found in {path}")
    row = rows[pid]
    if row["status"] not in allowed_status:
        raise ValueError(f"{pid} has status {row['status']}; allowed here: {', '.join(allowed_status)}")
    if row[column] == "":
        raise ValueError(f"{pid} has no value in column {column}")
    return float(row[column])


def load_sensitivity_values(pid: str, path: Path = ASSUMPTIONS_CSV) -> tuple[float, ...]:
    """Sensitivity values of a row (';'-separated in the sensitivity_values column); empty tuple if none."""
    rows = load_assumptions(path)
    if pid not in rows:
        raise KeyError(f"{pid} not found in {path}")
    cell = rows[pid]["sensitivity_values"]
    return tuple(float(v) for v in cell.split(";")) if cell else ()


def load_duration_vectors(path: Path = DURATIONS_MAIN_CSV) -> dict[str, np.ndarray]:
    """Resampling vectors of trial durations (months) by phase, e.g. {"PHASE2": ..., "PHASE3": ...}."""
    by_phase: dict[str, list[float]] = {}
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_phase.setdefault(row["phase"], []).append(float(row["duration_months"]))
    return {ph: np.asarray(v) for ph, v in by_phase.items()}
