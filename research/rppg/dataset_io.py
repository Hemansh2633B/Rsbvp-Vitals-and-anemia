"""Local-only explicit dataset intake and modality-aware reference processing.

No network access, provider filename assumptions, or dataset uploads. CSV/HDF5
paths and signal keys are taken only from a verified local manifest.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.signal import butter, periodogram, sosfiltfilt

MANIFEST_REQUIRED = {
    "dataset", "dataset_version", "participant_id", "recording_id",
    "trace_csv", "reference_path", "reference_format", "reference_type",
    "time_offset_s", "source_citation", "license_verified",
}
REFERENCE_TYPES = {"ppg", "bvp", "ecg"}


@dataclass(frozen=True)
class ReferenceSignal:
    timestamps_s: np.ndarray  # mapped onto the trace clock after explicit offset
    values: np.ndarray
    sampling_hz: float  # provider-declared original rate or estimated median rate
    signal_type: str
    offset_s: float
    timestamp_median_interval_s: float
    timestamp_jitter_fraction: float
    sampling_rate_source: str = "estimated_from_timestamps"


def data_root(cli_root: str | Path | None = None) -> Path:
    """Choose CLI root, then RSBVP_DATA_ROOT; reject implicit machine paths."""
    raw = cli_root if cli_root is not None else os.environ.get("RSBVP_DATA_ROOT")
    if not raw:
        raise ValueError("Set RSBVP_DATA_ROOT or pass --data-root; no implicit dataset path is used")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root does not exist or is not a directory: {root}")
    return root


def _local_path(root: Path, value: str) -> Path:
    p = Path(value)
    p = (root / p).resolve() if not p.is_absolute() else p.resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError("Input path escapes configured data root")
    return p


def read_manifest(path: str | Path, root: str | Path) -> list[dict[str, str]]:
    path, root = Path(path), Path(root).resolve()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or ())
        missing = MANIFEST_REQUIRED - fields
        if missing:
            raise ValueError(f"Manifest missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("Manifest has no recordings")
    seen: set[tuple[str, str]] = set()
    for line, row in enumerate(rows, 2):
        for key in MANIFEST_REQUIRED:
            if not (row.get(key) or "").strip():
                raise ValueError(f"Manifest row {line}: {key} is required")
        if row["reference_type"].lower() not in REFERENCE_TYPES:
            raise ValueError(f"Manifest row {line}: reference_type must be ppg, bvp, or ecg")
        if row["license_verified"].lower() not in {"true", "false"}:
            raise ValueError(f"Manifest row {line}: license_verified must be true/false")
        if row["license_verified"].lower() != "true":
            raise ValueError(f"Manifest row {line}: terms/license must be verified before processing")
        key = (row["dataset"], row["recording_id"])
        if key in seen:
            raise ValueError(f"Manifest row {line}: duplicate dataset/recording_id")
        seen.add(key)
        for field in ("trace_csv", "reference_path"):
            target = _local_path(root, row[field])
            if not target.is_file():
                raise FileNotFoundError(f"Manifest row {line}: missing {field}: {target}")
        fmt = row["reference_format"].lower()
        if fmt not in {"csv", "hdf5"}:
            raise ValueError(f"Manifest row {line}: reference_format must be csv or hdf5")
        if fmt == "csv" and not (row.get("reference_signal_column") or "").strip():
            raise ValueError(f"Manifest row {line}: CSV requires reference_signal_column")
        if fmt == "hdf5" and not (row.get("reference_dataset_path") or "").strip():
            raise ValueError(f"Manifest row {line}: HDF5 requires explicit reference_dataset_path")
        try:
            offset = float(row["time_offset_s"])
            fsraw = (row.get("reference_fs_hz") or "").strip()
            declared_fs = float(fsraw) if fsraw else None
        except ValueError as exc:
            raise ValueError(f"Manifest row {line}: invalid numeric offset or sampling rate") from exc
        if not np.isfinite(offset):
            raise ValueError(f"Manifest row {line}: time_offset_s must be finite")
        if declared_fs is not None and (not np.isfinite(declared_fs) or declared_fs <= 0):
            raise ValueError(f"Manifest row {line}: reference_fs_hz must be positive")
        if not declared_fs and not (row.get("reference_time_column") or "").strip():
            raise ValueError(f"Manifest row {line}: provide reference_fs_hz or reference_time_column")
        if fmt == "hdf5" and not declared_fs:
            raise ValueError(f"Manifest row {line}: HDF5 sample-index timestamps require verified reference_fs_hz")
    return rows


def _number_or_nan(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else np.nan
    except (ValueError, TypeError):
        return np.nan


def _timestamp_stats(times: np.ndarray) -> tuple[float, float]:
    if times.ndim != 1 or len(times) < 3 or not np.isfinite(times).all():
        raise ValueError("Reference timestamps must contain at least three finite values")
    intervals = np.diff(times)
    if np.any(intervals <= 0):
        raise ValueError("Reference timestamps must be strictly increasing; duplicates/reordering are invalid")
    median_interval = float(np.median(intervals))
    # Robust MAD-based relative jitter; isolated dropped frames are detected
    # separately by maximum-gap checks rather than distorting the jitter score.
    jitter = float(np.median(np.abs(intervals - median_interval)) / median_interval)
    return median_interval, jitter


def load_reference(row: dict[str, str], root: str | Path) -> ReferenceSignal:
    """Load one timestamped CSV or explicitly keyed HDF5 reference waveform.

    An explicitly mapped time column takes precedence for sample times. If no
    time column exists, sample-index timing uses a provider-verified rate. CSV
    blank/malformed signal values become NaN and invalidate their analysis
    window; timestamps are never repaired. HDF5 timestamp keys are not guessed.
    """
    root = Path(root).resolve()
    if (row.get("license_verified") or "").lower() != "true":
        raise ValueError("Dataset terms/license must be explicitly verified before reference processing")
    path = _local_path(root, row["reference_path"])
    fmt = row["reference_format"].lower()
    fsraw = (row.get("reference_fs_hz") or "").strip()
    declared_fs = float(fsraw) if fsraw else None
    time_column = (row.get("reference_time_column") or "").strip()
    if fmt == "csv":
        signal_column = (row.get("reference_signal_column") or "").strip()
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if signal_column not in (reader.fieldnames or ()):
                raise ValueError(f"Reference signal column {signal_column!r} not found")
            if time_column and time_column not in (reader.fieldnames or ()):
                raise ValueError(f"Reference time column {time_column!r} not found")
            raw = list(reader)
        vals = np.array([_number_or_nan(r.get(signal_column)) for r in raw], dtype=float)
        if time_column:
            times = np.array([_number_or_nan(r.get(time_column)) for r in raw], dtype=float)
        elif declared_fs:
            times = np.arange(len(vals), dtype=float) / declared_fs
        else:
            raise ValueError("Reference CSV needs timestamps or a verified reference_fs_hz")
    elif fmt == "hdf5":
        key = (row.get("reference_dataset_path") or "").strip()
        if not key:
            raise ValueError("HDF5 requires explicit reference_dataset_path after archive inspection")
        if time_column:
            raise ValueError("HDF5 timestamp datasets are not guessed; normalize documented timestamps to CSV")
        if not declared_fs:
            raise ValueError("HDF5 reference requires verified reference_fs_hz")
        try:
            import h5py  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install h5py to read the explicitly configured HDF5 signal") from exc
        with h5py.File(path, "r") as f:
            if key not in f:
                raise ValueError(f"Configured HDF5 dataset path {key!r} not found")
            vals = np.asarray(f[key][()], dtype=float)
        if vals.ndim != 1:
            raise ValueError(f"Configured HDF5 signal {key!r} must be one-dimensional")
        times = np.arange(len(vals), dtype=float) / declared_fs
    else:
        raise ValueError(f"Unsupported reference format: {fmt}")
    if vals.ndim != 1 or len(vals) != len(times) or len(vals) < 3:
        raise ValueError("Reference must contain at least three aligned samples")
    median_interval, jitter = _timestamp_stats(times)
    measured_fs = 1 / median_interval
    original_fs = declared_fs or measured_fs
    return ReferenceSignal(times + float(row["time_offset_s"]), vals, float(original_fs),
                           row["reference_type"].lower(), float(row["time_offset_s"]),
                           median_interval, jitter,
                           "provider_declared" if declared_fs is not None else "estimated_from_timestamp_median")


def reference_hr_windows(reference: ReferenceSignal, starts_s: Iterable[float], *,
                         window_seconds: float = 12.0, step_seconds: float = 6.0,
                         min_hz: float = 0.7, max_hz: float = 3.5,
                         max_gap_seconds: float = 0.25,
                         max_jitter_fraction: float = 0.05,
                         min_peak_fraction: float = 0.05) -> list[dict[str, object]]:
    """Estimate per-window PPG/BVP pulse frequency; ECG is explicitly unsupported.

    Acceptable timestamp jitter is regularized by linear interpolation over a
    uniform grid at the measured median sampling frequency, only after coverage,
    jitter, value and max-gap checks pass. Butterworth SOS bandpass plus Hann
    periodogram is used for pulse waveform frequency. ECG is rejected: no
    validated R-peak detector exists in this project, so FFT-derived ECG HR is
    intentionally not reported.
    """
    if not 0 < min_hz < max_hz:
        raise ValueError("Pulse passband must be positive and ordered")
    if window_seconds <= 0 or step_seconds <= 0 or max_gap_seconds <= 0 or max_jitter_fraction < 0:
        raise ValueError("Window, step and gap must be positive; jitter tolerance cannot be negative")
    t, x = np.asarray(reference.timestamps_s, float), np.asarray(reference.values, float)
    _timestamp_stats(t)
    out: list[dict[str, object]] = []
    for start in starts_s:
        start = float(start); stop = start + window_seconds
        idx = np.flatnonzero((t >= start) & (t < stop))
        tt, xx = t[idx], x[idx]
        reason: str | None = None
        bpm: float | None = None
        effective_fs: float | None = None
        jitter = None
        max_interval = None
        peak_fraction = None
        measured_fs = None
        if reference.signal_type == "ecg":
            reason = "ecg_rpeak_estimator_unavailable"
        elif reference.signal_type not in {"ppg", "bvp"}:
            reason = "unsupported_reference_signal_type"
        elif len(idx) < 3:
            reason = "insufficient_reference_samples"
        else:
            try:
                dt, jitter = _timestamp_stats(tt)
                measured_fs = 1 / dt
                intervals = np.diff(tt); max_interval = float(np.max(intervals))
            except ValueError:
                reason = "invalid_reference_timestamps"
            if reason is None:
                # Require complete temporal overlap with this trace window (allow
                # at most one source sample of endpoint quantization).
                if tt[0] - start > 1.5 / measured_fs:
                    reason = "reference_does_not_cover_window_start"
                elif stop - tt[-1] > 1.5 / measured_fs:
                    reason = "reference_does_not_cover_window_end"
                elif max_interval > max_gap_seconds:
                    reason = "reference_gap_exceeds_limit"
                elif jitter > max_jitter_fraction:
                    reason = "timestamp_jitter_exceeds_tolerance"
                elif not np.isfinite(xx).all():
                    reason = "missing_or_malformed_reference_samples"
                elif measured_fs <= 2 * max_hz:
                    reason = "reference_nyquist_below_passband"
                elif not np.isfinite(xx).all() or np.ptp(xx) <= 1e-10:
                    reason = "reference_signal_flat_or_invalid"
            if reason is None:
                # Linear resampling only over this fully covered, gap-checked window.
                grid = np.arange(start, stop, 1 / measured_fs)
                if len(grid) < max(8, int(window_seconds * 2 * min_hz)):
                    reason = "insufficient_effective_samples"
                else:
                    y = np.interp(grid, tt, xx)
                    effective_fs = 1 / float(np.median(np.diff(grid)))
                    try:
                        sos = butter(3, [min_hz, max_hz], btype="bandpass", fs=effective_fs, output="sos")
                        filtered = sosfiltfilt(sos, y)
                        if not np.isfinite(filtered).all() or np.std(filtered) <= 1e-10:
                            reason = "reference_signal_quality_failure"
                        else:
                            freq, power = periodogram(filtered, fs=effective_fs, window="hann", detrend="constant")
                            band = (freq >= min_hz) & (freq <= max_hz)
                            total = float(np.sum(power[band]))
                            peak_fraction = float(np.max(power[band]) / total) if band.any() and total > 0 else 0.0
                            if not band.any() or not np.isfinite(power[band]).all() or total <= 0 or peak_fraction < min_peak_fraction:
                                reason = "reference_spectral_quality_failure"
                            else:
                                bpm = float(freq[band][np.argmax(power[band])] * 60)
                    except ValueError:
                        reason = "reference_filter_failed"
        out.append({"start_s": start, "end_s": stop, "reference_hr_bpm": bpm,
                    "valid": bpm is not None, "rejection_reason": reason,
                    "reference_type": reference.signal_type,
                    "original_sampling_hz": reference.sampling_hz,
                    "original_sampling_hz_source": reference.sampling_rate_source,
                    "measured_sampling_hz": measured_fs,
                    "effective_sampling_hz": effective_fs,
                    "timestamp_median_interval_s": 1 / measured_fs if measured_fs else reference.timestamp_median_interval_s,
                    "timestamp_jitter_fraction": jitter,
                    "max_observed_interval_s": max_interval,
                    "spectral_peak_fraction": peak_fraction,
                    "configured_max_gap_seconds": max_gap_seconds,
                    "configured_max_jitter_fraction": max_jitter_fraction})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args()
    root = data_root(args.data_root)
    rows = read_manifest(args.manifest, root)
    print(f"Validated {len(rows)} local manifest rows under {root}; no data uploaded.")


if __name__ == "__main__":
    main()
