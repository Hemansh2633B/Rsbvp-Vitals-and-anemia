"""Local-only, explicit-manifest dataset intake and reference waveform utilities.

No network access, provider-specific filename assumptions, or dataset uploads.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.signal import periodogram

MANIFEST_REQUIRED = {
    "dataset", "dataset_version", "participant_id", "recording_id",
    "trace_csv", "reference_path", "reference_format", "reference_type",
    "time_offset_s",
    "source_citation", "license_verified",
}
REFERENCE_TYPES = {"ppg", "bvp", "ecg"}


@dataclass(frozen=True)
class ReferenceSignal:
    timestamps_s: np.ndarray
    values: np.ndarray
    sampling_hz: float
    signal_type: str
    offset_s: float


def data_root(cli_root: str | Path | None = None) -> Path:
    """Choose CLI root, then env root; reject implicit machine-specific defaults."""
    raw = cli_root if cli_root is not None else os.environ.get("RSBVP_DATA_ROOT")
    if not raw:
        raise ValueError("Set RSBVP_DATA_ROOT or pass --data-root; no implicit dataset path is used")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root does not exist or is not a directory: {root}")
    return root


def read_manifest(path: str | Path, root: str | Path) -> list[dict[str, str]]:
    path, root = Path(path), Path(root).resolve()
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = MANIFEST_REQUIRED - set(reader.fieldnames or ())
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
            source = Path(row[field])
            target = (root / source).resolve() if not source.is_absolute() else source.resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Manifest row {line}: {field} must remain inside data root")
            if not target.is_file():
                raise FileNotFoundError(f"Manifest row {line}: missing {field}: {target}")
        fmt = row["reference_format"].lower()
        if fmt not in {"csv", "hdf5"}:
            raise ValueError(f"Manifest row {line}: reference_format must be csv or hdf5")
        if fmt == "csv" and not (row.get("reference_signal_column") or "").strip():
            raise ValueError(f"Manifest row {line}: CSV requires reference_signal_column")
        if fmt == "hdf5" and not (row.get("reference_dataset_path") or "").strip():
            raise ValueError(f"Manifest row {line}: HDF5 requires explicit reference_dataset_path")
        offset = float(row["time_offset_s"])
        if not np.isfinite(offset):
            raise ValueError(f"Manifest row {line}: time_offset_s must be finite")
        fs = row["reference_fs_hz"].strip()
        if fs and (not np.isfinite(float(fs)) or float(fs) <= 0):
            raise ValueError(f"Manifest row {line}: reference_fs_hz must be positive")
        if not fs and not (row.get("reference_time_column") or "").strip():
            raise ValueError(f"Manifest row {line}: provide reference_fs_hz or reference_time_column")
    return rows


def _local_path(root: Path, value: str) -> Path:
    p = Path(value)
    p = (root / p).resolve() if not p.is_absolute() else p.resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError("Input path escapes configured data root")
    return p


def load_reference(row: dict[str, str], root: str | Path) -> ReferenceSignal:
    """Load a CSV reference, or a configured HDF5 dataset (optional h5py).

    For HDF5, `reference_dataset_path` must explicitly identify a 1-D signal.
    Timestamp dataset mapping is intentionally not guessed; use a reference time
    column in CSV or a verified sampling rate for HDF5 sample-index timing.
    """
    root = Path(root).resolve()
    path = _local_path(root, row["reference_path"])
    fmt = row["reference_format"].lower()
    fs_raw = (row.get("reference_fs_hz") or "").strip()
    fs = float(fs_raw) if fs_raw else None
    time_column = (row.get("reference_time_column") or "").strip()
    signal_column = row["reference_signal_column"].strip()
    if fmt == "csv":
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
        elif fs:
            times = np.arange(len(vals), dtype=float) / fs
        else:
            raise ValueError("Reference CSV needs timestamps or a verified reference_fs_hz")
    elif fmt == "hdf5":
        key = (row.get("reference_dataset_path") or "").strip()
        if not key:
            raise ValueError("HDF5 requires explicit reference_dataset_path after archive inspection")
        try:
            import h5py  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install h5py to read the explicitly configured HDF5 signal") from exc
        if time_column:
            raise ValueError("HDF5 timestamp datasets are not guessed; normalize documented timestamps to CSV")
        if not fs:
            raise ValueError("HDF5 reference requires verified reference_fs_hz")
        with h5py.File(path, "r") as f:
            if key not in f:
                raise ValueError(f"Configured HDF5 dataset path {key!r} not found")
            vals = np.asarray(f[key][()], dtype=float).reshape(-1)
        times = np.arange(len(vals), dtype=float) / fs
    else:
        raise ValueError(f"Unsupported reference format: {fmt}")
    if vals.ndim != 1 or len(vals) != len(times) or len(vals) < 2:
        raise ValueError("Reference must contain at least two aligned samples")
    # Reference NaNs remain missing and are rejected window-by-window; malformed
    # timestamps cannot be repaired without inventing synchronization.
    finite_t = np.isfinite(times)
    if not finite_t.all() or np.any(np.diff(times) <= 0):
        raise ValueError("Reference timestamps must be finite and strictly increasing")
    if fs is None:
        fs = float(1 / np.median(np.diff(times)))
    return ReferenceSignal(times + float(row["time_offset_s"]), vals, fs,
                           row["reference_type"].lower(), float(row["time_offset_s"]))


def _number_or_nan(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else np.nan
    except (ValueError, TypeError):
        return np.nan


def reference_hr_windows(reference: ReferenceSignal, starts_s: Iterable[float], *,
                         window_seconds: float = 12.0, step_seconds: float = 6.0,
                         min_hz: float = 0.7, max_hz: float = 3.5,
                         max_gap_seconds: float = 0.25) -> list[dict[str, object]]:
    """Independent per-window HR from reference PPG/BVP/ECG; no gap extrapolation."""
    if reference.signal_type not in REFERENCE_TYPES:
        raise ValueError("Reference must be explicitly typed ppg, bvp, or ecg")
    if window_seconds <= 0 or step_seconds <= 0 or max_gap_seconds <= 0:
        raise ValueError("Window, step and gap limits must be positive")
    t, x = reference.timestamps_s, reference.values
    out: list[dict[str, object]] = []
    for start in starts_s:
        start = float(start)
        stop = start + window_seconds
        idx = np.flatnonzero((t >= start) & (t < stop))
        reason = None
        bpm: float | None = None
        if len(idx) < max(8, int(window_seconds * min_hz * 2)):
            reason = "insufficient_reference_samples"
        elif not np.isfinite(x[idx]).all():
            reason = "missing_reference_samples"
        elif np.max(np.diff(t[idx])) > max_gap_seconds:
            reason = "reference_gap_exceeds_limit"
        else:
            tt, xx = t[idx], x[idx]
            fs = 1 / float(np.median(np.diff(tt)))
            if fs <= 2 * max_hz:
                reason = "reference_nyquist_below_passband"
            elif (tt[-1] - tt[0]) < window_seconds * 0.8:
                reason = "insufficient_reference_duration"
            else:
                # Uniform grid based on observed rate, only after the gap check.
                grid = np.arange(tt[0], tt[-1], 1 / fs)
                if len(grid) < 8:
                    reason = "insufficient_reference_samples"
                else:
                    y = np.interp(grid, tt, xx)
                    freq, power = periodogram(y, fs=fs, window="hann", detrend="constant")
                    band = (freq >= min_hz) & (freq <= max_hz)
                    if not band.any() or not np.isfinite(power[band]).all() or np.max(power[band]) <= 0:
                        reason = "reference_signal_invalid"
                    else:
                        bpm = float(freq[band][np.argmax(power[band])] * 60)
        out.append({"start_s": start, "end_s": stop, "reference_hr_bpm": bpm,
                    "valid": bpm is not None, "rejection_reason": reason,
                    "reference_type": reference.signal_type,
                    "reference_fs_hz": reference.sampling_hz})
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
