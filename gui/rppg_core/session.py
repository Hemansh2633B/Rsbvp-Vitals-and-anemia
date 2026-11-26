"""Session-level measurement collection and aggregation (Python pathway).

This mirrors ``gui/frontend/src/rppg/sessionAggregate.ts`` for the live pathway
whose DSP runs on the server (``gui/rppg_core/live.py`` -> WebSocket). The rules
are the same on purpose: a session result must be computed from readings that
passed the *existing* quality gate, must be honest about how much independent
evidence it rests on, and must never be a fabricated number.

Kept deliberately dependency-free (standard library only) so it can be imported
by the live loop without touching the DSP imports.

Design rules, each covered by a test:

* Readings are append-only; the aggregate never overwrites history.
* A reading is accepted only if the existing verdict is ``valid``, the value is
  finite, and it is inside a wide data-hygiene band for its metric.
* Different metrics and units are never combined in one aggregate.
* Different algorithms are never averaged together: a series is per algorithm
  and the presented result is the agreement-checked consensus only.
* Overlapping windows are not independent observations, so the standard error
  uses the non-overlapping subset count, never the raw reading count.
* Too little evidence yields an explicit ``insufficient`` verdict, never a
  number and never an invented confidence score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Sequence

#: Series label for the per-window consensus estimate (the presented result).
CONSENSUS = "consensus"

SCHEMA = "rsbvp.session-aggregate.v1"


@dataclass(frozen=True)
class MetricSpec:
    """Static description of an aggregatable metric.

    ``plausible_min``/``plausible_max`` are data-hygiene bounds: they catch unit
    mix-ups and lost estimates (0, 3, 900). They are NOT healthy ranges and carry
    no clinical meaning.
    """

    id: str
    label: str
    unit: str
    decimals: int
    plausible_min: float
    plausible_max: float
    note: str


METRICS: dict[str, MetricSpec] = {
    "heart_rate": MetricSpec(
        "heart_rate", "Heart rate", "BPM", 1, 30.0, 220.0,
        "Estimate from accepted camera readings, not a medical measurement.",
    ),
    "respiratory_rate": MetricSpec(
        "respiratory_rate", "Respiratory rate", "br/min", 1, 4.0, 60.0,
        "Derived from beat-to-beat interval variability (experimental); "
        "not a direct breathing measurement.",
    ),
}

#: Metrics that must never be averaged into a session result, with the reason.
NOT_AGGREGATED: dict[str, str] = {
    "rmssd": "Requires beat-to-beat pulse timing with independent reference validation; not available.",
    "sdnn": "Requires beat-to-beat pulse timing with independent reference validation; not available.",
    "pnn50": "Requires beat-to-beat pulse timing with independent reference validation; not available.",
    "spo2": "Not measurable from consumer RGB video; no validated estimator exists in this project.",
    "blood_pressure": "Not measurable from this method; deliberately absent.",
    "hemoglobin": "Anemia image features stay in a separate, non-cardiovascular pathway; no model exists.",
}


@dataclass(frozen=True)
class AggregationConfig:
    """Aggregation thresholds. Configurable so a study can state its own."""

    min_accepted_readings: int = 5
    min_independent_windows: int = 2
    target_accepted_readings: int = 8
    stale_after_ms: int = 5000
    plausible: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {k: (v.plausible_min, v.plausible_max) for k, v in METRICS.items()}
    )


DEFAULT_CONFIG = AggregationConfig()


@dataclass(frozen=True)
class Reading:
    """One measurement produced by one analysis window."""

    metric: str
    value: float | None
    algorithm: str
    roi: str
    quality_score: float | None
    quality_verdict: str
    fs_hz: float | None
    n_samples: int | None
    window_start_s: float | None
    window_end_s: float | None
    rejection_reason: str | None
    analyzed_at_ms: float
    session_elapsed_s: float | None
    window_index: int | None = None


@dataclass(frozen=True)
class Measurement(Reading):
    """A reading plus the collection decision, so nothing is dropped silently."""

    id: int = 0
    recorded_utc: str = ""
    accepted: bool = False
    final_rejection_reason: str | None = None


@dataclass(frozen=True)
class MetricAggregate:
    metric: str
    label: str
    unit: str
    decimals: int
    note: str
    algorithm: str
    verdict: str  # available | insufficient | no_readings
    reason: str
    n_accepted: int = 0
    n_rejected: int = 0
    n_total: int = 0
    acceptance_pct: float | None = None
    mean: float | None = None
    median: float | None = None
    min: float | None = None
    max: float | None = None
    sd: float | None = None
    range: float | None = None
    n_independent_accepted: int | None = None
    overlap_factor: float | None = None
    standard_error: float | None = None
    first_accepted_utc: str | None = None
    last_accepted_utc: str | None = None
    median_quality: float | None = None
    algorithms_seen: tuple[str, ...] = ()
    multiple_algorithm_series: bool = False

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "label": self.label,
            "unit": self.unit,
            "algorithm": self.algorithm,
            "verdict": self.verdict,
            "reason": self.reason,
            "accepted_readings": self.n_accepted,
            "rejected_readings": self.n_rejected,
            "total_readings": self.n_total,
            "acceptance_pct": self.acceptance_pct,
            "mean": self.mean,
            "median": self.median,
            "min": self.min,
            "max": self.max,
            "sd": self.sd,
            "range": self.range,
            "independent_windows": self.n_independent_accepted,
            "overlap_factor": self.overlap_factor,
            "standard_error": self.standard_error,
            "median_quality_score": self.median_quality,
            "first_accepted_utc": self.first_accepted_utc,
            "last_accepted_utc": self.last_accepted_utc,
        }


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return math.fsum(values) / len(values)


def sample_sd(values: Sequence[float]) -> float | None:
    """Sample standard deviation (n-1). One value has no spread to report."""
    if len(values) < 2:
        return None
    m = mean(values)
    assert m is not None
    return math.sqrt(math.fsum((v - m) ** 2 for v in values) / (len(values) - 1))


def median(values: Sequence[float]) -> float | None:
    """Median; ``None`` for an empty series (never 0)."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def classify_reading(
    reading: Reading, config: AggregationConfig = DEFAULT_CONFIG, now_ms: float | None = None
) -> tuple[bool, str | None]:
    """May this reading contribute to a session average? Returns (accepted, reason)."""
    if reading.metric not in METRICS:
        return False, f"unsupported_metric:{reading.metric}"
    reference = reading.analyzed_at_ms if now_ms is None else now_ms
    if reference - reading.analyzed_at_ms > config.stale_after_ms:
        # The loop re-reported an old analysis: it describes a moment that has
        # passed, so it must not be counted as a current observation.
        return False, "stale_reading"
    # The pipeline's own verdict takes precedence over a missing value: "ROIs
    # lost" tells a reader more than "no estimate".
    if reading.quality_verdict != "valid":
        return False, reading.rejection_reason or reading.quality_verdict
    if reading.value is None or not math.isfinite(reading.value):
        return False, "valid_verdict_without_estimate"
    low, high = config.plausible.get(reading.metric, (METRICS[reading.metric].plausible_min,
                                                       METRICS[reading.metric].plausible_max))
    if not (low <= reading.value <= high):
        return False, f"implausible_value_{reading.value:.1f}_outside_{low:g}-{high:g}"
    return True, None


def count_independent_windows(readings: Iterable[Reading]) -> int | None:
    """Number of readings whose windows do not overlap each other.

    Greedy interval scheduling by end time. Sliding-window analysis re-analyses
    the same stretch of signal many times, so the raw count hugely overstates how
    many independent observations a session contains. ``None`` when no reading
    carries window bounds - unknown, never guessed.
    """
    bounded = [r for r in readings if r.window_start_s is not None and r.window_end_s is not None]
    if not bounded:
        return None
    ordered = sorted(bounded, key=lambda r: (r.window_end_s, r.window_start_s))
    count = 0
    last_end = float("-inf")
    for r in ordered:
        assert r.window_start_s is not None and r.window_end_s is not None
        if r.window_start_s >= last_end:  # touching windows are adjacent, not overlapping
            count += 1
            last_end = r.window_end_s
    return count


class SessionCollector:
    """Append-only collection of every reading produced during one session."""

    def __init__(self, config: AggregationConfig = DEFAULT_CONFIG) -> None:
        self._config = config
        self._readings: list[Measurement] = []
        self._next_id = 1

    @property
    def config(self) -> AggregationConfig:
        return self._config

    def add(self, reading: Reading, now_ms: float | None = None) -> Measurement:
        accepted, reason = classify_reading(reading, self._config, now_ms)
        measurement = Measurement(
            **{**reading.__dict__},
            id=self._next_id,
            recorded_utc=_iso(reading.analyzed_at_ms),
            accepted=accepted,
            final_rejection_reason=None if accepted else reason,
        )
        self._next_id += 1
        self._readings.append(measurement)
        return measurement

    @property
    def readings(self) -> list[Measurement]:
        return list(self._readings)

    def accepted(self, metric: str | None = None) -> list[Measurement]:
        return [r for r in self._readings if r.accepted and (metric is None or r.metric == metric)]

    def rejected(self, metric: str | None = None) -> list[Measurement]:
        return [r for r in self._readings if not r.accepted and (metric is None or r.metric == metric)]

    def reset(self) -> None:
        """Start a new session: history is cleared, ids restart."""
        self._readings = []
        self._next_id = 1

    def __len__(self) -> int:
        return len(self._readings)


def summarize(
    readings: Sequence[Measurement], metric: str, algorithm: str = CONSENSUS,
    config: AggregationConfig = DEFAULT_CONFIG,
) -> MetricAggregate:
    """Summarise one metric for one algorithm series.

    A series is always a single algorithm by construction (separation happens by
    filtering); the mixed case is asserted rather than trusted.
    """
    if metric not in METRICS:
        spec = METRICS["heart_rate"]
        return MetricAggregate(metric, spec.label, spec.unit, spec.decimals, spec.note,
                               algorithm, "insufficient", f"unsupported_metric:{metric}")
    spec = METRICS[metric]
    for_metric = [r for r in readings if r.metric == metric]
    if not for_metric:
        return MetricAggregate(metric, spec.label, spec.unit, spec.decimals, spec.note,
                               algorithm, "no_readings",
                               "No readings recorded for this metric in this session")
    algorithms_seen = tuple(sorted({r.algorithm for r in for_metric}))
    series = [r for r in for_metric if r.algorithm == algorithm]
    accepted = [r for r in series if r.accepted]
    n_rejected = len(series) - len(accepted)
    acceptance_pct = (len(accepted) / len(series) * 100.0) if series else None

    if len({r.algorithm for r in series}) > 1:
        return MetricAggregate(metric, spec.label, spec.unit, spec.decimals, spec.note, algorithm,
                               "insufficient",
                               "Series mixes several algorithms; they are not interchangeable and "
                               "were not averaged",
                               n_accepted=len(accepted), n_rejected=n_rejected, n_total=len(series),
                               acceptance_pct=acceptance_pct, algorithms_seen=algorithms_seen,
                               multiple_algorithm_series=len(algorithms_seen) > 1)

    values = [r.value for r in accepted if r.value is not None]
    independent = count_independent_windows(accepted)
    overlap_factor = (len(accepted) / independent) if independent else None
    qualities = [r.quality_score for r in accepted
                 if r.quality_score is not None and math.isfinite(r.quality_score)]

    base = dict(
        metric=metric, label=spec.label, unit=spec.unit, decimals=spec.decimals, note=spec.note,
        algorithm=algorithm, n_accepted=len(accepted), n_rejected=n_rejected, n_total=len(series),
        acceptance_pct=acceptance_pct, n_independent_accepted=independent,
        overlap_factor=overlap_factor, median_quality=median(qualities),
        algorithms_seen=algorithms_seen, multiple_algorithm_series=len(algorithms_seen) > 1,
        first_accepted_utc=accepted[0].recorded_utc if accepted else None,
        last_accepted_utc=accepted[-1].recorded_utc if accepted else None,
    )

    if not values:
        reason = (f"No accepted readings ({n_rejected} rejected by the quality gates)"
                  if series else "No readings for this algorithm in this session")
        return MetricAggregate(verdict="insufficient", reason=reason, **base)

    m = mean(values)
    sd = sample_sd(values)
    low, high = min(values), max(values)
    standard_error = None
    if independent is not None and independent >= 3 and sd is not None:
        standard_error = sd / math.sqrt(independent)

    result = dict(base, mean=m, median=median(values), min=low, max=high, sd=sd,
                  range=high - low, standard_error=standard_error)

    if len(values) < config.min_accepted_readings:
        return MetricAggregate(
            verdict="insufficient",
            reason=(f"Only {len(values)} accepted reading{'s' if len(values) != 1 else ''}; at least "
                    f"{config.min_accepted_readings} are needed for a session average"),
            **result)
    if independent is not None and independent < config.min_independent_windows:
        return MetricAggregate(
            verdict="insufficient",
            reason=(f"Only {independent} independent (non-overlapping) window"
                    f"{'s' if independent != 1 else ''}; at least {config.min_independent_windows} "
                    "are needed"),
            **result)
    return MetricAggregate(verdict="available", reason="", **result)


ACCEPTANCE_BANDS = {"good": 70.0, "fair": 40.0}


def summarize_session(
    readings: Sequence[Measurement], config: AggregationConfig = DEFAULT_CONFIG
) -> dict:
    """Session summary: per-metric aggregates plus completion state."""
    metrics = [summarize(readings, m, config=config) for m in METRICS]
    per_algorithm: list[MetricAggregate] = []
    for metric in METRICS:
        algorithms = sorted({r.algorithm for r in readings if r.metric == metric})
        for algorithm in algorithms:
            if algorithm == CONSENSUS:
                continue
            per_algorithm.append(summarize(readings, metric, algorithm, config=config))

    # The interface counts analysed *windows*: the per-estimator series of one
    # window are diagnostics, not additional evidence.
    primary = [r for r in readings if r.algorithm == CONSENSUS]
    n_accepted = sum(1 for r in primary if r.accepted)
    n_rejected = len(primary) - n_accepted
    acceptance_pct = (n_accepted / len(primary) * 100.0) if primary else None
    if acceptance_pct is None:
        band = None
    elif acceptance_pct >= ACCEPTANCE_BANDS["good"]:
        band = "good"
    elif acceptance_pct >= ACCEPTANCE_BANDS["fair"]:
        band = "fair"
    else:
        band = "poor"

    presentable = [a for a in metrics if a.verdict == "available"]
    # Progress is tracked on the primary metric's accepted count, NOT on whether
    # an average is presentable yet: otherwise a session with some accepted
    # readings but not enough for an average would claim nothing had passed.
    progress_metric = next((a for a in metrics if a.metric == "heart_rate"), metrics[0])
    accepted_so_far = progress_metric.n_accepted
    completion = "idle"
    completion_reason = "Start a session to collect readings"
    if primary:
        completion = "collecting"
        completion_reason = (
            f"{accepted_so_far} of {config.target_accepted_readings} accepted readings collected"
            if accepted_so_far > 0
            else f"No readings accepted yet ({n_rejected} rejected by the quality checks)")
        if accepted_so_far >= config.target_accepted_readings:
            completion = "complete"
            completion_reason = ("Enough accepted readings for a session average; you can stop "
                                 "the camera")

    return {
        "metrics": metrics,
        "per_algorithm": per_algorithm,
        "windows_total": len(primary),
        "windows_accepted": n_accepted,
        "windows_rejected": n_rejected,
        "readings_total": len(readings),
        "readings_accepted": sum(1 for r in readings if r.accepted),
        "acceptance_pct": acceptance_pct,
        "acceptance_band": band,
        "completion": completion,
        "completion_reason": completion_reason,
        "has_result": bool(presentable),
        "config": config,
    }


def build_aggregate_export(summary: dict, session_id: str, created_utc: str,
                           acquisition: dict | None = None) -> dict:
    """JSON-serialisable session aggregate.

    The independence caveat travels with the statistics so a reader cannot take
    the mean of hundreds of overlapping windows as hundreds of observations.
    """
    config: AggregationConfig = summary["config"]
    return {
        "schema": SCHEMA,
        "created_utc": created_utc,
        "capture_session_id": session_id,
        "primary_series": CONSENSUS,
        "metrics": [a.as_dict() for a in summary["metrics"]],
        "per_estimator": [a.as_dict() for a in summary["per_algorithm"]],
        "windows_total": summary["windows_total"],
        "windows_accepted": summary["windows_accepted"],
        "windows_rejected": summary["windows_rejected"],
        "readings_total": summary["readings_total"],
        "readings_accepted": summary["readings_accepted"],
        "acceptance_pct": summary["acceptance_pct"],
        "acceptance_band": summary["acceptance_band"],
        "acceptance_band_note": (
            "Band derived from the observed acceptance rate only. It is not a confidence "
            "score and says nothing about accuracy."
        ),
        "completion_state": summary["completion"],
        "completion_reason": summary["completion_reason"],
        "aggregation_config": {
            "min_accepted_readings": config.min_accepted_readings,
            "min_independent_windows": config.min_independent_windows,
            "target_accepted_readings": config.target_accepted_readings,
            "stale_after_ms": config.stale_after_ms,
            "plausible_bounds": {k: list(v) for k, v in config.plausible.items()},
        },
        "acquisition": acquisition or {},
        "statistics_notes": [
            "The mean is the arithmetic mean of accepted readings only; rejected readings are "
            "counted but never averaged.",
            "Readings come from overlapping analysis windows, so independent_windows is the number "
            "of non-overlapping observations and the only basis used for the standard error.",
            "standard_error is null when fewer than three independent windows exist, rather than "
            "being estimated from overlapping samples.",
            "Averaging readings reduces random variation; it does not establish physiological "
            "accuracy and this is not a medical measurement.",
        ],
        "frames_images_included": False,
        "frames_uploaded": False,
    }


READINGS_CSV_HEADER = (
    "reading_id", "metric", "unit", "value", "algorithm", "roi", "accepted",
    "rejection_reason", "quality_score", "quality_verdict", "sampling_rate_hz",
    "n_samples", "window_start_s", "window_end_s", "session_elapsed_s",
    "window_index", "recorded_utc",
)


def _cell(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if any(ch in text for ch in ',"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def build_readings_csv(readings: Sequence[Measurement]) -> str:
    """One row per reading, accepted and rejected alike, so nothing is hidden."""
    lines = [",".join(READINGS_CSV_HEADER)]
    for r in readings:
        spec = METRICS.get(r.metric)
        cells = [
            r.id, r.metric, spec.unit if spec else "", r.value, r.algorithm, r.roi,
            "true" if r.accepted else "false", r.final_rejection_reason, r.quality_score,
            r.quality_verdict, r.fs_hz, r.n_samples, r.window_start_s, r.window_end_s,
            r.session_elapsed_s, r.window_index, r.recorded_utc,
        ]
        lines.append(",".join(_cell(c) for c in cells))
    return "\n".join(lines)
