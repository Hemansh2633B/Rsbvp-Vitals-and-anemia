"""Leakage-aware split and descriptive evaluation helpers (not clinical validation)."""
from __future__ import annotations
import numpy as np


def grouped_holdout(patient_ids, test_fraction=0.2, seed=42):
    """Return disjoint record indices, grouping all records by patient.

    Missing patient IDs are rejected: record-level splitting would falsely imply
    patient-independent evaluation. Caller must resolve label/ID provenance.
    """
    ids = np.asarray(patient_ids, dtype=object)
    if ids.ndim != 1 or len(ids) < 2 or any(x is None or str(x).strip() == "" for x in ids):
        raise ValueError("complete patient identifiers are required for grouped splitting")
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between zero and one")
    patients = np.unique(ids)
    if len(patients) < 2:
        raise ValueError("at least two distinct patients are required")
    rng = np.random.default_rng(seed)
    rng.shuffle(patients)
    n_test = min(len(patients)-1, max(1, round(len(patients)*test_fraction)))
    test_patients = set(patients[:n_test])
    test = np.flatnonzero(np.isin(ids, list(test_patients)))
    train = np.flatnonzero(~np.isin(ids, list(test_patients)))
    return train, test


def regression_metrics(reference, estimate):
    y, p = np.asarray(reference, float), np.asarray(estimate, float)
    if y.shape != p.shape or y.ndim != 1 or len(y) < 2 or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError("paired finite 1-D reference and estimate arrays required")
    error = p-y
    ss_tot = np.sum((y-y.mean())**2)
    bias = float(error.mean())
    sd = float(error.std(ddof=1))
    return {"mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error**2))),
            "r_squared": float(1-np.sum(error**2)/ss_tot) if ss_tot > 0 else None,
            "bias": bias, "loa_lower_95": bias-1.96*sd, "loa_upper_95": bias+1.96*sd}
