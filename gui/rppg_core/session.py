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
    #: May this metric occupy the headline position? Only independently
    #: substantiated metrics may; see the respiratory-rate spec.
    primary: bool = False
    #: Must be labelled experimental wherever it is shown.
    experimental: bool = True


METRICS: dict[str, MetricSpec] = {
    "heart_rate": MetricSpec(
        "heart_rate", "Heart rate", "BPM", 1, 30.0, 220.0,
        "Estimate from accepted camera readings, not a medical measurement.",
        primary=True, experimental=False,
    ),
    "respiratory_rate": MetricSpec(
        "respiratory_rate", "Respiratory rate", "br/min", 1, 4.0, 60.0,
        # Not a direct breathing measurement: inferred from pulse-to-pulse
        # interval variability, unvalidated against a respiratory reference, and
        # confounded by motion and by the pulse estimate itself.
        "Experimental. Inferred from beat-to-beat pulse-interval variability, not from a "
        "breathing measurement; unvalidated against a respiratory reference.",
        primary=False, experimental=True,
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
    #: Above this ratio of densest to sparsest analysis density the result is
    #: flagged as potentially density-biased. Reports a property of the accepted
    #: readings; it is not a quality gate.
    density_ratio_warning: float = 3.0
    #: A reading whose window repeats one already recorded is the same observation
    #: arriving twice. It is kept in history (flagged, never deleted) but excluded
    #: from the aggregate so one window cannot contribute twice.
    suppress_duplicate_windows: bool = True
    #: A reading this many sample SDs from the mean is FLAGGED, never removed.
    #: The project rule is that nothing is dropped for disagreeing with the others.
    outlier_sd_threshold: float = 2.5
    #: Spread (sample SD, in the metric's own unit) at or above which the session is
    #: described as variable rather than steady. Interpretable in BPM.
    variability_sd_warning: float = 8.0
    #: Smallest deviation from the rest of the session, in the metric's own unit,
    #: that can count as an outlier at all. The spread test alone is a poor flag at
    #: small n: when six windows agree to within 1 BPM, a 1.4 BPM difference is
    #: statistically "far" and would be flagged on every steady session. A reading
    #: must be both statistically unusual AND materially different. Affects only the
    #: label, never the statistics.
    outlier_min_deviation: dict[str, float] = field(
        default_factory=lambda: {"heart_rate": 6.0, "respiratory_rate": 3.0}
    )
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
    #: Accepted readings whose window repeats one already counted. Excluded from
    #: every statistic; surfaced so the UI can explain what was set aside.
    n_duplicate_windows: int = 0
    #: Accepted readings flagged as far from the centre. These ARE included in
    #: every statistic; nothing is removed for disagreeing with the mean.
    n_flagged_outliers: int = 0
    flagged_outlier_ids: tuple[int, ...] = ()
    #: True when the spread across accepted readings warrants a variability warning.
    variable: bool = False

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "label": self.label,
            "unit": self.unit,
            "algorithm": self.algorithm,
            "verdict": self.verdict,
            "reason": self.reason,
            "experimental": METRICS[self.metric].experimental if self.metric in METRICS else True,
            "primary": METRICS[self.metric].primary if self.metric in METRICS else False,
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


#: Rejection reason for a window that repeats one already recorded.
#:
#: Asymmetric with ``stale_reading``: stale describes a moment the session has moved
#: past, duplicate describes a moment already counted. Both are excluded, both named.
DUPLICATE_WINDOW = "duplicate_window"

#: Rejection reasons that mean "not a new observation" rather than "bad signal".
NON_OBSERVATION_REASONS = frozenset({DUPLICATE_WINDOW})


def window_key(reading: Reading) -> str | None:
    """Identity of the underlying observation.

    The same metric, estimator and window bounds describe one moment in the
    session, however many times the pipeline re-reports it. Unknown bounds return
    None and are never treated as duplicates: "I do not know the window" is not
    evidence that it repeats one.
    """
    start, end = reading.window_start_s, reading.window_end_s
    if start is None or end is None:
        return None
    if not (math.isfinite(start) and math.isfinite(end)):
        return None
    return f"{reading.metric}|{reading.algorithm}|{start}|{end}"


def classify_reading(
    reading: Reading, config: AggregationConfig = DEFAULT_CONFIG, now_ms: float | None = None,
    prior: Sequence[Reading] = (),
) -> tuple[bool, str | None]:
    """May this reading contribute to a session average? Returns (accepted, reason).

    ``prior`` is the session history so far and is used only for the duplicate
    check; every other rule is a property of the reading alone.
    """
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
    # A duplicate window is the same observation arriving twice; letting it in
    # would give one moment two votes in the mean, the median and every count.
    # Checked last so a duplicate that also failed a gate keeps the specific reason.
    if config.suppress_duplicate_windows:
        key = window_key(reading)
        if key is not None and any(
            (r.accepted or getattr(r, "final_rejection_reason", None) == DUPLICATE_WINDOW)
            and window_key(r) == key
            for r in prior
        ):
            return False, DUPLICATE_WINDOW
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


#: What the capture is doing. Completion is not derivable from readings alone.
SESSION_LIFECYCLE = ("running", "stopped", "interrupted")


def density_ratio(readings: Sequence[Reading]) -> float | None:
    """Ratio of the densest to the sparsest analysis density across the session.

    Density is readings per unit time over the span the readings cover, split
    into thirds so a single short burst does not dominate. ``None`` when there is
    too little span to judge, rather than guessing 1.

    This exists because the all-window mean weights every reading equally: when
    one stretch was analysed far more often than another, that stretch dominates
    the average. Reporting the ratio makes the condition visible without changing
    the statistic.
    """
    times = [r.session_elapsed_s for r in readings
             if r.session_elapsed_s is not None and math.isfinite(r.session_elapsed_s)]
    if len(times) < 4:
        return None
    ordered = sorted(times)
    span = ordered[-1] - ordered[0]
    if not span > 0:
        return None
    third = span / 3.0
    if third <= 0:
        return None
    start = ordered[0]
    counts = [0, 0, 0]
    for t in ordered:
        counts[min(2, int((t - start) / third))] += 1
    non_zero = [c for c in counts if c > 0]
    if not non_zero:
        return None
    sparsest = min(non_zero)
    return max(non_zero) / sparsest if sparsest else None


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
        # History is passed in so the duplicate rule can see what is already counted.
        accepted, reason = classify_reading(reading, self._config, now_ms, self._readings)
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
    # A duplicate window is recorded but is not a new observation: kept out of the
    # statistics, counted separately, so "rejected" and "already counted" stay
    # distinguishable in the UI and the export.
    duplicates = [r for r in series if r.final_rejection_reason == DUPLICATE_WINDOW]
    accepted = [r for r in series if r.accepted]
    n_rejected = len(series) - len(accepted) - len(duplicates)
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
        n_duplicate_windows=len(duplicates),
        acceptance_pct=acceptance_pct, n_independent_accepted=independent,
        overlap_factor=overlap_factor, median_quality=median(qualities),
        algorithms_seen=algorithms_seen, multiple_algorithm_series=len(algorithms_seen) > 1,
        first_accepted_utc=accepted[0].recorded_utc if accepted else None,
        last_accepted_utc=accepted[-1].recorded_utc if accepted else None,
    )

    if not values:
        if not series:
            reason = "No readings for this algorithm in this session"
        elif len(duplicates) == len(series):
            reason = (f"All {len(series)} readings repeated a window already counted, "
                      "so none are new observations")
        else:
            dup = (f", {len(duplicates)} duplicate window{'s' if len(duplicates) != 1 else ''}"
                   if duplicates else "")
            reason = f"No accepted readings ({n_rejected} rejected by the quality gates{dup})"
        return MetricAggregate(verdict="insufficient", reason=reason, **base)

    m = mean(values)
    sd = sample_sd(values)
    low, high = min(values), max(values)
    standard_error = None
    if independent is not None and independent >= 3 and sd is not None:
        standard_error = sd / math.sqrt(independent)

    # Outliers are FLAGGED, never removed: dropping a reading for disagreeing with
    # the mean would hide the disagreement a reader most needs, and with
    # autocorrelated windows it would bias the result toward the survivors.
    #
    # Leave-one-out on purpose: comparing a reading with a centre and spread that
    # include it lets one wild value inflate the spread it is judged against (in
    # [70,71,72,71,70,155] the naive limit is 86 and misses 155). Excluding the
    # reading from its own baseline catches it. n >= 3 so a spread exists.
    flagged: list[int] = []
    if sd is not None and sd > 0 and len(accepted) >= 3:
        for r in accepted:
            others = [o.value for o in accepted
                      if o.id != r.id and o.value is not None]
            centre = mean(others)
            spread = sample_sd(others)
            if centre is None or spread is None:
                continue
            deviation = abs(r.value - centre)
            material = deviation >= config.outlier_min_deviation.get(r.metric, 0.0)
            if spread == 0:
                far = r.value != centre and material
            else:
                far = deviation > config.outlier_sd_threshold * spread and material
            if far:
                flagged.append(r.id)
    flagged_ids = tuple(flagged)

    result = dict(base, mean=m, median=median(values), min=low, max=high, sd=sd,
                  range=high - low, standard_error=standard_error,
                  n_flagged_outliers=len(flagged_ids), flagged_outlier_ids=flagged_ids,
                  variable=sd is not None and sd >= config.variability_sd_warning)

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
    readings: Sequence[Measurement], config: AggregationConfig = DEFAULT_CONFIG,
    lifecycle: str = "stopped",
) -> dict:
    """Session summary: per-metric aggregates, completion state, result availability.

    The single rule this function exists to enforce: ``completed`` (permission to
    stop) and ``available`` (a headline number) both require the aggregate verdict
    to actually be ``available``. An accepted-reading count is progress, never
    permission to stop.
    """
    if lifecycle not in SESSION_LIFECYCLE:
        raise ValueError(f"unknown lifecycle: {lifecycle}")
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
    # "The signal was bad" and "this window was already counted" are different
    # messages; adding them together would misreport what happened.
    n_duplicate = sum(1 for r in primary if r.final_rejection_reason == DUPLICATE_WINDOW)
    n_rejected = len(primary) - n_accepted - n_duplicate
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
    # Completion follows the metric the interface headlines: heart rate. A session
    # is not "available" because a secondary metric has enough readings.
    primary_aggregate = next((a for a in metrics if a.metric == "heart_rate"), metrics[0])
    result_available = primary_aggregate.verdict == "available"
    needed = config.min_accepted_readings
    progress_metric = primary_aggregate

    # Density flag uses the consensus series only: the per-estimator readings are
    # recorded at the same moments, so including them would divide out.
    density = density_ratio(primary)
    uneven_density = density is not None and density > config.density_ratio_warning

    if not primary:
        if lifecycle == "interrupted":
            completion, completion_reason = (
                "interrupted", "Capture was interrupted before any window was analysed")
        elif lifecycle == "stopped":
            # No session exists yet. Calling an idle page "initialising" would
            # imply work is happening when none is.
            completion, completion_reason = (
                "idle", "No session yet: press Start to begin collecting readings")
        else:
            completion, completion_reason = (
                "initialising", "Waiting for the first analysable window")
    elif result_available:
        completion = "available" if lifecycle == "running" else "completed"
        completion_reason = (
            f"Session average available from {progress_metric.n_accepted} accepted readings; "
            "you can stop the camera" if lifecycle == "running"
            else f"Session complete: {progress_metric.n_accepted} accepted readings")
    elif lifecycle == "interrupted":
        completion = "interrupted"
        completion_reason = (f"Capture interrupted with {progress_metric.n_accepted} accepted "
                             "readings - not enough for a session average")
    elif lifecycle == "running":
        # Name whichever condition is actually blocking, so "collecting" is never a
        # vague reassurance when the real problem is overlap, not a low count.
        completion = "collecting"
        accepted = progress_metric.n_accepted
        independent = progress_metric.n_independent_accepted
        if accepted < needed:
            completion_reason = f"Collecting: {accepted} of {needed} accepted readings"
        elif independent is not None and independent < config.min_independent_windows:
            completion_reason = (
                f"Collecting: {accepted} accepted readings, but they overlap "
                f"({independent} independent window{'s' if independent != 1 else ''}); "
                "keep capturing")
        else:
            completion_reason = (f"Collecting: {accepted} accepted readings; waiting for the "
                                 "aggregate to become available")
    else:
        # Capture finished without enough evidence: a final state, and it never
        # invites the user to stop.
        completion = "insufficient"
        completion_reason = progress_metric.reason or (
            "Not enough accepted readings for a session average")

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
        "result_available": result_available,
        "density_ratio": density,
        "uneven_density": uneven_density,
        "has_result": bool(presentable),
        "n_duplicate_windows": n_duplicate,
        "n_flagged_outliers": primary_aggregate.n_flagged_outliers,
        "variable": primary_aggregate.variable,
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
        "duplicate_windows": summary["n_duplicate_windows"],
        "flagged_outliers": summary["n_flagged_outliers"],
        "variable": summary["variable"],
        "readings_total": summary["readings_total"],
        "readings_accepted": summary["readings_accepted"],
        "acceptance_pct": summary["acceptance_pct"],
        "acceptance_band": summary["acceptance_band"],
        "acceptance_band_note": (
            "Band derived from the observed acceptance rate only. It is not a confidence "
            "score and says nothing about accuracy."
        ),
        "completion_state": summary["completion"],
        "result_available": summary["result_available"],
        "density_ratio": summary["density_ratio"],
        "uneven_density": summary["uneven_density"],
        "completion_reason": summary["completion_reason"],
        "aggregation_config": {
            "min_accepted_readings": config.min_accepted_readings,
            "min_independent_windows": config.min_independent_windows,
            "target_accepted_readings": config.target_accepted_readings,
            "stale_after_ms": config.stale_after_ms,
            "density_ratio_warning": config.density_ratio_warning,
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
