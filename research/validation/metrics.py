"""Accuracy, agreement and coverage statistics — with their sample counts.

The distinction this module exists to protect:

* **Correlation** (Pearson r) describes whether two series move together. It is
  invariant to scale and offset, so an estimator that reads exactly 20 % high has
  *perfect* correlation and terrible accuracy. It is reported, and it is labelled as
  a correlation, never as agreement or accuracy.
* **Agreement** (bias, Bland-Altman limits) describes how far the estimate sits from
  the reference. Two methods can agree on average while disagreeing wildly on
  individual samples, which is what the limits of agreement show and the bias hides.
* **Accuracy** (MAE, RMSE) is the size of the error, in BPM, in both directions.
* **Coverage** is how much of the session produced a usable estimate at all. A
  spectacular MAE over 3 windows is not better than a good MAE over 300; coverage is
  reported beside every accuracy figure for that reason.

No statistic is computed from fewer observations than it needs. Every returned block
carries ``n`` and, where relevant, an ``insufficient`` marker with the reason — never
a plausible-looking number computed from two points.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

#: Below this many paired observations, accuracy statistics are refused. Two points
#: define a line, not a distribution; reporting MAE from 2 pairs invites a reader to
#: treat it as a measurement of performance.
MIN_PAIRS_FOR_ACCURACY = 3
#: Pearson r needs variance in *both* series to mean anything.
MIN_PAIRS_FOR_CORRELATION = 3
#: Bland-Altman limits need enough pairs for an SD to be meaningful.
MIN_PAIRS_FOR_LIMITS_OF_AGREEMENT = 5


@dataclass(frozen=True)
class Pair:
    """One (reference, estimate) observation in BPM."""

    reference_bpm: float
    estimate_bpm: float
    key: str = ""

    @property
    def error(self) -> float:
        return self.estimate_bpm - self.reference_bpm


def _insufficient(reason: str, n: int) -> dict:
    return {"available": False, "reason": reason, "n_pairs": n}


def agreement(pairs: Sequence[Pair]) -> dict:
    """MAE, RMSE, bias, error SD, percentiles, and Bland-Altman limits.

    Returns ``available: False`` with a reason when there are too few pairs. It never
    returns a partially-computed block: a MAE without its n, or a limit of agreement
    without an SD, would be read as more than it is.
    """
    n = len(pairs)
    if n < MIN_PAIRS_FOR_ACCURACY:
        return _insufficient(
            f"{n} paired observation(s); at least {MIN_PAIRS_FOR_ACCURACY} are needed before any "
            "accuracy statistic is reported", n)

    ref = np.array([p.reference_bpm for p in pairs], dtype=float)
    est = np.array([p.estimate_bpm for p in pairs], dtype=float)
    errors = est - ref
    abs_errors = np.abs(errors)
    bias = float(errors.mean())
    sd = float(errors.std(ddof=1))
    result = {
        "available": True,
        "n_pairs": n,
        "mae_bpm": float(abs_errors.mean()),
        "rmse_bpm": float(np.sqrt(np.mean(errors ** 2))),
        "bias_bpm": bias,
        "median_absolute_error_bpm": float(np.median(abs_errors)),
        "error_sd_bpm": sd,
        "error_p05_bpm": float(np.percentile(errors, 5)),
        "error_p50_bpm": float(np.percentile(errors, 50)),
        "error_p95_bpm": float(np.percentile(errors, 95)),
        # The interval travels with its own caveat. Without the note a reader (or a
        # script) that copies `mae_ci95_bpm` alone reads it as a confidence interval
        # for the method, when it only resamples these windows.
        "mae_ci95_bpm": _bootstrap_mae_ci(abs_errors),
        "mae_ci95_note": (
            "resamples the paired windows, which overlap and are not independent, so this "
            "interval is optimistic; it is not an interval about RSBVP in general"),
    }

    if n >= MIN_PAIRS_FOR_LIMITS_OF_AGREEMENT:
        result["loa_lower_bpm"] = bias - 1.96 * sd
        result["loa_upper_bpm"] = bias + 1.96 * sd
        # The fraction of pairs inside the limits is a property of the sample, not a
        # guarantee about future measurements; it is reported as such.
        inside = np.abs(errors - bias) <= 1.96 * sd
        result["fraction_within_loa"] = float(inside.mean())
    else:
        result["loa_lower_bpm"] = None
        result["loa_upper_bpm"] = None
        result["fraction_within_loa"] = None
        result["loa_note"] = (
            f"limits of agreement need at least {MIN_PAIRS_FOR_LIMITS_OF_AGREEMENT} pairs; "
            f"{n} available")

    result["within_3_bpm_fraction"] = float(np.mean(abs_errors <= 3.0))
    result["within_5_bpm_fraction"] = float(np.mean(abs_errors <= 5.0))
    return result


def correlation(pairs: Sequence[Pair]) -> dict:
    """Pearson r, labelled as correlation and nothing else.

    Explicitly not an accuracy measure. ``interpretation`` says so in words, because
    a high r in a results table is read as "the method works" unless it is denied.
    """
    n = len(pairs)
    if n < MIN_PAIRS_FOR_CORRELATION:
        return _insufficient(
            f"{n} paired observation(s); at least {MIN_PAIRS_FOR_CORRELATION} are needed", n)
    ref = np.array([p.reference_bpm for p in pairs], dtype=float)
    est = np.array([p.estimate_bpm for p in pairs], dtype=float)
    if ref.std() == 0 or est.std() == 0:
        return _insufficient(
            "one of the series has no variance, so a correlation coefficient is undefined", n)
    r = float(np.corrcoef(ref, est)[0, 1])
    return {
        "available": True,
        "n_pairs": n,
        "pearson_r": r,
        "interpretation": (
            "Correlation only. It measures whether the two series move together and is invariant "
            "to scale and offset: an estimate that reads consistently high still correlates almost "
            "perfectly. It is not agreement and not accuracy."),
        # The reference range is shown because r depends on it: a narrow reference
        # range attenuates r and makes weak agreement look strong.
        "reference_range_bpm": [float(ref.min()), float(ref.max())],
        "estimate_range_bpm": [float(est.min()), float(est.max())],
    }


def _bootstrap_mae_ci(abs_errors: np.ndarray, *, n_boot: int = 2000,
                      seed: int = 20261127) -> list[float] | None:
    """Deterministic bootstrap CI of the MAE over observations.

    Clustered by participant when participant-level data exists (see
    ``participant_bootstrap``); this pooled version is *not* clustered and is
    therefore labelled as descriptive — overlapping windows are not independent
    draws, so this interval is optimistic and must not be quoted as a confidence
    interval about future sessions.
    """
    if len(abs_errors) < MIN_PAIRS_FOR_ACCURACY:
        return None
    rng = np.random.default_rng(seed)
    draws = rng.choice(abs_errors, size=(n_boot, len(abs_errors)), replace=True).mean(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return [float(lo), float(hi)]


def participant_bootstrap_mae(
    per_participant: dict[str, Sequence[Pair]], *, n_boot: int = 1000,
    seed: int = 20261127,
) -> dict | None:
    """MAE CI resampling *participants*, not windows.

    This is the honest interval when sessions come from several people: windows
    within one session are autocorrelated, so resampling them would understate the
    uncertainty. Needs at least two participants; returns ``None`` otherwise rather
    than pretending a single-session interval generalises.
    """
    groups = {k: [p for p in v if p is not None] for k, v in per_participant.items()}
    usable = {k: v for k, v in groups.items() if v}
    if len(usable) < 2:
        return None
    rng = np.random.default_rng(seed)
    keys = sorted(usable)
    maes: list[float] = []
    for _ in range(n_boot):
        sample = rng.choice(keys, size=len(keys), replace=True)
        errors = [abs(p.error) for key in sample for p in usable[key]]
        if errors:
            maes.append(float(np.mean(errors)))
    if not maes:
        return None
    lo, hi = np.percentile(maes, [2.5, 97.5])
    return {
        "mae_ci95_bpm": [float(lo), float(hi)],
        "participants": len(keys),
        "bootstrap_samples": n_boot,
        "seed": seed,
        "note": "resamples participants, not windows, because windows within a session are "
                "autocorrelated",
    }


def coverage(*, windows_considered: int, windows_paired: int, windows_accepted: int,
             independent_windows: int | None) -> dict:
    """How much usable data the session actually produced.

    Reported beside every accuracy figure. A low coverage means the accuracy numbers
    describe a small, self-selected part of the session.
    """
    return {
        "windows_considered": windows_considered,
        "windows_accepted": windows_accepted,
        "windows_paired": windows_paired,
        "independent_windows": independent_windows,
        "acceptance_rate": (windows_accepted / windows_considered) if windows_considered else None,
        "rejection_rate": (1 - windows_accepted / windows_considered) if windows_considered else None,
        "paired_fraction_of_accepted": (
            windows_paired / windows_accepted if windows_accepted else None),
        "note": "Coverage is reported with every accuracy figure: a small MAE over few paired "
                "windows describes only those windows.",
    }


def error_percentiles(pairs: Sequence[Pair]) -> dict:
    """Signed error percentiles — the distribution, not just its mean."""
    if len(pairs) < MIN_PAIRS_FOR_ACCURACY:
        return _insufficient(f"{len(pairs)} pairs", len(pairs))
    errors = np.array([p.error for p in pairs], dtype=float)
    percentiles = [5, 25, 50, 75, 95]
    return {
        "available": True,
        "n_pairs": len(pairs),
        **{f"p{p:02d}_bpm": float(np.percentile(errors, p)) for p in percentiles},
        "min_bpm": float(errors.min()),
        "max_bpm": float(errors.max()),
    }
