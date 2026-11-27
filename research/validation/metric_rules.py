"""The evaluation rule set, shared with the TypeScript session layer.

Why this file exists separately: the research platform must apply *the same*
acceptance rules the application applied, or a study would evaluate a filtered
subset while claiming to evaluate the app. Two independent re-implementations of
"which readings count" is precisely how the browser and Python paths drifted
before Sprint 16.

The constants mirror ``gui/frontend/src/rppg/sessionAggregate.ts`` and
``gui/rppg_core/session.py``. ``tests/test_validation_parity.py`` reads all three
and fails if they disagree, so a change to one without the others is a test
failure rather than a silent divergence.

Nothing here re-decides whether a reading is *physiologically* valid. These are
data-hygiene rules: unit mix-ups, lost estimates, and double counting.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

# --- Constants mirrored in both implementations -----------------------------

CONSENSUS = "consensus"
DUPLICATE_WINDOW = "duplicate_window"
STALE_READING = "stale_reading"

MIN_ACCEPTED_READINGS = 5
MIN_INDEPENDENT_WINDOWS = 2
TARGET_ACCEPTED_READINGS = 8
STALE_AFTER_MS = 5000
DENSITY_RATIO_WARNING = 3.0
SUPPRESS_DUPLICATE_WINDOWS = True
OUTLIER_SD_THRESHOLD = 2.5
OUTLIER_MIN_DEVIATION_BPM = 6.0
VARIABILITY_SD_WARNING_BPM = 8.0

#: Data-hygiene plausibility bounds in BPM. NOT healthy ranges, NOT a clinical
#: judgement: they catch a lost estimate (0, 3) or a unit error (900).
PLAUSIBLE_BPM = (30.0, 220.0)

#: Acceptance bands for the plain-language quality indicator. Observed acceptance
#: rate only; never a confidence score.
ACCEPTANCE_BANDS = {"good": 70.0, "fair": 40.0}

#: Metrics the platform will evaluate. Deliberately a closed set.
EVALUABLE_METRICS = ("heart_rate",)


@dataclass(frozen=True)
class Classification:
    """Outcome of the shared acceptance rule."""

    accepted: bool
    reason: str | None


def window_key(metric: str, algorithm: str, start_s: float | None, end_s: float | None,
               roi: str | None = None) -> str | None:
    """Identity of the underlying observation.

    The same metric, estimator, ROI and window bounds describe one moment, however
    many times it was written out. Unknown bounds return ``None`` and are never
    treated as duplicates: not knowing the window is not evidence that it repeats one.

    ``roi`` is part of the identity. Forehead, left-cheek and right-cheek estimates of
    the *same* window are three measurements of one moment, not a repetition of one —
    treating them as duplicates would delete two of the three ROIs before the ROI
    comparison could run. Whether they should count as three independent observations
    is a separate question, answered by the independence analysis, not here.
    """
    if start_s is None or end_s is None:
        return None
    if not (math.isfinite(start_s) and math.isfinite(end_s)):
        return None
    suffix = f"|{roi}" if roi is not None else ""
    return f"{metric}|{algorithm}|{start_s}|{end_s}{suffix}"


def is_duplicate(metric: str, algorithm: str, start_s: float | None, end_s: float | None,
                 seen: set[str], roi: str | None = None) -> bool:
    key = window_key(metric, algorithm, start_s, end_s, roi)
    return key is not None and key in seen


def classify_reading(
    *,
    metric: str,
    value: float | None,
    quality_verdict: str,
    rejection_reason: str | None,
    naive_dup: bool,
) -> Classification:
    """Apply the same acceptance rule the application applied.

    ``naive_dup`` is supplied by the caller because duplicate detection is a
    property of the file, not of a single row. It is checked last so a duplicate
    that also failed a quality gate keeps the more specific reason.
    """
    if metric not in EVALUABLE_METRICS:
        return Classification(False, f"unsupported_metric:{metric}")
    if quality_verdict != "valid":
        return Classification(False, rejection_reason or quality_verdict or "invalid_verdict")
    if value is None or not (isinstance(value, (int, float)) and math.isfinite(value)):
        return Classification(False, "valid_verdict_without_estimate")
    low, high = PLAUSIBLE_BPM
    if not (low <= float(value) <= high):
        return Classification(False, f"implausible_value_{float(value):.1f}_outside_{low:g}-{high:g}")
    if SUPPRESS_DUPLICATE_WINDOWS and naive_dup:
        return Classification(False, DUPLICATE_WINDOW)
    return Classification(True, None)


@dataclass(frozen=True)
class BoundedWindow:
    start_s: float | None
    end_s: float | None


def count_independent_windows(windows: Iterable[BoundedWindow]) -> int | None:
    """Greedy interval scheduling by end time.

    Sliding-window analysis re-analyses every 500 ms over a 10 s window, so almost
    every pair of readings overlaps and the raw count hugely overstates how many
    distinct observations a session contains. Returns ``None`` when no window has
    usable bounds, rather than guessing.
    """
    bounded = [(w.start_s, w.end_s) for w in windows
               if w.start_s is not None and w.end_s is not None
               and math.isfinite(w.start_s) and math.isfinite(w.end_s)]
    if not bounded:
        return None
    bounded.sort(key=lambda pair: (pair[1], pair[0]))
    count = 0
    last_end = -math.inf
    for start, end in bounded:
        if start >= last_end:  # touching windows are adjacent, not overlapping
            count += 1
            last_end = end
    return count


def density_ratio(elapsed: Sequence[float | None]) -> float | None:
    """Ratio of the densest third of the session to the sparsest third.

    Reported, never applied: it describes whether one stretch of the session was
    analysed more often than another, which is the condition under which the
    all-window mean can be biased. It never changes a statistic.
    """
    times = sorted(t for t in elapsed if t is not None and math.isfinite(t))
    if len(times) < 4:
        return None
    span = times[-1] - times[0]
    if not span > 0:
        return None
    third = span / 3.0
    if third <= 0:
        return None
    counts = [0, 0, 0]
    for t in times:
        counts[min(2, int((t - times[0]) / third))] += 1
    nonzero = [c for c in counts if c > 0]
    if not nonzero:
        return None
    sparsest = min(nonzero)
    if sparsest == 0:
        return None
    return max(nonzero) / sparsest


def acceptance_band(acceptance_pct: float | None) -> str | None:
    if acceptance_pct is None:
        return None
    if acceptance_pct >= ACCEPTANCE_BANDS["good"]:
        return "good"
    if acceptance_pct >= ACCEPTANCE_BANDS["fair"]:
        return "fair"
    return "poor"
