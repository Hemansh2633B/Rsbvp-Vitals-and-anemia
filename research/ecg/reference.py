#!/usr/bin/env python3
"""ECG-derived reference heart rate for rPPG benchmarking.

Independent, separately-tested pathway. The existing rPPG evaluator and
``research/backends`` remain ECG-agnostic by design; this module is the only
place ECG is processed, and it feeds reference values into the metrics layer
*after* estimation — never into any estimator or quality gate.

Method
------
R-peaks are located with a deliberately classic, documented algorithm:
a simplified **Pan–Tompkins** detector (Pan & Tompkins, "A Real-Time
QRS Detection Algorithm", IEEE Trans. Biomed. Eng., 32(3):230–236, 1985):

1. Bandpass 5–15 Hz (Butterworth, order 2, zero phase) — emphasises the QRS
   complex, attenuates P/T waves and baseline wander.
2. Five-point derivative, squared.
3. 150 ms moving-window integration.
4. Local-maximum picking with a fixed 200 ms refractory period and
   SPKI/NPKI adaptive thresholding (signal/noise peak estimates).
5. Each integrated peak is refined to the maximum absolute bandpassed
   deflection within ±80 ms (sign-preserving magnitude refinement).

Assumptions and limits (binding)
-------------------------------
* Sampling frequency and amplitude units are **caller-supplied**; they are
  never guessed. The validator enforces only a wide sanity envelope
  (100–2000 Hz) as an implementation guard, not a physiological claim.
* R-R intervals must lie in [0.3, 2.0] s (30–200 BPM guard). Windows with
  more than 25 % implausible intervals are rejected as ambiguous.
* HR per window = 60 / median(valid R-R). Averaging is robust to residual
  misdetections; no spectral peak of the ECG is ever used for HR.
* This pathway does **not** compute HRV/PRV, does not classify beats, and
  does not interpret the ECG clinically. ECG-reference agreement measures
  pulse-rate agreement, nothing more.
* Every rejection carries a machine-readable token; the module never
  fabricates a fallback value.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
from scipy.signal import butter, sosfiltfilt

# --- documented implementation guards (rationale in docs/RELIABILITY.md) ---
MIN_FS_HZ = 100.0
MAX_FS_HZ = 2000.0
MIN_RR_S = 0.3
MAX_RR_S = 2.0
MAX_IMPLAUSIBLE_RR_FRACTION = 0.25
MIN_WINDOW_SECONDS = 5.0
MIN_RPEAKS_PER_WINDOW = 3
REFRACTORY_S = 0.200
MWI_S = 0.150
MAX_VALID_TIMING_IRREGULARITY_FRACTION = 0.05
# Minimum median QRS amplitude expressed in robust noise standard deviations
# (MAD-based). Guards against "detecting" R-peaks in pure noise or a signal
# without QRS structure; empirically ~10-100 for synthetic ECGs with SNR > 0 dB.
MIN_QRS_PROMINENCE_SIGMA = 3.0


class ECGReferenceError(ValueError):
    """Machine-readable ECG validation/processing failure."""

    def __init__(self, token: str, detail: str = ""):
        self.token = token
        super().__init__(f"{token}: {detail}" if detail else token)


@dataclass
class ECGConfig:
    fs_hz: float
    bandpass_low_hz: float = 5.0
    bandpass_high_hz: float = 15.0
    refractory_s: float = REFRACTORY_S
    mwi_s: float = MWI_S
    min_peaks_per_window: int = MIN_RPEAKS_PER_WINDOW
    min_window_seconds: float = MIN_WINDOW_SECONDS
    timing_regularity_tol: float = MAX_VALID_TIMING_IRREGULARITY_FRACTION
    z_series: list[str] = field(default_factory=list)  # audit trail of checks applied


def _finite_1d(signal) -> np.ndarray:
    x = np.asarray(signal, dtype=np.float64)
    if x.ndim != 1:
        raise ECGReferenceError("ecg_not_1d", f"ndim={x.ndim}")
    if x.size == 0:
        raise ECGReferenceError("ecg_empty", "no samples")
    if not np.isfinite(x).all():
        bad = int((~np.isfinite(x)).sum())
        raise ECGReferenceError("ecg_nonfinite_samples", f"{bad} non-finite samples")
    return x


def validate_fs(fs_hz) -> float:
    try:
        fs = float(fs_hz)
    except (TypeError, ValueError):
        raise ECGReferenceError("ecg_fs_invalid", f"fs not a number: {fs_hz!r}") from None
    if not math.isfinite(fs) or fs < MIN_FS_HZ or fs > MAX_FS_HZ:
        raise ECGReferenceError("ecg_fs_invalid", f"fs={fs_hz!r} outside documented guard [{MIN_FS_HZ}, {MAX_FS_HZ}] Hz")
    return fs


def validate_signal(signal, fs_hz, min_seconds: float = 1.0) -> tuple[np.ndarray, float]:
    fs = validate_fs(fs_hz)
    x = _finite_1d(signal)
    min_samples = int(math.ceil(min_seconds * fs))
    if x.size < min_samples:
        raise ECGReferenceError("ecg_length_too_short", f"n={x.size} samples < required {min_samples} ({min_seconds}s @ {fs}Hz)")
    centered = x - x.mean()
    if np.std(centered) < 1e-9:
        raise ECGReferenceError("ecg_flat_signal", "zero-variance signal")
    extreme = max(abs(float(x.max())), abs(float(x.min())))
    if extreme > 0:
        saturated = float(np.mean(np.abs(np.abs(x) - extreme) < 1e-12))
        if saturated > 0.02:
            raise ECGReferenceError("ecg_saturated", f"{saturated:.1%} of samples at a rail ({extreme:g})")
    return x, fs


def validate_timestamps(timestamps, n_samples: int, fs: float, regularity_tol: float = MAX_VALID_TIMING_IRREGULARITY_FRACTION) -> np.ndarray:
    """Optional external timestamp vector (seconds). Strictly increasing and
    near-uniform to within ``regularity_tol`` of the nominal interval."""
    if timestamps is None:
        return np.arange(n_samples, dtype=np.float64) / fs
    t = np.asarray(timestamps, dtype=np.float64)
    if t.ndim != 1 or t.size != n_samples:
        raise ECGReferenceError("ecg_timestamps_length_mismatch", f"t={t.size} vs n={n_samples}")
    if not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ECGReferenceError("ecg_timestamps_not_increasing", "timestamps must be finite and strictly increasing")
    diffs = np.diff(t)
    nominal = 1.0 / fs
    irregular = float(np.mean(np.abs(diffs - nominal) > regularity_tol * nominal))
    if irregular > 0.05:
        raise ECGReferenceError("ecg_timestamps_irregular", f"{irregular:.1%} of intervals deviate > {regularity_tol:.0%} from 1/fs")
    return t


def detect_rpeaks(ecg, fs_hz, *, bandpass_low_hz: float = 5.0, bandpass_high_hz: float = 15.0,
                  refractory_s: float = REFRACTORY_S, mwi_s: float = MWI_S) -> np.ndarray:
    """Pan–Tompkins style QRS detection. Returns R-peak sample indices (int64).

    Raises ECGReferenceError on invalid input. Returns an empty array when no
    peaks pass the refractory/threshold logic — callers reject the window.
    """
    x, fs = validate_signal(ecg, fs_hz, min_seconds=1.0)
    sos = butter(2, [bandpass_low_hz, bandpass_high_hz], btype="band", fs=fs, output="sos")
    filtered = sosfiltfilt(sos, x)

    deriv = (np.roll(filtered, -1) - np.roll(filtered, 1)) * 0.5
    deriv[0] = deriv[1]
    deriv[-1] = deriv[-2]
    squared = deriv * deriv

    width = max(1, int(round(mwi_s * fs)))
    kernel = np.ones(width) / width
    integrated = np.convolve(squared, kernel, mode="same")

    refractory = int(round(refractory_s * fs))
    peaks: list[int] = []
    spki = float(integrated.max()) * 0.25 if integrated.size else 0.0
    npki = float(integrated.max()) * 0.05 if integrated.size else 0.0
    threshold = npki + 0.25 * (spki - npki)
    if threshold <= 0.0:
        threshold = float(integrated.max()) * 0.1 + 1e-12

    index = 0
    last_peak = -refractory - 1
    n = integrated.size
    while index < n:
        if integrated[index] >= threshold:
            # find the local maximum within the refractory neighbourhood
            end = min(n, index + refractory)
            local_max = index + int(np.argmax(integrated[index:end]))
            if local_max - last_peak >= refractory:
                peaks.append(local_max)
                # Adaptive threshold update (Pan & Tompkins sec. on SPKI/NPKI)
                if spki == 0.0:
                    spki = integrated[local_max]
                else:
                    spki = 0.125 * integrated[local_max] + 0.875 * spki
                threshold = npki + 0.25 * (spki - npki)
                last_peak = local_max
                index = local_max + refractory
                continue
        index += 1

    if not peaks:
        return np.array([], dtype=np.int64)

    # Refine: snap each integrated peak to the max |bandpassed| within ±80 ms,
    # keeping physiologic ordering.
    radius = int(round(0.080 * fs))
    refined: list[int] = []
    for p in peaks:
        lo = max(0, p - radius)
        hi = min(x.size, p + radius + 1)
        local = lo + int(np.argmax(np.abs(filtered[lo:hi])))
        if refined and local <= refined[-1]:
            local = refined[-1] + 1
        refined.append(int(local))

    peaks_array = np.asarray(refined, dtype=np.int64)
    # Prominence guard: median deflection at R-peaks, in robust noise sigma.
    noise_sigma = 1.4826 * float(np.median(np.abs(filtered - np.median(filtered))))
    if noise_sigma <= 0:
        raise ECGReferenceError("ecg_flat_signal", "no measurable noise floor after bandpass")
    prominence = float(np.median(np.abs(filtered[peaks_array]))) / noise_sigma
    if prominence < MIN_QRS_PROMINENCE_SIGMA:
        raise ECGReferenceError(
            "ecg_qrs_prominence_low",
            f"median R-peak deflection {prominence:.2f} sigma < {MIN_QRS_PROMINENCE_SIGMA} sigma "
            "(no QRS structure — likely noise-only or artefact-contaminated segment)",
        )
    return peaks_array


def rr_intervals_s(peaks: Sequence[int], fs_hz: float) -> np.ndarray:
    fs = validate_fs(fs_hz)
    peaks = np.asarray(peaks, dtype=np.int64)
    if peaks.size < 2:
        return np.array([], dtype=np.float64)
    return np.diff(peaks).astype(np.float64) / fs


def _implausible_fraction(rr: np.ndarray) -> float:
    if rr.size == 0:
        return 1.0
    return float(np.mean((rr < MIN_RR_S) | (rr > MAX_RR_S)))


@dataclass
class WindowReference:
    status: str
    rejection_reasons: list[str]
    hr_bpm: Optional[float]
    rr_median_s: Optional[float]
    rr_mad_s: Optional[float]
    rr_implausible_fraction: float
    n_rpeaks: int
    n_rr_intervals: int
    coverage_ratio: Optional[float]
    window_start_s: float
    window_end_s: float

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "rejection_reasons": list(self.rejection_reasons),
            "hr_bpm": self.hr_bpm,
            "rr_median_s": self.rr_median_s,
            "rr_mad_s": self.rr_mad_s,
            "rr_implausible_fraction": self.rr_implausible_fraction,
            "n_rpeaks": self.n_rpeaks,
            "n_rr_intervals": self.n_rr_intervals,
            "coverage_ratio": self.coverage_ratio,
            "window_start_s": self.window_start_s,
            "window_end_s": self.window_end_s,
        }


def window_reference_hr(ecg, fs_hz, start_s: float, end_s: float, *,
                        min_window_seconds: float = MIN_WINDOW_SECONDS,
                        min_peaks: int = MIN_RPEAKS_PER_WINDOW) -> dict:
    """Window-level reference HR. Never fabricates; rejects instead."""
    fs = validate_fs(fs_hz)
    try:
        x = _finite_1d(ecg)
    except ECGReferenceError as exc:
        return WindowReference("rejected", [exc.token], None, None, None, 1.0, 0, 0,
                               None, float(start_s), float(end_s)).to_dict()

    try:
        start_s = float(start_s)
        end_s = float(end_s)
    except (TypeError, ValueError):
        return WindowReference("rejected", ["ecg_window_bounds_invalid"], None, None, None,
                               1.0, 0, 0, None, float("nan"), float("nan")).to_dict()
    if not (math.isfinite(start_s) and math.isfinite(end_s)) or end_s <= start_s:
        return WindowReference("rejected", ["ecg_window_bounds_invalid"], None, None, None,
                               1.0, 0, 0, None, start_s, end_s).to_dict()
    if (end_s - start_s) < min_window_seconds:
        return WindowReference("rejected", ["ecg_window_too_short"], None, None, None,
                               1.0, 0, 0, None, start_s, end_s).to_dict()

    total_s = x.size / fs
    if start_s >= total_s or end_s > total_s + (1.0 / fs):
        return WindowReference("rejected", ["ecg_window_out_of_bounds"], None, None, None,
                               1.0, 0, 0, None, start_s, end_s).to_dict()

    i0, i1 = int(math.floor(start_s * fs)), int(math.ceil(end_s * fs))
    segment = x[max(0, i0):min(x.size, i1)]
    try:
        validate_signal(segment, fs, min_seconds=min_window_seconds)
    except ECGReferenceError as exc:
        return WindowReference("rejected", [exc.token], None, None, None, 1.0, 0, 0,
                               None, start_s, end_s).to_dict()

    try:
        peaks = detect_rpeaks(segment, fs)
    except ECGReferenceError as exc:
        return WindowReference("rejected", [exc.token], None, None, None, 1.0, 0, 0,
                               None, start_s, end_s).to_dict()
    if peaks.size < min_peaks:
        return WindowReference("rejected", ["ecg_too_few_rpeaks"], None, None, None,
                               1.0, int(peaks.size), 0, None, start_s, end_s).to_dict()

    rr = rr_intervals_s(peaks, fs)
    implausible = _implausible_fraction(rr)
    if implausible > MAX_IMPLAUSIBLE_RR_FRACTION:
        return WindowReference("rejected", ["ecg_rr_out_of_range"], None, None, None,
                               implausible, int(peaks.size), int(rr.size), None,
                               start_s, end_s).to_dict()

    valid_rr = rr[(rr >= MIN_RR_S) & (rr <= MAX_RR_S)]
    rr_median = float(np.median(valid_rr))
    rr_mad = float(np.median(np.abs(valid_rr - rr_median))) if valid_rr.size else None
    hr = 60.0 / rr_median
    coverage = float(min(1.0, max(0.0, (float(peaks[-1]) - float(peaks[0])) / fs / (end_s - start_s))))
    return WindowReference("ok", [], round(hr, 6), round(rr_median, 6),
                           None if rr_mad is None else round(rr_mad, 6),
                           implausible, int(peaks.size), int(rr.size),
                           round(coverage, 6), start_s, end_s).to_dict()


def window_references_for_starts(ecg, fs_hz, window_starts_s: Sequence[float],
                                 window_seconds: float = 12.0, **kwargs) -> dict[float, Optional[float]]:
    """Map each window start (seconds) to its reference HR (or None if rejected).

    Keys are ``float(start_s)``; the caller is responsible for matching the
    benchmark's ``window_key`` convention (recording_id, start with 3-decimal
    formatting). Rejected windows map to None — never to a fabricated value.
    """
    refs: dict[float, Optional[float]] = {}
    for start in window_starts_s:
        result = window_reference_hr(ecg, fs_hz, float(start), float(start) + window_seconds, **kwargs)
        refs[float(start)] = result["hr_bpm"] if result["status"] == "ok" else None
    return refs
