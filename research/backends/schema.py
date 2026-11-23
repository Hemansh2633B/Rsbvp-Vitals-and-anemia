"""Standardized output schema for the RSBVP research benchmark adapter.

One :class:`BenchmarkRecord` describes one algorithm applied to one window of
one recording of one ROI. Missing values are preserved as ``None`` (JSON
``null`` / CSV empty cell) — they are never coerced to zero. Samples are never
fabricated: a backend that cannot produce a waveform emits ``pulse_signal =
None`` and (usually) ``estimated_hr_bpm = None`` with an explanatory
``signal_quality`` token.

CSV export contains one row per record (waveforms excluded); full-fidelity
per-sample waveforms are written separately by :func:`write_waveforms_csv`.
JSON export is the canonical, lossless format.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Sequence

BACKEND_RECORD_SCHEMA_VERSION = "rsbvp.benchmark-record.v1"

_RECORD_CSV_COLUMNS = [
    "schema_version",
    "recording_id",
    "participant_id",
    "timestamp_s",
    "window_end_s",
    "algorithm",
    "roi",
    "estimated_hr_bpm",
    "signal_quality",
    "sampling_rate_hz",
    "backend",
    "backend_version",
    "model_checkpoint",
    "configuration_hash",
    "backend_output_type",
    "pulse_signal_length",
]

_WAVEFORM_CSV_COLUMNS = [
    "schema_version",
    "recording_id",
    "algorithm",
    "roi",
    "sample_index",
    "timestamp_s",
    "pulse_signal",
]

_ALLOWED_OUTPUT_TYPES = {"window", "aggregate"}
_QUALITY_TOKEN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")


class SchemaError(ValueError):
    """Raised when a record fails schema validation."""


def _clean_optional_float(value, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{field_name} must be a number or null, got {value!r}") from exc
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _clean_pulse_signal(pulse_signal):
    if pulse_signal is None:
        return None
    if isinstance(pulse_signal, (str, bytes)):
        raise SchemaError("pulse_signal must be a list of numbers/nulls or null, not a string")
    cleaned: list[float | None] = []
    for entry in pulse_signal:
        cleaned.append(_clean_optional_float(entry, "pulse_signal entry"))
    return cleaned


@dataclass
class BenchmarkRecord:
    """One standardized benchmark record (see docs/RESEARCH_BACKENDS.md)."""

    recording_id: str
    timestamp_s: float
    algorithm: str
    roi: str
    pulse_signal: list[float | None] | None
    estimated_hr_bpm: float | None
    signal_quality: str
    sampling_rate_hz: float | None
    backend: str
    backend_version: str
    model_checkpoint: str | None
    configuration_hash: str
    window_end_s: float | None = None
    participant_id: str | None = None
    backend_output_type: str = "window"
    schema_version: str = BACKEND_RECORD_SCHEMA_VERSION
    backend_report: dict | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        self.pulse_signal = _clean_pulse_signal(self.pulse_signal)
        self.estimated_hr_bpm = _clean_optional_float(self.estimated_hr_bpm, "estimated_hr_bpm")
        self.sampling_rate_hz = _clean_optional_float(self.sampling_rate_hz, "sampling_rate_hz")
        self.timestamp_s = _clean_optional_float(self.timestamp_s, "timestamp_s")  # type: ignore[assignment]
        self.window_end_s = _clean_optional_float(self.window_end_s, "window_end_s")
        validate_record(self)

    # ------------------------------------------------------------------
    def to_dict(self, include_waveform: bool = True) -> dict:
        data = asdict(self)
        if not include_waveform:
            data.pop("pulse_signal", None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        unknown = sorted(set(data) - known)
        if unknown:
            # Unknown keys are rejected rather than silently dropped so a
            # typo in a producer cannot masquerade as a valid record.
            raise SchemaError(f"unknown record keys: {', '.join(unknown)}")
        return cls(**kwargs)


@dataclass(frozen=True)
class BenchmarkWaveformSample:
    """One sample of a predicted pulse waveform (CSV waveform export)."""

    recording_id: str
    algorithm: str
    roi: str
    sample_index: int
    timestamp_s: float
    pulse_signal: float | None
    schema_version: str = BACKEND_RECORD_SCHEMA_VERSION


def validate_record(record: BenchmarkRecord) -> BenchmarkRecord:
    """Validate a record, raising :class:`SchemaError` on any violation."""
    if not isinstance(record, BenchmarkRecord):
        raise SchemaError(f"expected BenchmarkRecord, got {type(record).__name__}")
    for field_name in ("recording_id", "algorithm", "roi", "signal_quality",
                       "backend", "backend_version", "configuration_hash"):
        value = getattr(record, field_name)
        if not isinstance(value, str) or not value.strip():
            raise SchemaError(f"{field_name} must be a non-empty string")
    for field_name in ("recording_id", "algorithm", "roi", "signal_quality",
                       "backend", "backend_version"):
        value = getattr(record, field_name)
        if any(ch not in _QUALITY_TOKEN_CHARS | set(" ") for ch in value):
            raise SchemaError(f"{field_name} contains unsupported characters: {value!r}")
    if record.timestamp_s is None or not math.isfinite(record.timestamp_s):
        raise SchemaError("timestamp_s must be a finite number (NaN/inf are not allowed)")
    if record.window_end_s is not None and record.window_end_s < record.timestamp_s:
        raise SchemaError("window_end_s must not precede timestamp_s")
    if record.sampling_rate_hz is not None and record.sampling_rate_hz <= 0:
        raise SchemaError("sampling_rate_hz must be positive when present")
    if record.estimated_hr_bpm is not None and not (0 < record.estimated_hr_bpm < 400):
        raise SchemaError("estimated_hr_bpm must be within (0, 400) BPM when present")
    if record.backend_output_type not in _ALLOWED_OUTPUT_TYPES:
        raise SchemaError(f"backend_output_type must be one of {sorted(_ALLOWED_OUTPUT_TYPES)}")
    if record.schema_version != BACKEND_RECORD_SCHEMA_VERSION:
        raise SchemaError(f"schema_version must be {BACKEND_RECORD_SCHEMA_VERSION!r}")
    config_hash = record.configuration_hash.strip().lower()
    if len(config_hash) != 64 or any(c not in "0123456789abcdef" for c in config_hash):
        raise SchemaError("configuration_hash must be a 64-character sha256 hex digest")
    if record.pulse_signal is not None:
        for entry in record.pulse_signal:
            if entry is not None and not math.isfinite(entry):
                raise SchemaError("pulse_signal entries must be finite numbers or null")
    return record


# ----------------------------------------------------------------------
# Serialization helpers
# ----------------------------------------------------------------------

def records_to_json(records: Sequence[BenchmarkRecord]) -> str:
    payload = {
        "schema_version": BACKEND_RECORD_SCHEMA_VERSION,
        "record_count": len(records),
        "records": [r.to_dict(include_waveform=True) for r in records],
    }
    return json.dumps(payload, indent=2, sort_keys=False, allow_nan=False) + "\n"


def records_from_json(text: str) -> list[BenchmarkRecord]:
    def _reject_constant(value):
        raise SchemaError(f"non-standard JSON constant {value!r} is not allowed; missing values must be null")
    try:
        payload = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON payload: {exc}") from exc
    if isinstance(payload, dict):
        version = payload.get("schema_version")
        if version != BACKEND_RECORD_SCHEMA_VERSION:
            raise SchemaError(f"unsupported schema_version: {version!r}")
        raw_records = payload.get("records")
    elif isinstance(payload, list):
        raw_records = payload
    else:
        raise SchemaError("JSON payload must be an object or a list of records")
    if not isinstance(raw_records, list):
        raise SchemaError("JSON payload 'records' must be a list")
    return [BenchmarkRecord.from_dict(dict(item)) for item in raw_records]


def read_records_json(path: str | Path) -> list[BenchmarkRecord]:
    return records_from_json(Path(path).read_text(encoding="utf-8"))


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10g}"


def records_to_csv_rows(records: Sequence[BenchmarkRecord]):
    for record in records:
        yield {
            "schema_version": record.schema_version,
            "recording_id": record.recording_id,
            "participant_id": record.participant_id or "",
            "timestamp_s": _fmt_optional(record.timestamp_s),
            "window_end_s": _fmt_optional(record.window_end_s),
            "algorithm": record.algorithm,
            "roi": record.roi,
            "estimated_hr_bpm": _fmt_optional(record.estimated_hr_bpm),
            "signal_quality": record.signal_quality,
            "sampling_rate_hz": _fmt_optional(record.sampling_rate_hz),
            "backend": record.backend,
            "backend_version": record.backend_version,
            "model_checkpoint": record.model_checkpoint or "",
            "configuration_hash": record.configuration_hash,
            "backend_output_type": record.backend_output_type,
            "pulse_signal_length": "" if record.pulse_signal is None else str(len(record.pulse_signal)),
        }


def waveform_samples_to_csv_rows(records: Iterable[BenchmarkRecord]):
    for record in records:
        if record.pulse_signal is None:
            continue
        fs = record.sampling_rate_hz
        for index, value in enumerate(record.pulse_signal):
            if fs:
                timestamp = record.timestamp_s + index / fs
            else:
                timestamp = record.timestamp_s
            yield {
                "schema_version": record.schema_version,
                "recording_id": record.recording_id,
                "algorithm": record.algorithm,
                "roi": record.roi,
                "sample_index": str(index),
                "timestamp_s": _fmt_optional(timestamp),
                "pulse_signal": _fmt_optional(value),
            }


def write_records_csv(records: Sequence[BenchmarkRecord], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_RECORD_CSV_COLUMNS)
        writer.writeheader()
        for row in records_to_csv_rows(records):
            writer.writerow(row)
    return path


def write_waveforms_csv(records: Sequence[BenchmarkRecord], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_WAVEFORM_CSV_COLUMNS)
        writer.writeheader()
        for row in waveform_samples_to_csv_rows(records):
            writer.writerow(row)
    return path


def write_records_json(records: Sequence[BenchmarkRecord], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(records_to_json(records), encoding="utf-8")
    return path


def read_records_csv(path: str | Path) -> list[BenchmarkRecord]:
    """Read a records CSV back. Waveforms are not embedded in CSV exports;
    reconstituted records therefore carry ``pulse_signal=None``."""
    records: list[BenchmarkRecord] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = set(_RECORD_CSV_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise SchemaError(f"records CSV missing columns: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            def opt(name):
                raw = (row.get(name) or "").strip()
                return None if raw == "" else float(raw)
            try:
                record = BenchmarkRecord(
                    schema_version=row["schema_version"],
                    recording_id=row["recording_id"],
                    participant_id=(row.get("participant_id") or "").strip() or None,
                    timestamp_s=float(row["timestamp_s"]),
                    window_end_s=opt("window_end_s"),
                    algorithm=row["algorithm"],
                    roi=row["roi"],
                    pulse_signal=None,
                    estimated_hr_bpm=opt("estimated_hr_bpm"),
                    signal_quality=row["signal_quality"],
                    sampling_rate_hz=opt("sampling_rate_hz"),
                    backend=row["backend"],
                    backend_version=row["backend_version"],
                    model_checkpoint=(row.get("model_checkpoint") or "").strip() or None,
                    configuration_hash=row["configuration_hash"],
                    backend_output_type=row["backend_output_type"],
                )
            except (ValueError, SchemaError) as exc:
                raise SchemaError(f"records CSV line {line}: {exc}") from exc
            records.append(record)
    return records
