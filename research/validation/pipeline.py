"""End-to-end evaluation pipeline.

``evaluate_session`` is the single entry point: validate, align, score, compare,
and package the result with the provenance needed to reproduce it.

Nothing here writes files or draws plots — that separation is deliberate, so the
numbers can be tested independently of the presentation and the report can be
regenerated from a saved JSON without re-reading the inputs.

**What this pipeline will not do**, by construction:

* It will not evaluate an undeclared time base or an unestablished offset.
* It will not pool heart rate with any other metric.
* It will not count per-estimator rows as extra evidence.
* It will not report an accuracy statistic whose ``n`` is below the floor.
* It will not describe synthetic input as real-world validation; the
  ``input_is_synthetic`` flag is propagated into every artefact.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from research.validation.alignment import (
    AlignmentResult,
    OffsetEstimate,
    SyncConfig,
    align,
    derive_offset,
)
from research.validation.errors import (
    INFO,
    REJECT,
    WARN,
    InputFinding,
    InputRejection,
    summarise_findings,
    worst_severity,
)
from research.validation.loader import LoadedSession, load_session_bundle
from research.validation.method_comparison import (
    MethodResult,
    compare_methods,
    evaluate_all_series,
    evaluate_session_aggregation,
)
from research.validation.metric_rules import (
    MIN_ACCEPTED_READINGS,
    MIN_INDEPENDENT_WINDOWS,
    density_ratio,
    acceptance_band,
)
from research.validation.reference import ReferenceTable, load_reference

RESULTS_SCHEMA = "rsbvp.validation-results.v1"
PROTOCOL_VERSION = "sprint17-1"

#: The number of paired observations below which the whole evaluation is declared
#: insufficient rather than reported with caveats. Ten is not a statistical
#: threshold; it is the point below which a pooled MAE is not worth printing at all.
MIN_PAIRS_FOR_EVALUATION = 3


@dataclass
class EvaluationResult:
    """Everything one evaluation produced, in a form that can be serialised."""

    schema: str
    protocol_version: str
    created_utc: str
    inputs: dict
    validation: dict
    sync: dict
    metrics: dict
    methods: list[dict]
    comparison: dict
    session_aggregation: dict
    coverage: dict
    stratification: dict
    findings: list[dict]
    limitations: list[str]
    reproducibility: dict
    input_is_synthetic: bool
    #: Kept out of the JSON: the raw observations are large and the report only
    #: needs summaries. Available for plotting.
    alignment: AlignmentResult | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "schema": self.schema,
            "protocol_version": self.protocol_version,
            "created_utc": self.created_utc,
            "input_is_synthetic": self.input_is_synthetic,
            "inputs": self.inputs,
            "validation": self.validation,
            "sync": self.sync,
            "metrics": self.metrics,
            "methods": self.methods,
            "comparison": self.comparison,
            "session_aggregation": self.session_aggregation,
            "coverage": self.coverage,
            "stratification": self.stratification,
            "findings": self.findings,
            "limitations": self.limitations,
            "reproducibility": self.reproducibility,
        }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path) -> str | None:
    try:
        from pathlib import Path
        return _sha256_bytes(Path(path).read_bytes())
    except Exception:  # noqa: BLE001 - a digest is provenance, not a requirement
        return None


LIMITATIONS = [
    "Overlapping analysis windows are autocorrelated, so pooled per-window statistics are "
    "descriptive of these recordings and are not a population estimate.",
    "A pooled bootstrap interval resamples windows and is therefore optimistic; only a "
    "participant-level resample generalises, and that needs more than one participant.",
    "Correlation is not agreement and not accuracy. An estimator with a fixed offset can "
    "correlate almost perfectly and still be wrong by that offset on every window.",
    "Agreement with a reference is not clinical validation. These are estimates from consumer "
    "cameras compared with another measurement device, not diagnoses.",
    "Coverage limits every accuracy figure: methods that produce fewer estimates are scored on a "
    "smaller, self-selected part of the session unless the shared-subset comparison says otherwise.",
    "A session average reduces zero-mean window noise only. Correlated error, drift and a "
    "changing reference are not reduced by averaging and can make a session mean worse than a "
    "typical window.",
    "No HRV, blood pressure, oxygen saturation or hemoglobin quantity can be inferred from these "
    "evaluations; none is computed here.",
]


def evaluate_session(
    *,
    readings_csv=None,
    summary_json=None,
    reference_csv=None,
    sync: SyncConfig | None = None,
    anchors: Sequence[tuple[float, float]] | None = None,
    stratum: str | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> EvaluationResult:
    """Run the full evaluation. Raises :class:`InputRejection` on blocking problems.

    Ordering matters: the session and reference are validated *before* alignment, and
    alignment is validated before any statistic, so a report never shows numbers
    derived from input that failed its checks.
    """
    if reference_csv is None:
        raise InputRejection([InputFinding(
            REJECT, "no_reference",
            "no reference measurement supplied. RSBVP cannot validate itself: an independent "
            "measurement from another device is required, and the platform will not synthesise "
            "one.")])

    loaded: LoadedSession = load_session_bundle(readings_csv=readings_csv, summary_json=summary_json)
    reference: ReferenceTable = load_reference(reference_csv)

    findings: list[InputFinding] = list(loaded.findings) + list(reference.findings)

    # --- synchronisation ----------------------------------------------------
    effective_sync = sync or SyncConfig()
    offset_provenance = ""
    if anchors is not None:
        estimate = derive_offset(anchors)
        findings.append(InputFinding(
            INFO if estimate.established else REJECT,
            "offset_derivation",
            f"offset derivation: {estimate.reason}",
            count=estimate.anchors))
        if estimate.established:
            effective_sync = SyncConfig(
                time_base=effective_sync.time_base,
                offset_s=estimate.offset_s,
                min_overlap_fraction=effective_sync.min_overlap_fraction,
                min_window_duration_s=effective_sync.min_window_duration_s,
                evaluate_from_s=effective_sync.evaluate_from_s,
                evaluate_to_s=effective_sync.evaluate_to_s,
                max_reference_variation_fraction=effective_sync.max_reference_variation_fraction,
            )
            offset_provenance = estimate.reason
        else:
            # Do not fall back to a supplied offset: a derivation that failed means the
            # anchors contradict, and quietly using something else would hide that.
            findings.append(InputFinding(
                REJECT, "offset_not_established",
                "the anchor set could not establish an offset; see the offset_derivation finding"))

    if worst_severity(findings) is REJECT:
        raise InputRejection(findings)

    alignment = align(loaded.export.primary(), reference, effective_sync)
    findings.extend(alignment.findings)
    if worst_severity(findings) is REJECT:
        raise InputRejection(findings)

    # --- metrics ------------------------------------------------------------
    observations = alignment.pairs
    primary = loaded.export.primary()
    accepted = [r for r in primary if r.accepted_recomputed]
    considered = len(primary)
    series_results: list[MethodResult] = evaluate_all_series(
        observations, windows_considered=considered)

    # Per-estimator series: evaluated separately, never pooled with consensus.
    estimator_observations: list = []
    if readings_csv is not None:
        for algorithm, roi in loaded.export.by_series():
            if algorithm == "consensus":
                continue
            subset = [r for r in loaded.export.readings
                      if r.algorithm == algorithm and r.roi == roi]
            sub_alignment = align(subset, reference, effective_sync)
            estimator_observations.extend(sub_alignment.pairs)
    estimator_results: list[MethodResult] = evaluate_all_series(
        estimator_observations, windows_considered=considered) if estimator_observations else []

    # The comparison must cover every series that was scored, not just the consensus
    # one. An earlier version built this dict from `series_results` alone, so with a
    # single consensus series the report said "only one method series was paired" while
    # the table above it listed nine scored GREEN/POS/CHROM series — the comparison
    # silently ignored every estimator.
    by_method: dict[str, list] = {}
    for result in [*series_results, *estimator_results]:
        by_method[result.label] = [
            o for o in estimator_observations + observations
            if o.algorithm == result.algorithm and o.roi == result.roi]
    by_method = {label: pairs for label, pairs in by_method.items() if pairs}

    # The headline block is the consensus/all-regions series, which is what the
    # application's session result is built from.
    headline = next((r for r in series_results if r.roi in {"all", "face"}), None)
    headline_dict = headline.as_dict() if headline else {
        "available": False,
        "reason": "no consensus all-region series was paired with the reference",
    }

    independent = None
    from research.validation.metric_rules import BoundedWindow, count_independent_windows
    independent = count_independent_windows(
        [BoundedWindow(o.window_start_s, o.window_end_s) for o in observations])

    density = density_ratio([r.session_elapsed_s for r in accepted])
    agg = evaluate_session_aggregation(
        observations,
        # Detection happens inside evaluate_session_aggregation, which discloses flagged
        # windows without removing them. Nothing is passed in from here, so the
        # pipeline cannot quietly exclude a window that passed every gate.
        outlier_ids=None,
    )

    coverage_block = {
        "windows_recorded": considered,
        "windows_accepted": len(accepted),
        "windows_rejected": considered - len(accepted),
        "windows_paired": len(observations),
        "windows_unmatched": len(alignment.unmatched),
        "windows_excluded_from_alignment": len(alignment.excluded),
        "independent_windows_paired": independent,
        "acceptance_rate": (len(accepted) / considered) if considered else None,
        "acceptance_band": acceptance_band((len(accepted) / considered) * 100 if considered else None),
        "density_ratio": density,
        "density_note": "Reported only. Uneven density means the session mean weights the most "
                        "analysed stretch most; it never alters a statistic here.",
        "evaluation_adequacy": {
            "min_accepted_readings_required": MIN_ACCEPTED_READINGS,
            "min_independent_windows_required": MIN_INDEPENDENT_WINDOWS,
            "accepted_readings_sufficient": len(accepted) >= MIN_ACCEPTED_READINGS,
            "independent_windows_sufficient": (
                independent is not None and independent >= MIN_INDEPENDENT_WINDOWS),
        },
    }

    stratification = _stratify(observations)

    evaluation_available = (
        len(observations) >= MIN_PAIRS_FOR_EVALUATION
        and bool(headline and headline.available))

    metrics_block = {
        "n_paired_observations": len(observations),
        "evaluation_available": evaluation_available,
        "reason": "" if evaluation_available else (
            f"{len(observations)} paired observation(s) with a comparable reference; more are "
            "needed before an accuracy statement is made"),
        "headline_series": headline_dict,
        "error_by_window": agg.individual if agg.available else {},
        "per_estimator_series": [r.as_dict() for r in estimator_results],
        "session_aggregation": agg.as_dict(),
    }

    created = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reproducibility = {
        "protocol_version": PROTOCOL_VERSION,
        "deterministic": True,
        "random_sources": ["bootstrap MAE interval (seeded)"],
        "bootstrap_seed": 20261127,
        "input_digests": {
            "readings_csv": _file_digest(readings_csv) if readings_csv is not None else None,
            "summary_json": _file_digest(summary_json) if summary_json is not None else None,
            "reference_csv": _file_digest(reference_csv) if reference_csv is not None else None,
        },
        "reproduce_with": (
            "research.validation.evaluate_session(readings_csv=..., summary_json=..., "
            "reference_csv=..., sync=SyncConfig(**sync_settings))"),
        "sync_settings": effective_sync.as_dict(),
        "python": _python_version(),
        "numpy": _numpy_version(),
    }

    return EvaluationResult(
        schema=RESULTS_SCHEMA,
        protocol_version=PROTOCOL_VERSION,
        created_utc=created,
        inputs={
            "session_source": loaded.export.source,
            "session_id": loaded.export.session_id,
            "reference_source": reference.source,
            "reference_layout": "intervals" if reference.interval_mode else "samples",
            "reference_span_s": list(reference.span_s),
            "acquisition": (loaded.export.summary or {}).get("acquisition") or {},
            "stratum": stratum,
            "notes": notes,
        },
        validation={
            "findings": [f.as_dict() for f in findings],
            "summary": summarise_findings(findings),
            "session_findings": [f.as_dict() for f in loaded.findings],
            "reference_findings": [f.as_dict() for f in reference.findings],
        },
        sync={
            "settings": effective_sync.as_dict(),
            "offset_provenance": alignment.offset_provenance or offset_provenance,
            "coverage": alignment.coverage(),
            "unmatched": alignment.unmatched[:200],
            "unmatched_truncated": len(alignment.unmatched) > 200,
            "excluded": alignment.excluded[:200],
            "excluded_truncated": len(alignment.excluded) > 200,
        },
        metrics=metrics_block,
        methods=[*[r.as_dict() for r in series_results],
                 *[r.as_dict() for r in estimator_results]],
        comparison=compare_methods(by_method) if len(by_method) > 1 else {
            "comparisons": [],
            "note": "Only one method series was paired with the reference, so there is nothing "
                    "to compare. A comparison needs at least two series on the same reference.",
        },
        session_aggregation=agg.as_dict(),
        coverage=coverage_block,
        stratification=stratification,
        findings=[f.as_dict() for f in findings],
        limitations=LIMITATIONS,
        reproducibility=reproducibility,
        input_is_synthetic=loaded.export.synthetic or reference.synthetic,
        alignment=alignment,
    )


def _stratify(observations: Sequence) -> dict:
    """Group by whatever metadata the reference carries.

    Only metadata that is *supplied* is used. Nothing is inferred from the estimates:
    a camera model guessed from an accuracy figure would be a fabricated covariate.
    Absent metadata is reported as ``unknown``, never dropped.
    """
    groups: dict[str, dict[str, list]] = {"condition": {}, "device": {}, "participant": {}}
    for observation in observations:
        for name in groups:
            value = getattr(observation, name, None) or "unknown"
            groups[name].setdefault(value, []).append(observation)

    out: dict[str, Any] = {"available": False, "note": (
        "Stratification uses only metadata supplied alongside the reference. Nothing is inferred "
        "from the estimates, and absent metadata is labelled unknown.")}
    for name, values in groups.items():
        if set(values) == {"unknown"}:
            out[name] = {"unknown": {"n": len(observations), "mae_bpm": None}}
            continue
        out["available"] = True
        block = {}
        for value, subset in sorted(values.items()):
            from research.validation.method_comparison import to_pairs
            from research.validation.metrics import agreement as _agreement
            score = _agreement(to_pairs(subset))
            block[value] = {
                "n": len(subset),
                "mae_bpm": score.get("mae_bpm"),
                "bias_bpm": score.get("bias_bpm"),
                "available": bool(score.get("available")),
            }
        out[name] = block
    return out


def _python_version() -> str:
    import platform
    return platform.python_version()


def _numpy_version() -> str:
    import numpy
    return numpy.__version__
