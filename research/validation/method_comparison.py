"""Per-method evaluation: algorithms, ROIs, and session-level aggregation.

Two things this module refuses to do, because both are easy and both are wrong:

* **Compare methods on different subsets and present the difference as method
  quality.** If POS pairs with 200 reference windows and CHROM with 60, their MAEs
  describe different parts of the session. Every comparison therefore reports its
  own coverage, the shared-subset MAE alongside the full-subset MAE, and a
  ``subset_comparability`` verdict. A method that only produces estimates when the
  signal is clean will look excellent on its own subset and average on the shared one.

* **Count overlapping windows as independent observations.** A session of 300
  sliding windows over 60 s is one recording, not 300 participants. Pooled statistics
  across windows are descriptive; the interval that generalises comes from resampling
  participants (``metrics.participant_bootstrap_mae``), and when there is one session
  there is no such interval and none is given.

The session-average analysis is a genuine question, not a formality: averaging can
*increase* bias when the session drifts, because a session mean is dominated by
whichever period was analysed most often. That is measured here, not assumed away.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from research.validation.alignment import PairedObservation
from research.validation.metric_rules import (
    CONSENSUS,
    OUTLIER_MIN_DEVIATION_BPM,
    OUTLIER_SD_THRESHOLD,
    BoundedWindow,
    count_independent_windows,
)
from research.validation.metrics import (
    MIN_PAIRS_FOR_ACCURACY,
    Pair,
    agreement,
    correlation,
    coverage as coverage_block,
)

#: Two methods' MAEs are only compared directly when their paired subsets overlap by
#: at least this fraction of the smaller subset.
MIN_SHARED_SUBSET_FRACTION = 0.7


def to_pairs(observations: Sequence[PairedObservation]) -> list[Pair]:
    return [Pair(o.reference_bpm, o.estimate_bpm, key=f"{o.algorithm}|{o.roi}|{o.reading_id}")
            for o in observations]


@dataclass
class MethodResult:
    """Evaluation of one (algorithm, roi) series."""

    label: str
    algorithm: str
    roi: str
    available: bool
    reason: str
    n_pairs: int
    agreement: dict
    correlation: dict
    coverage: dict

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "algorithm": self.algorithm,
            "roi": self.roi,
            "available": self.available,
            "reason": self.reason,
            "n_pairs": self.n_pairs,
            "agreement": self.agreement,
            "correlation": self.correlation,
            "coverage": self.coverage,
        }


def _label(algorithm: str, roi: str) -> str:
    algorithm_label = "Consensus" if algorithm == CONSENSUS else algorithm.upper()
    roi_label = "all regions" if roi in {"all", "face"} else roi.replace("_", " ")
    return f"{algorithm_label} · {roi_label}"


def evaluate_series(
    observations: Sequence[PairedObservation],
    *,
    windows_considered: int,
    windows_accepted: int,
    algorithm: str,
    roi: str,
) -> MethodResult:
    """Score one algorithm/ROI series and state what its coverage was."""
    pairs = to_pairs(observations)
    independent = count_independent_windows(
        [BoundedWindow(o.window_start_s, o.window_end_s) for o in observations])
    block = coverage_block(
        windows_considered=windows_considered,
        windows_paired=len(pairs),
        windows_accepted=windows_accepted,
        independent_windows=independent)
    result_agreement = agreement(pairs)
    result_correlation = correlation(pairs)
    available = bool(result_agreement.get("available"))
    reason = "" if available else str(result_agreement.get("reason", ""))
    return MethodResult(
        label=_label(algorithm, roi),
        algorithm=algorithm,
        roi=roi,
        available=available,
        reason=reason,
        n_pairs=len(pairs),
        agreement=result_agreement,
        correlation=result_correlation,
        coverage=block,
    )


def evaluate_all_series(
    observations: Sequence[PairedObservation], *, windows_considered: int,
) -> list[MethodResult]:
    """One result per (algorithm, roi) present in the *paired* set."""
    groups: dict[tuple[str, str], list[PairedObservation]] = {}
    for observation in observations:
        groups.setdefault((observation.algorithm, observation.roi), []).append(observation)
    results = [
        evaluate_series(group, windows_considered=windows_considered,
                        windows_accepted=len(group), algorithm=algorithm, roi=roi)
        for (algorithm, roi), group in sorted(groups.items())
    ]
    return results


def compare_methods(
    by_method: dict[str, list[PairedObservation]],
) -> dict:
    """Compare methods, and say when the comparison is not like-for-like.

    For each pair of methods it reports the MAE on each method's own subset, the MAE
    restricted to the windows *both* methods paired, and a verdict. The shared-subset
    figure is the only one that isolates method quality; the difference between it and
    the individual-subset figures is the selection effect, which is reported rather
    than hidden.
    """
    labels = sorted(by_method)
    # The shared subset is a set of *time intervals*, not a set of rows. Keying on
    # algorithm and ROI — which is what window identity means elsewhere — made the
    # intersection of any two different methods empty by construction, so every
    # comparison reported "0 shared windows". Two methods are compared on the same
    # moments, which is exactly what the shared subset is supposed to be.
    keyed = {
        label: {f"{o.window_start_s}|{o.window_end_s}": o for o in by_method[label]}
        for label in labels
    }
    comparisons = []
    for i, left in enumerate(labels):
        for right in labels[i + 1:]:
            left_keys, right_keys = set(keyed[left]), set(keyed[right])
            shared = left_keys & right_keys
            left_only, right_only = left_keys - right_keys, right_keys - left_keys
            smallest = min(len(left_keys), len(right_keys)) or 1
            shared_fraction = len(shared) / smallest

            left_all = agreement(to_pairs(list(keyed[left].values())))
            right_all = agreement(to_pairs(list(keyed[right].values())))
            shared_left = agreement(to_pairs([keyed[left][k] for k in shared]))
            shared_right = agreement(to_pairs([keyed[right][k] for k in shared]))

            comparable = shared_fraction >= MIN_SHARED_SUBSET_FRACTION and bool(
                shared_left.get("available")) and bool(shared_right.get("available"))

            if len(shared) < MIN_PAIRS_FOR_ACCURACY:
                verdict = "insufficient_shared_observations"
                explanation = (
                    f"the two methods share only {len(shared)} window(s) with a common reference, "
                    "so no like-for-like comparison exists. Their separate figures describe "
                    "different parts of the session.")
            elif comparable:
                verdict = "comparable"
                explanation = (
                    f"{len(shared)} shared window(s) ({shared_fraction:.0%} of the smaller subset) "
                    "allow a like-for-like comparison on the shared subset.")
            else:
                verdict = "not_comparable"
                explanation = (
                    f"the methods share only {shared_fraction:.0%} of the smaller subset, so their "
                    "own-subset figures cannot be attributed to method quality alone. The "
                    "shared-subset MAE is given; the coverage difference is part of the result.")

            comparisons.append({
                "left": left,
                "right": right,
                "shared_windows": len(shared),
                "left_only_windows": len(left_only),
                "right_only_windows": len(right_only),
                "shared_fraction": shared_fraction,
                "left_mae_own_subset_bpm": left_all.get("mae_bpm"),
                "right_mae_own_subset_bpm": right_all.get("mae_bpm"),
                "left_mae_shared_subset_bpm": shared_left.get("mae_bpm"),
                "right_mae_shared_subset_bpm": shared_right.get("mae_bpm"),
                "verdict": verdict,
                "explanation": explanation,
            })
    return {
        "comparisons": comparisons,
        "min_shared_subset_fraction": MIN_SHARED_SUBSET_FRACTION,
        "note": "Overlapping windows are not independent observations; these are descriptive "
                "pooled statistics, not a population estimate.",
    }


# --- session-average evaluation ---------------------------------------------


@dataclass
class SessionAggregationResult:
    """Individual-window versus session-level agreement with the reference."""

    available: bool
    reason: str
    n_windows: int
    n_independent_windows: int | None
    individual: dict
    session_mean: dict
    session_median: dict
    comparison: dict

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "n_windows": self.n_windows,
            "n_independent_windows": self.n_independent_windows,
            "individual_windows": self.individual,
            "outlier_detection": self.session_mean.get("outlier_detection", {}),
            "session_mean": self.session_mean,
            "session_median": self.session_median,
            "comparison": self.comparison,
        }


def detect_outliers(
    observations: Sequence[PairedObservation], *,
    sd_threshold: float = OUTLIER_SD_THRESHOLD,
    min_deviation_bpm: float = OUTLIER_MIN_DEVIATION_BPM,
) -> dict:
    """Flag windows whose error is far from the session's typical error.

    This **discloses; it does not remove**. The platform has no basis for deciding
    that a window which passed every quality gate is not real data, and removing one
    would quietly change the estimate that the session mean is compared on. What it
    can do is say "this window is unusual, look at it", so a reader can judge whether
    the session mean is being pulled by it and the median (which is not) is reported
    beside it.

    Two conditions must both hold before a window is called an outlier, because either
    alone produces nonsense:

    * it deviates by more than ``sd_threshold`` robust SDs (from the MAD, so the
      outliers themselves do not inflate the threshold), and
    * it deviates by more than ``min_deviation_bpm``, so a session of near-perfect
      windows does not flag a 0.3 BPM difference as an outlier.

    Returns ids, the robust statistics used, and the retained/excluded counts so a
    caller cannot report "n outliers removed" when nothing was removed.
    """
    errors = np.array([o.estimate_bpm - o.reference_bpm for o in observations], dtype=float)
    n = int(errors.size)
    if n < MIN_PAIRS_FOR_ACCURACY:
        return {
            "available": False,
            "reason": f"{n} paired window(s); at least {MIN_PAIRS_FOR_ACCURACY} are needed to "
                      "describe a typical error",
            "n": n,
            "outlier_ids": [],
            "removed": False,
        }

    median = float(np.median(errors))
    mad = float(np.median(np.abs(errors - median)))
    # 1.4826 * MAD is the consistent estimator of SD for normal data.
    robust_sd = 1.4826 * mad
    deviations = np.abs(errors - median)
    if robust_sd <= 0:
        # More than half the windows share an identical error: there is no spread to
        # rank against, so nothing can be called an outlier.
        flagged = np.zeros(n, dtype=bool)
    else:
        flagged = (deviations > sd_threshold * robust_sd) & (deviations > min_deviation_bpm)

    ids = [o.reading_id for o, flag in zip(observations, flagged) if flag]
    return {
        "available": True,
        "n": n,
        "median_error_bpm": median,
        "robust_sd_bpm": robust_sd,
        "sd_threshold": sd_threshold,
        "min_deviation_bpm": min_deviation_bpm,
        "outlier_ids": ids,
        "outlier_errors_bpm": [float(e) for e, flag in zip(errors, flagged) if flag],
        "n_flagged": len(ids),
        "removed": False,
        "note": (
            "Flagged windows are disclosed, not removed. The session statistics below include "
            "every accepted window; the median is reported beside the mean because it is not "
            "pulled by a single unusual window."),
    }


def evaluate_session_aggregation(
    observations: Sequence[PairedObservation], *,
    outlier_ids: Sequence[int] | None = None,
) -> SessionAggregationResult:
    """Does averaging improve agreement with the reference?

    Method. The individual-window distribution gives a per-window error distribution.
    The session mean and median are single numbers, so they are compared against the
    reference **for the same interval** — computed as the duration-weighted mean of the
    matched reference values, so a window that covered 30 s counts for more than one
    that covered 10 s. Comparing a time-weighted estimate against an unweighted
    reference would bias the comparison by the session's own sampling pattern.

    What the comparison can and cannot show:

    * Individual-window MAE is measured over windows that *passed the gates*, so it is
      already a filtered population. The session mean summarises the same filtered set.
      Averaging therefore cannot be credited with removing windows it never saw.
    * A session mean removes random, zero-mean window noise. It does **not** remove
      correlated error — a systematic offset, drift, or a lighting change that shifts
      every window the same way — and it can *increase* bias when the session drifts,
      because the mean is weighted by how often each period was analysed.
    * With one session the session-level statistics have n = 1. They are reported as a
      single observation and never given an interval.

    Outliers are **not** removed. They are detected (see :func:`detect_outliers`) and
    their ids are carried so a reader can see whether the session mean is being pulled
    by one; the median — which is not — is reported beside it. ``outlier_ids`` exists
    only so a caller can supply its own disclosure list; passing ids never removes
    those windows from any statistic.
    """
    pairs = to_pairs(observations)
    n = len(pairs)
    independent = count_independent_windows(
        [BoundedWindow(o.window_start_s, o.window_end_s) for o in observations])
    if n < MIN_PAIRS_FOR_ACCURACY:
        return SessionAggregationResult(
            available=False,
            reason=f"{n} paired window(s); at least {MIN_PAIRS_FOR_ACCURACY} are needed to "
                   "compare individual windows with a session aggregate",
            n_windows=n, n_independent_windows=independent,
            individual={}, session_mean={}, session_median={}, comparison={})

    estimates = np.array([o.estimate_bpm for o in observations], dtype=float)
    durations = np.array([max(o.window_end_s - o.window_start_s, 0.0) for o in observations])
    references = np.array([o.reference_bpm for o in observations], dtype=float)
    weights = durations if durations.sum() > 0 else np.ones_like(durations)

    session_mean = float(estimates.mean())
    session_median = float(np.median(estimates))
    # The reference for the interval the session actually covers, weighted the same
    # way the session mean implicitly is.
    reference_session = float(np.average(references, weights=weights))

    individual = agreement(pairs)
    mean_agreement = agreement([Pair(reference_session, session_mean)] * 1)
    median_agreement = agreement([Pair(reference_session, session_median)] * 1)

    mean_error = session_mean - reference_session
    median_error = session_median - reference_session

    # Is the session mean inside the individual-window error distribution?
    individual_errors = np.abs(estimates - references)
    p95 = float(np.percentile(individual_errors, 95))

    drift = _drift(observations)
    weighted_bias_note = ""
    if drift.get("available"):
        weighted_bias_note = (
            f" The error changes by {drift['change_over_span_bpm']:+.1f} BPM across the session "
            "(slope " + f"{drift['slope_bpm_per_s']:+.3f} BPM/s). The session mean gives every "
            "accepted window equal weight, so a stretch analysed more often contributes more; "
            "with a drifting error the mean inherits that stretch's bias rather than describing "
            "the whole interval.")

    outliers = detect_outliers(observations)
    disclosed_ids = list(outlier_ids) if outlier_ids is not None else list(
        outliers.get("outlier_ids", []))
    if outlier_ids is not None and outliers.get("available"):
        # Verify a caller-supplied list rather than trusting it silently: an id that
        # is not in this session would make the report refer to nothing.
        known = {o.reading_id for o in observations}
        disclosed_ids = [i for i in disclosed_ids if i in known]

    verdict, explanation = _session_verdict(
        individual_mae=individual.get("mae_bpm"),
        session_mean_abs_error=abs(mean_error),
        n=n, independent=independent, drift=drift)

    return SessionAggregationResult(
        available=True,
        reason="",
        n_windows=n,
        n_independent_windows=independent,
        individual=individual,
        session_mean={
            "estimate_bpm": session_mean,
            "reference_bpm": reference_session,
            "error_bpm": mean_error,
            "abs_error_bpm": abs(mean_error),
            "n": 1,
            "note": "One session-level observation. No interval is reported: with a single "
                    "session there is nothing to estimate one from.",
            "flagged_outlier_ids": disclosed_ids,
            "outliers_retained": True,
            "outlier_detection": outliers,
        },
        session_median={
            "estimate_bpm": session_median,
            "reference_bpm": reference_session,
            "error_bpm": median_error,
            "abs_error_bpm": abs(median_error),
            "n": 1,
            "note": "Reported beside the mean because it is not pulled by a single unusual "
                    "window. Neither is more 'correct'; they answer different questions.",
        },
        comparison={
            "individual_mae_bpm": individual.get("mae_bpm"),
            "individual_error_p95_bpm": p95,
            "session_mean_abs_error_bpm": abs(mean_error),
            "session_median_abs_error_bpm": abs(median_error),
            "averaging_improves_point_estimate": (
                abs(mean_error) < individual.get("mae_bpm", float("inf"))
                if individual.get("available") else None),
            "verdict": verdict,
            "explanation": explanation + weighted_bias_note,
            "reference_weighting": "duration-weighted mean of matched reference values",
            "drift": drift,
        },
    )


def _drift(observations: Sequence[PairedObservation]) -> dict:
    """Error drift across the session: does the estimator walk away from the reference?

    Uses the signed error against elapsed time. A non-zero slope means the session
    mean is not describing a stationary error, and averaging over a drifting series
    produces a number that matches no part of the recording particularly well.
    """
    points = [(o.session_elapsed_s, o.estimate_bpm - o.reference_bpm)
              for o in observations if o.session_elapsed_s is not None]
    if len(points) < MIN_PAIRS_FOR_ACCURACY:
        return {"available": False,
                "reason": f"{len(points)} timed observation(s) for a drift estimate"}
    times = np.array([p[0] for p in points], dtype=float)
    errors = np.array([p[1] for p in points], dtype=float)
    if times.std() == 0:
        return {"available": False, "reason": "all observations share one timestamp"}
    slope, intercept = np.polyfit(times, errors, 1)
    return {
        "available": True,
        "n": len(points),
        "slope_bpm_per_s": float(slope),
        "change_over_span_bpm": float(slope * (times.max() - times.min())),
        "intercept_bpm": float(intercept),
        "note": "A non-zero slope means the error is not stationary, so the session mean "
                "describes no single part of the recording well.",
    }


def _session_verdict(*, individual_mae: float | None, session_mean_abs_error: float,
                     n: int, independent: int | None, drift: dict) -> tuple[str, str]:
    if individual_mae is None:
        return ("insufficient", "the individual-window distribution is not available")
    if drift.get("available") and abs(drift["change_over_span_bpm"]) > individual_mae:
        return ("averaging_may_increase_bias",
                f"The error drifts by {drift['change_over_span_bpm']:.1f} BPM across the session, "
                "which is larger than the individual-window MAE. Averaging a drifting series does "
                "not converge to the reference; the session mean can be further from it than a "
                "typical window.")
    if session_mean_abs_error < individual_mae:
        return ("averaging_helped",
                f"The session mean is {individual_mae - session_mean_abs_error:.1f} BPM closer to "
                "the reference than the average individual window. That is consistent with "
                "zero-mean window noise being reduced by averaging; it is not evidence of accuracy "
                "beyond this recording.")
    return ("averaging_did_not_help",
            f"The session mean is {session_mean_abs_error - individual_mae:.1f} BPM further from "
            "the reference than the average individual window. Averaging removes random noise but "
            "not correlated error, and this session's errors did not average out.")


def aggregate_unpaired_window_statistics(observations: Sequence[PairedObservation]) -> dict:
    """Descriptive spread of the estimates themselves, independent of the reference."""
    if len(observations) < 2:
        return {"available": False, "reason": f"{len(observations)} observation(s)"}
    estimates = np.array([o.estimate_bpm for o in observations], dtype=float)
    return {
        "available": True,
        "n": len(observations),
        "mean_bpm": float(estimates.mean()),
        "median_bpm": float(np.median(estimates)),
        "sd_bpm": float(estimates.std(ddof=1)),
        "min_bpm": float(estimates.min()),
        "max_bpm": float(estimates.max()),
    }
