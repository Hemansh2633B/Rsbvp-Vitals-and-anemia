"""Backend contract shared by every RSBVP research adapter.

A backend consumes a :class:`RecordingInput` (timestamped ROI RGB traces, or a
reference to external video/data files for subprocess backends) and emits
:class:`~research.backends.schema.BenchmarkRecord` objects plus per-algorithm
timing information. Reference/ground-truth measurements are never part of
:class:`RecordingInput`; the benchmark layer joins references afterwards.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np

BACKEND_RECORD_SCHEMA_VERSION = "rsbvp.benchmark-record.v1"
_DEFAULT_PASSBAND_HZ = (0.7, 3.5)  # 42–210 BPM, research-wide default


class BackendError(RuntimeError):
    """Unrecoverable backend failure."""


class BackendUnavailable(BackendError):
    """The backend cannot run in this environment.

    ``reason`` is a short machine-friendly token; ``instructions`` explains how
    a researcher can make the backend available. This is the expected,
    non-exceptional state for optional research environments that are not
    installed (e.g. no toolbox checkout, no GPU, no checkpoint).
    """

    def __init__(self, reason: str, instructions: str | None = None):
        super().__init__(reason if not instructions else f"{reason} — {instructions}")
        self.reason = reason
        self.instructions = instructions or ""


class UnsupportedAlgorithm(BackendError):
    """The backend does not implement the requested algorithm."""


def configuration_hash(config: dict) -> str:
    """Stable sha256 of a JSON-serialisable configuration dictionary."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ROITrace:
    """Mean RGB trace for one region of interest."""

    name: str
    values: np.ndarray  # shape (n, 3), float; NaN marks missing samples


@dataclass
class RecordingInput:
    """Input to a backend. No reference/ground-truth data is included."""

    recording_id: str
    timestamps_s: np.ndarray
    rois: dict[str, np.ndarray]  # name -> (n, 3) array, NaN where missing
    sampling_rate_hz: float
    participant_id: str | None = None
    source_path: str | None = None
    dataset: str | None = None
    # External resources for subprocess backends (never opened by in-process
    # backends): e.g. a toolbox-formatted dataset root or a video file.
    external_data_root: str | None = None

    def __post_init__(self) -> None:
        self.timestamps_s = np.asarray(self.timestamps_s, dtype=float)
        if self.timestamps_s.ndim != 1 or len(self.timestamps_s) < 3:
            raise ValueError("recording must contain at least three timestamps")
        if not np.isfinite(self.timestamps_s).all():
            raise ValueError("timestamps contain NaN/inf; missing timestamps invalidate the recording")
        if np.any(np.diff(self.timestamps_s) <= 0):
            raise ValueError("timestamps must be strictly increasing")
        if not math.isfinite(self.sampling_rate_hz) or self.sampling_rate_hz <= 0:
            raise ValueError("sampling_rate_hz must be positive and finite")
        cleaned: dict[str, np.ndarray] = {}
        for name, values in self.rois.items():
            arr = np.asarray(values, dtype=float)
            if arr.ndim != 2 or arr.shape[1] != 3 or len(arr) != len(self.timestamps_s):
                raise ValueError(f"ROI {name!r} must have shape (n_samples, 3) aligned with timestamps")
            cleaned[name] = arr
        self.rois = cleaned


def iter_windows(
    n_samples: int,
    fs: float,
    window_seconds: float = 12.0,
    step_seconds: float = 6.0,
) -> Iterator[tuple[int, int]]:
    """Yield (start_index, stop_index) sample windows.

    Windows shorter than the requested length at the tail are dropped rather
    than padded — samples are never fabricated to complete a window.
    """
    if fs <= 0:
        raise ValueError("fs must be positive")
    window = int(round(window_seconds * fs))
    step = int(round(step_seconds * fs))
    if window < 8:
        raise ValueError("window_seconds too short for a stable estimate (need >= 8 samples)")
    if step < 1:
        raise ValueError("step_seconds must resolve to at least one sample")
    for start in range(0, n_samples - window + 1, step):
        yield start, start + window


MAX_INTERPOLATION_GAP_S = 0.25  # seconds; mirrors gui/rppg_core/research.py convention


def regularize_segment(t_win: np.ndarray, segment: np.ndarray, fs: float,
                       max_gap_s: float = MAX_INTERPOLATION_GAP_S):
    """Return a gap-consistent view of one window, or None if a long gap exists.

    Regular (evenly sampled) windows are returned unchanged. Windows with
    short-range irregularity (all gaps <= ``max_gap_s``) are linearly
    interpolated onto a uniform grid at ``fs`` — the same convention used by
    ``gui/rppg_core/research.py::resample_rgb_traces``. Any gap longer than
    ``max_gap_s`` invalidates the window entirely; samples are never invented
    across it.
    """
    t = np.asarray(t_win, dtype=float)
    x = np.asarray(segment, dtype=float)
    if len(t) < 2 or not np.isfinite(t).all() or not np.isfinite(x).all():
        return None
    d = np.diff(t)
    if d.size == 0 or np.any(d <= 0):
        return None
    if float(d.max() - d.min()) <= 1e-6 * max(1.0, float(np.median(d))):
        return x  # already regular; no interpolation, no fabricated samples
    if d.max() > max_gap_s:
        return None
    grid = np.arange(t[0], t[-1] + 0.5 / fs, 1.0 / fs)
    out = np.empty((len(grid), x.shape[1]), dtype=float)
    for channel in range(x.shape[1]):
        out[:, channel] = np.interp(grid, t, x[:, channel])
    return out


@dataclass
class WindowResult:
    """Raw result of evaluating one window (internal; pre-schema)."""

    roi: str
    start_index: int
    stop_index: int
    start_s: float
    end_s: float
    pulse_signal: np.ndarray | None  # samples in [start_index, stop_index)
    estimated_hr_bpm: float | None
    signal_quality: str
    sampling_rate_hz: float


@dataclass
class BackendInfo:
    name: str
    version: str
    backend_type: str  # "native-inprocess" | "reference-inprocess" | "external-subprocess" | "external-checkpoint-contract"
    license_id: str
    source: str
    pinned_commit: str | None = None
    integration: str = ""
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "backend_type": self.backend_type,
            "license_id": self.license_id,
            "source": self.source,
            "pinned_commit": self.pinned_commit,
            "integration": self.integration,
            "notes": self.notes,
        }


@dataclass
class BackendRunResult:
    backend: BackendInfo
    records: list = field(default_factory=list)  # list[BenchmarkRecord]
    latency_s: dict[str, float] = field(default_factory=dict)  # algorithm -> wall seconds
    warnings: list[str] = field(default_factory=list)
    configuration_hash: str = ""


def check_algorithms(requested: Sequence[str], supported: Sequence[str], backend_name: str) -> list[str]:
    """Validate requested algorithm names against the backend's support list."""
    supported_normalized = {name.upper(): name for name in supported}
    out: list[str] = []
    for name in requested:
        key = str(name).upper()
        if key not in supported_normalized:
            raise UnsupportedAlgorithm(
                f"backend {backend_name!r} does not implement algorithm {name!r}; "
                f"supported: {', '.join(sorted(supported_normalized.values()))}"
            )
        out.append(supported_normalized[key])
    return out


def timed(callable_):
    start = time.perf_counter()
    result = callable_()
    return result, time.perf_counter() - start


class ResearchBackend(ABC):
    """Abstract research backend contract."""

    name: str = "abstract"

    @abstractmethod
    def info(self) -> BackendInfo: ...

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (usable, human-readable reason or empty string when usable)."""

    @abstractmethod
    def supported_algorithms(self) -> list[str]: ...

    @abstractmethod
    def run(self, recording, algorithms=None, window_seconds=12.0,
            step_seconds=6.0, passband_hz=_DEFAULT_PASSBAND_HZ, rois=None) -> BackendRunResult: ...


def _quality_token_from_features(peak_fraction, snr_db, separation_ratio) -> str:
    """Conservative per-window quality token (documented research heuristics).

    A strong peak is not proof of pulse origin: all three checks must pass for
    ``ok``. Failing windows keep their estimate (annotated, never hidden) but
    are flagged ``low_quality:<check>`` so availability accounting cannot mask
    systematic bias. ``spectral_features`` is the single source of truth.
    """
    from research.backends import reference_methods as _rm
    failing = _rm.quality_failures(peak_fraction, snr_db, separation_ratio)
    if not failing:
        return "ok"
    if failing == ["no_spectral_peak"]:
        return "unavailable:no_spectral_peak"
    return f"low_quality:{failing[0]}"


class TraceBackend(ResearchBackend):
    """Shared windowed execution for in-process, trace-domain backends."""

    #: algorithm -> callable(segment(n,3), fs, min_hz, max_hz, **kwargs) -> (waveform, metadata)
    def _transforms(self) -> dict:
        raise NotImplementedError

    def supported_algorithms(self) -> list[str]:
        return sorted(self._transforms())

    def default_configuration(self, algorithm, window_seconds, step_seconds, passband_hz, roi):
        return {
            "backend": self.name,
            "backend_version": self.info().version,
            "algorithm": algorithm,
            "roi": roi,
            "window_seconds": float(window_seconds),
            "step_seconds": float(step_seconds),
            "passband_hz": [float(passband_hz[0]), float(passband_hz[1])],
            "estimator": "hann-periodogram-v1",
            "hr_selection": "max-power-in-passband",
            "missing_data": "nonfinite-window-rejected|short-gap-linear-interp<=0.25s|long-gap-window-rejected",
        }

    def run(self, recording, algorithms=None, window_seconds=12.0, step_seconds=6.0,
            passband_hz=_DEFAULT_PASSBAND_HZ, rois=None) -> BackendRunResult:
        from research.backends.schema import BenchmarkRecord
        from research.backends import reference_methods

        transforms = self._transforms()
        if algorithms is None:
            algorithms = sorted(transforms)
        wanted = check_algorithms(algorithms, list(transforms), self.name)
        info = self.info()
        run_started = time.perf_counter()
        latencies: dict[str, float] = {}
        records: list = []
        warnings: list[str] = []
        hash_accumulator = {}
        target_rois = rois if rois is not None else list(recording.rois)
        for algorithm in wanted:
            algo_started = time.perf_counter()
            transform = transforms[algorithm]
            for roi_name in target_rois:
                if roi_name not in recording.rois:
                    warnings.append(f"roi {roi_name!r} not present in recording; skipped")
                    continue
                segment_all = recording.rois[roi_name]
                fs = recording.sampling_rate_hz
                config = self.default_configuration(algorithm, window_seconds, step_seconds, passband_hz, roi_name)
                config_hash = configuration_hash(config)
                hash_accumulator[f"{algorithm}:{roi_name}"] = config_hash
                for start, stop in iter_windows(len(segment_all), fs, window_seconds, step_seconds):
                    min_s, max_s = passband_hz
                    start_s = float(recording.timestamps_s[start])
                    end_s = float(recording.timestamps_s[stop - 1])
                    window = segment_all[start:stop]
                    base_kwargs = dict(
                        recording_id=recording.recording_id,
                        timestamp_s=start_s,
                        algorithm=algorithm,
                        roi=roi_name,
                        sampling_rate_hz=fs,
                        backend=info.name,
                        backend_version=info.version,
                        model_checkpoint=None,
                        configuration_hash=config_hash,
                        window_end_s=end_s,
                        participant_id=recording.participant_id,
                        backend_output_type="window",
                    )
                    if not np.isfinite(window).all():
                        records.append(BenchmarkRecord(
                            pulse_signal=None, estimated_hr_bpm=None,
                            signal_quality="rejected:nonfinite_samples", **base_kwargs))
                        continue
                    t_win = recording.timestamps_s[start:stop]
                    regularized = regularize_segment(t_win, window, fs)
                    if regularized is None:
                        records.append(BenchmarkRecord(
                            pulse_signal=None, estimated_hr_bpm=None,
                            signal_quality="rejected:excessive_gaps", **base_kwargs))
                        continue
                    try:
                        waveform, _metadata = transform(regularized, fs, min_s, max_s)
                        bpm, peak_fraction, snr_db, separation_ratio = reference_methods.spectral_features(
                            np.asarray(waveform, dtype=float), fs, min_s, max_s)
                        raw_signal = [float(v) if np.isfinite(v) else None for v in np.asarray(waveform, dtype=float)]
                        quality = _quality_token_from_features(peak_fraction, snr_db, separation_ratio)
                        records.append(BenchmarkRecord(
                            pulse_signal=raw_signal,
                            estimated_hr_bpm=bpm,
                            signal_quality=quality,
                            **base_kwargs))
                    except Exception as exc:  # noqa: BLE001 — per-window isolation is deliberate
                        records.append(BenchmarkRecord(
                            pulse_signal=None, estimated_hr_bpm=None,
                            signal_quality=f"rejected:{type(exc).__name__.lower()}",
                            backend_report={"error": str(exc)}, **base_kwargs))
            latencies[algorithm] = time.perf_counter() - algo_started
        return BackendRunResult(
            backend=info,
            records=records,
            latency_s=latencies,
            warnings=warnings,
            configuration_hash=configuration_hash(hash_accumulator),
        )
