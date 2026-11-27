"""Strict loaders for real RSBVP session exports.

Everything here reads what the application actually writes — nothing more. The two
formats are the ones ``BrowserPulse`` produces:

* ``rsbvp_session_summary_<UTC>.json`` (schema ``rsbvp.session-aggregate.v1``)
* ``rsbvp_session_readings_<UTC>.csv``  (one row per reading, accepted and rejected)

Loading is **strict**. A malformed value becomes a finding, not a coerced default.
Nothing is repaired silently: a researcher who is told "18 readings, 4 rejected"
must be able to trust that those are the file's numbers.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from research.validation.errors import (
    INFO,
    REJECT,
    WARN,
    InputFinding,
    InputRejection,
    Severity,
    worst_severity,
)
from research.validation.metric_rules import (
    CONSENSUS,
    DUPLICATE_WINDOW,
    EVALUABLE_METRICS,
    classify_reading,
    window_key,
)

SESSION_SCHEMA = "rsbvp.session-aggregate.v1"

#: Columns the CSV must have for a defensible evaluation. Extra columns are fine
#: (the schema is additive); missing ones are not, because each is used below.
REQUIRED_CSV_COLUMNS = (
    "reading_id",
    "metric",
    "value",
    "algorithm",
    "roi",
    "accepted",
    "quality_verdict",
    "window_start_s",
    "window_end_s",
    "recorded_utc",
)

#: Columns used when present; their absence is reported but not fatal.
OPTIONAL_CSV_COLUMNS = (
    "rejection_reason",
    "quality_score",
    "sampling_rate_hz",
    "n_samples",
    "session_elapsed_s",
    "window_index",
    "unit",
)


@dataclass(frozen=True)
class Reading:
    """One row of the readings CSV, in the file's own terms.

    ``value`` is ``None`` when the cell was empty (the app never writes 0 for a
    missing estimate) and also when the cell was unparseable — those two cases are
    distinguished by ``value_parse_error``.
    """

    reading_id: int
    metric: str
    value: float | None
    algorithm: str
    roi: str
    accepted_in_file: bool
    quality_verdict: str
    rejection_reason: str | None
    quality_score: float | None
    fs_hz: float | None
    n_samples: int | None
    window_start_s: float | None
    window_end_s: float | None
    session_elapsed_s: float | None
    window_index: int | None
    recorded_utc: str
    unit: str | None = None
    value_parse_error: str | None = None
    row_number: int | None = None

    #: Filled in by the loader: does our re-application of the shared rule agree
    #: with the ``accepted`` column the file carries?
    accepted_recomputed: bool = False
    recomputed_reason: str | None = None

    @property
    def is_duplicate(self) -> bool:
        return self.recomputed_reason == DUPLICATE_WINDOW

    @property
    def key(self) -> str | None:
        return window_key(self.metric, self.algorithm, self.window_start_s,
                          self.window_end_s, self.roi)


@dataclass
class SessionExport:
    """A loaded session: the JSON summary (if any) plus its readings."""

    source: str
    readings: list[Reading]
    summary: dict[str, Any] | None
    findings: list[InputFinding] = field(default_factory=list)
    synthetic: bool = False

    @property
    def session_id(self) -> str | None:
        if not self.summary:
            return None
        value = self.summary.get("capture_session_id")
        return str(value) if value else None

    def primary(self) -> list[Reading]:
        """The agreement-checked consensus series — the one the app headlines.

        Per-estimator rows (green/pos/chrom) are diagnostics in the application and
        stay diagnostics here. Counting them as extra observations would inflate
        every statistic.
        """
        return [r for r in self.readings if r.algorithm == CONSENSUS]

    def by_series(self) -> dict[tuple[str, str], list[Reading]]:
        series: dict[tuple[str, str], list[Reading]] = {}
        for reading in self.readings:
            series.setdefault((reading.algorithm, reading.roi), []).append(reading)
        return dict(sorted(series.items()))

    @property
    def acqusition(self) -> dict[str, Any]:
        return (self.summary or {}).get("acquisition") or {}


# --- primitive parsing helpers -----------------------------------------------


def _parse_float(text: str | None, *, field: str, row: int, findings: list[InputFinding],
                 source: str) -> float | None:
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        findings.append(InputFinding(
            REJECT, "unparseable_number", f"{field} is not a number: {text!r}",
            source=source, field_name=field, row=row))
        return None
    if not math.isfinite(value):
        findings.append(InputFinding(
            REJECT, "non_finite_number", f"{field} is not finite: {text!r}",
            source=source, field_name=field, row=row))
        return None
    return value


def _parse_int(text: str | None, *, field: str, row: int, findings: list[InputFinding],
               source: str) -> int | None:
    if text is None or text == "":
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        findings.append(InputFinding(
            REJECT, "unparseable_integer", f"{field} is not an integer: {text!r}",
            source=source, field_name=field, row=row))
        return None


def _parse_bool(text: str | None) -> bool | None:
    if text is None or text == "":
        return None
    lowered = text.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _is_iso_utc(text: str) -> bool:
    """Accept only the ISO-8601 UTC form the exporter writes.

    Deliberately strict: a local-time string in a UTC column would shift a whole
    session silently if we guessed at it.
    """
    if not text or "T" not in text:
        return False
    if not (text.endswith("Z") or text.endswith("+00:00")):
        return False
    try:
        from datetime import datetime
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


# --- CSV --------------------------------------------------------------------


def _detect_synthetic(text: str) -> bool:
    lowered = text.lower()
    return "synthetic" in lowered or "rsbvp_synthetic" in lowered or "fixture" in lowered


def load_session_csv(path: str | Path | io.TextIOBase, *,
                     source_name: str | None = None) -> tuple[list[Reading], list[InputFinding], bool]:
    """Parse a readings CSV into readings plus findings.

    Returns ``(readings, findings, synthetic)``. Raises :class:`InputRejection`
    only when the file cannot be read as CSV at all or lacks required columns —
    per-row problems are findings so the researcher sees all of them at once.
    """
    if hasattr(path, "read"):
        text = path.read()  # type: ignore[union-attr]
        name = source_name or "<stream>"
    else:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputRejection([
                InputFinding(REJECT, "unreadable_file", f"cannot read {p}: {exc}", source=str(p))
            ]) from exc
        name = source_name or p.name

    synthetic = _detect_synthetic(name)
    findings: list[InputFinding] = []
    if not text.strip():
        raise InputRejection([
            InputFinding(REJECT, "empty_file", "the readings CSV is empty", source=name)
        ])

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise InputRejection([
            InputFinding(REJECT, "no_header", "the readings CSV has no header row", source=name)
        ])
    columns = {c.strip() for c in reader.fieldnames if c}
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in columns]
    if missing:
        raise InputRejection([
            InputFinding(REJECT, "missing_columns",
                         f"required column(s) absent from the readings CSV: {', '.join(missing)}. "
                         "Re-export from RSBVP (Export readings (CSV)); do not add columns by hand.",
                         source=name, field_name=missing[0])
        ])
    for column in OPTIONAL_CSV_COLUMNS:
        if column not in columns:
            findings.append(InputFinding(
                WARN, "optional_column_absent",
                f"optional column {column!r} absent; affected statistics will be reported as unavailable",
                source=name, field_name=column))

    readings: list[Reading] = []
    seen_keys: set[str] = set()
    seen_ids: dict[int, int] = {}
    bad_rows = 0

    for index, raw in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip(): (v if isinstance(v, str) else "") for k, v in raw.items() if k}
        if not any(v.strip() for v in row.values()):
            continue  # a blank line is not a record

        reading_id = _parse_int(row.get("reading_id"), field="reading_id", row=index,
                                findings=findings, source=name)
        metric = (row.get("metric") or "").strip()
        algorithm = (row.get("algorithm") or "").strip()
        roi = (row.get("roi") or "").strip()

        if reading_id is None or not metric or not algorithm or not roi:
            bad_rows += 1
            if not metric:
                findings.append(InputFinding(REJECT, "missing_metric", "row has no metric",
                                             source=name, row=index, field_name="metric"))
            if not algorithm:
                findings.append(InputFinding(REJECT, "missing_algorithm", "row has no algorithm",
                                             source=name, row=index, field_name="algorithm"))
            if not roi:
                findings.append(InputFinding(REJECT, "missing_roi", "row has no ROI",
                                             source=name, row=index, field_name="roi"))
            continue

        raw_value = (row.get("value") or "").strip()
        value = _parse_float(raw_value, field="value", row=index, findings=findings, source=name)
        value_error = "unparseable" if raw_value and value is None else None

        start = _parse_float(row.get("window_start_s"), field="window_start_s", row=index,
                             findings=findings, source=name)
        end = _parse_float(row.get("window_end_s"), field="window_end_s", row=index,
                           findings=findings, source=name)
        if start is not None and end is not None and end <= start:
            findings.append(InputFinding(
                REJECT, "invalid_window_bounds",
                f"window_end_s ({end}) is not after window_start_s ({start})",
                source=name, row=index))

        recorded = (row.get("recorded_utc") or "").strip()
        if not _is_iso_utc(recorded):
            findings.append(InputFinding(
                REJECT, "invalid_timestamp",
                f"recorded_utc is not an ISO-8601 UTC timestamp: {recorded!r}",
                source=name, row=index, field_name="recorded_utc"))

        accepted_flag = _parse_bool(row.get("accepted"))
        if accepted_flag is None:
            findings.append(InputFinding(
                REJECT, "invalid_accepted_flag",
                f"accepted is not a boolean: {row.get('accepted')!r}",
                source=name, row=index, field_name="accepted"))
            accepted_flag = False

        verdict = (row.get("quality_verdict") or "").strip() or "unknown"
        reason = (row.get("rejection_reason") or "").strip() or None

        if reading_id in seen_ids:
            findings.append(InputFinding(
                REJECT, "duplicate_reading_id",
                f"reading_id {reading_id} also appears at row {seen_ids[reading_id]}",
                source=name, row=index, field_name="reading_id"))
        else:
            seen_ids[reading_id] = index

        key = window_key(metric, algorithm, start, end, roi)
        naive_dup = key is not None and key in seen_keys
        if key is not None:
            seen_keys.add(key)

        verdict_class = classify_reading(
            metric=metric, value=value, quality_verdict=verdict,
            rejection_reason=reason, naive_dup=naive_dup)

        # The file's own decision and our re-derivation must agree. A disagreement
        # means the file was produced by different rules than the ones being
        # evaluated — which invalidates the comparison rather than being a detail.
        if verdict_class.accepted != accepted_flag:
            findings.append(InputFinding(
                REJECT, "acceptance_mismatch",
                f"row {index}: file says accepted={accepted_flag} but the shared rules give "
                f"{verdict_class.accepted} ({verdict_class.reason or 'no reason'}). The export "
                "was produced by different rules than this evaluation applies.",
                source=name, row=index))

        readings.append(Reading(
            reading_id=reading_id,
            metric=metric,
            value=value,
            algorithm=algorithm,
            roi=roi,
            accepted_in_file=accepted_flag,
            quality_verdict=verdict,
            rejection_reason=reason,
            quality_score=_parse_float(row.get("quality_score"), field="quality_score",
                                       row=index, findings=findings, source=name),
            fs_hz=_parse_float(row.get("sampling_rate_hz"), field="sampling_rate_hz",
                               row=index, findings=findings, source=name),
            n_samples=_parse_int(row.get("n_samples"), field="n_samples", row=index,
                                 findings=findings, source=name),
            window_start_s=start,
            window_end_s=end,
            session_elapsed_s=_parse_float(row.get("session_elapsed_s"),
                                           field="session_elapsed_s", row=index,
                                           findings=findings, source=name),
            window_index=_parse_int(row.get("window_index"), field="window_index", row=index,
                                    findings=findings, source=name),
            recorded_utc=recorded,
            unit=(row.get("unit") or "").strip() or None,
            value_parse_error=value_error,
            row_number=index,
            accepted_recomputed=verdict_class.accepted,
            recomputed_reason=verdict_class.reason,
        ))

    if not readings and bad_rows == 0:
        findings.append(InputFinding(REJECT, "no_readings", "the readings CSV contains no records",
                                     source=name))
    return readings, findings, synthetic


# --- JSON -------------------------------------------------------------------


def load_session_json(path: str | Path | io.TextIOBase, *,
                      source_name: str | None = None) -> tuple[dict[str, Any], list[InputFinding], bool]:
    """Parse a session summary JSON. Structure and schema tag are enforced."""
    if hasattr(path, "read"):
        text = path.read()  # type: ignore[union-attr]
        name = source_name or "<stream>"
    else:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputRejection([
                InputFinding(REJECT, "unreadable_file", f"cannot read {p}: {exc}", source=str(p))
            ]) from exc
        name = source_name or p.name

    synthetic = _detect_synthetic(name)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputRejection([
            InputFinding(REJECT, "invalid_json", f"not valid JSON: {exc}", source=name)
        ]) from exc
    if not isinstance(payload, dict):
        raise InputRejection([
            InputFinding(REJECT, "invalid_json_root", "the session JSON root is not an object",
                         source=name)
        ])

    findings: list[InputFinding] = []
    schema = payload.get("schema")
    if schema != SESSION_SCHEMA:
        raise InputRejection([
            InputFinding(REJECT, "unknown_schema",
                         f"schema is {schema!r}; this platform reads {SESSION_SCHEMA!r}. "
                         "A different major version cannot be assumed readable.",
                         source=name, field_name="schema")
        ])

    if payload.get("frames_images_included") not in (False, None):
        findings.append(InputFinding(
            REJECT, "frames_present",
            "the export claims to include camera frames; exports must never contain imagery",
            source=name, field_name="frames_images_included"))

    acquisition = payload.get("acquisition")
    if not isinstance(acquisition, dict):
        findings.append(InputFinding(
            WARN, "missing_acquisition",
            "no acquisition block: algorithm/ROI provenance and camera metadata are unavailable",
            source=name, field_name="acquisition"))

    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        findings.append(InputFinding(
            WARN, "missing_metrics",
            "no metrics block: the session's own aggregate cannot be cross-checked",
            source=name, field_name="metrics"))
    else:
        hr = next((m for m in metrics if isinstance(m, dict) and m.get("metric") == "heart_rate"), None)
        if hr is None:
            findings.append(InputFinding(
                WARN, "no_heart_rate_aggregate",
                "the summary carries no heart-rate aggregate; the session average is unavailable",
                source=name))
        else:
            n_acc = hr.get("accepted_readings")
            if not isinstance(n_acc, int):
                findings.append(InputFinding(
                    WARN, "aggregate_count_missing",
                    "heart-rate aggregate has no integer accepted_readings count",
                    source=name, field_name="metrics.accepted_readings"))

    # An experimental metric in the headline block would be a contract violation.
    for block in metrics or []:
        if not isinstance(block, dict):
            continue
        if block.get("metric") != "heart_rate" and block.get("primary") is True:
            findings.append(InputFinding(
                REJECT, "experimental_metric_primary",
                f"{block.get('metric')!r} is marked primary; only heart rate may headline a result",
                source=name))
    return payload, findings, synthetic


# --- bundle -----------------------------------------------------------------


@dataclass
class LoadedSession:
    """Whatever combination of files the researcher supplied, plus its findings."""

    export: SessionExport
    findings: list[InputFinding]

    @property
    def worst(self) -> Severity:
        return worst_severity(self.findings)

    def raise_if_rejected(self) -> None:
        if self.worst is REJECT:
            raise InputRejection(self.findings)


def load_session_bundle(
    *,
    readings_csv: str | Path | io.TextIOBase | None = None,
    summary_json: str | Path | io.TextIOBase | None = None,
) -> LoadedSession:
    """Load one session from the files that exist.

    A readings CSV alone is sufficient: every statistic the platform computes can
    be derived from it. The JSON summary is used when present, to cross-check the
    session's own aggregate, but its absence is a warning rather than a blocker.
    """
    if readings_csv is None and summary_json is None:
        raise InputRejection([
            InputFinding(REJECT, "no_input", "supply at least a readings CSV or a session JSON")
        ])

    findings: list[InputFinding] = []
    readings: list[Reading] = []
    summary: dict[str, Any] | None = None
    synthetic = False
    sources: list[str] = []

    if summary_json is not None:
        summary, json_findings, json_synthetic = load_session_json(summary_json)
        findings.extend(json_findings)
        synthetic = synthetic or json_synthetic
        sources.append(str(summary_json if not hasattr(summary_json, "read") else "<summary stream>"))

    if readings_csv is not None:
        readings, csv_findings, csv_synthetic = load_session_csv(readings_csv)
        findings.extend(csv_findings)
        synthetic = synthetic or csv_synthetic
        sources.append(str(readings_csv if not hasattr(readings_csv, "read") else "<readings stream>"))
    else:
        findings.append(InputFinding(
            WARN, "no_readings_csv",
            "no readings CSV supplied: window-level evaluation and per-algorithm/ROI comparison "
            "are unavailable. The session JSON carries aggregates only, not individual readings.",
            source=str(summary_json)))

    if not readings and summary is None:
        findings.append(InputFinding(REJECT, "no_usable_input", "no readable input was supplied"))

    # Session-level checks that need the readings.
    if readings:
        primary = [r for r in readings if r.algorithm == CONSENSUS]
        if not primary:
            findings.append(InputFinding(
                REJECT, "no_consensus_series",
                "no consensus-series readings: the export carries only per-estimator rows, so the "
                "session result the application displayed cannot be reconstructed",
                source=sources[-1] if sources else ""))
        unknown_metric = sorted({r.metric for r in readings} - set(EVALUABLE_METRICS))
        if unknown_metric:
            findings.append(InputFinding(
                WARN, "non_evaluable_metric",
                f"metric(s) present but not evaluated here: {', '.join(unknown_metric)}. "
                "Aggregating an experimental metric into heart-rate statistics would be invalid.",
                source=sources[-1] if sources else ""))
        no_value = sum(1 for r in readings if r.value is None)
        if no_value == len(readings):
            findings.append(InputFinding(
                REJECT, "no_values",
                "every reading has an empty value: there is nothing to compare with a reference",
                source=sources[-1] if sources else ""))

    export = SessionExport(
        source=" + ".join(s for s in sources if s) or "<none>",
        readings=readings,
        summary=summary,
        findings=findings,
        synthetic=synthetic,
    )
    return LoadedSession(export=export, findings=findings)
