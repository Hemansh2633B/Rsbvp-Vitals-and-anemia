"""Fair-comparison metrics for the RSBVP research benchmark.

All functions operate on explicit (reference, estimate) pairs per window.
No reference value ever enters a backend; joining happens here, afterwards.
Overlapping windows are correlated — pooled statistics are descriptive only;
participant-level groupings and bootstrap confidence intervals are reported
separately, and the two are never conflated.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np


def error_metrics(pairs: Sequence[tuple[float, float]]) -> dict:
    """MAE/RMSE/bias/LoA/Pearson/MAPE over (reference_bpm, estimate_bpm) pairs."""
    if not pairs:
        return {
            "n_pairs": 0, "mae_bpm": None, "rmse_bpm": None, "bias_bpm": None,
            "loa_lower_95_bpm": None, "loa_upper_95_bpm": None,
            "pearson_r": None, "mape_percent": None,
            "within_3_bpm_fraction": None, "within_5_bpm_fraction": None,
        }
    ref = np.array([p[0] for p in pairs], dtype=float)
    est = np.array([p[1] for p in pairs], dtype=float)
    errors = est - ref
    bias = float(errors.mean())
    sd = float(errors.std(ddof=1)) if len(errors) > 1 else None
    pearson = None
    if len(errors) >= 3 and np.std(ref) > 0 and np.std(est) > 0:
        pearson = float(np.corrcoef(ref, est)[0, 1])
    nonzero_ref = np.abs(ref) > 1e-9
    mape = float(np.mean(np.abs(errors[nonzero_ref] / ref[nonzero_ref])) * 100.0) if nonzero_ref.any() else None
    return {
        "n_pairs": int(len(pairs)),
        "mae_bpm": float(np.abs(errors).mean()),
        "rmse_bpm": float(np.sqrt(np.mean(errors ** 2))),
        "bias_bpm": bias,
        "loa_lower_95_bpm": (bias - 1.96 * sd) if sd is not None else None,
        "loa_upper_95_bpm": (bias + 1.96 * sd) if sd is not None else None,
        "pearson_r": pearson,
        "mape_percent": mape,
        "within_3_bpm_fraction": float(np.mean(np.abs(errors) <= 3.0)),
        "within_5_bpm_fraction": float(np.mean(np.abs(errors) <= 5.0)),
    }


def window_key(recording_id: str, window_start_s: float) -> str:
    return f"{recording_id}|{window_start_s:.3f}"


def availability_summary(records: Iterable) -> dict:
    """Estimate availability + rejection accounting over window records."""
    total = 0
    usable = 0
    rejected = 0
    reasons: dict[str, int] = {}
    low_quality = 0
    ok = 0
    for record in records:
        if getattr(record, "backend_output_type", "window") != "window":
            continue
        total += 1
        if record.estimated_hr_bpm is not None:
            usable += 1
        quality = record.signal_quality or "unknown"
        head = quality.split(":", 1)[0]
        if head == "ok":
            ok += 1
        elif head == "low_quality":
            low_quality += 1
        if head in {"rejected", "unavailable"}:
            rejected += 1
            reason = quality.split(":", 1)[1] if ":" in quality else quality
            # Collapse verbose reasons to a stable bucket.
            bucket = reason.split(":", 1)[0]
            reasons[bucket] = reasons.get(bucket, 0) + 1
    return {
        "windows_total": total,
        "windows_with_estimate": usable,
        "estimate_availability": (usable / total) if total else None,
        "windows_quality_ok": ok,
        "windows_low_quality": low_quality,
        "quality_ok_fraction": (ok / total) if total else None,
        "windows_rejected_or_unavailable": rejected,
        "rejection_or_unavailability_reasons": reasons,
    }


def participant_bootstrap_mae(
    participant_pairs: dict[str, list[tuple[float, float]]],
    *,
    n_boot: int = 1000,
    seed: int = 20261123,
) -> dict | None:
    """Deterministic bootstrap CI of pooled MAE resampling participants."""
    participants = sorted(p for p, pairs in participant_pairs.items() if pairs)
    if len(participants) < 2:
        return None
    rng = np.random.default_rng(seed)
    maes: list[float] = []
    for _ in range(n_boot):
        sample = rng.choice(participants, size=len(participants), replace=True)
        errors = [abs(est - ref) for p in sample for (ref, est) in participant_pairs[p]]
        if errors:
            maes.append(float(np.mean(errors)))
    if not maes:
        return None
    lo, hi = np.percentile(maes, [2.5, 97.5])
    return {
        "mae_ci95_bpm": [float(lo), float(hi)],
        "participants": len(participants),
        "bootstrap_samples": n_boot,
        "seed": seed,
    }


def join_estimates_with_references(records, reference_by_key: dict[str, float]):
    """Yield ((recording_id, key), record, reference) for paired windows."""
    for record in records:
        if getattr(record, "backend_output_type", "window") != "window":
            continue
        key = window_key(record.recording_id, record.timestamp_s)
        reference = reference_by_key.get(key)
        if reference is None:
            continue
        yield record, reference


def memory_peak_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0
