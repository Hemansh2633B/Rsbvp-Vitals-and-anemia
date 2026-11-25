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
# A rail run is consecutive samples pinned at the extreme value. Brief single
# samples are ordinary clipping; a sustained run means the ADC saturated and the
# channel cannot be trusted for beat timing.
RAIL_RUN_SAMPLES = 10
RAIL_RUN_MIN_FRACTION = 0.001
# Per-window R-R dispersion gate: MAD(R-R)/median(R-R). Above this we cannot
# distinguish a misdetection from a genuine arrhythmia, so the window is
# rejected rather than reported as a reference.
MAX_RR_DISPERSION = 0.25
# Two independent detectors must agree on the median R-R within this relative
# tolerance, and on the beat count within the same tolerance, or the window is
# rejected (ambiguous reference).
CROSS_CHECK_TOLERANCE = 0.10


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
        rail_fraction = _rail_run_fraction(x)
        if rail_fraction > RAIL_RUN_MIN_FRACTION:
            raise ECGReferenceError(
                "ecg_rail_saturated",
                f"{rail_fraction:.2%} of samples sit in runs of >= {RAIL_RUN_SAMPLES} consecutive "
                "samples pinned at the minimum or maximum value (ADC rail) — beat timing is untrustworthy",
            )
    return x, fs


def _rail_run_fraction(x: np.ndarray) -> float:
    """Fraction of samples inside runs of >= RAIL_RUN_SAMPLES at min or max."""
    total = 0
    for level in (float(x.min()), float(x.max())):
        at_level = np.flatnonzero(np.abs(x - level) < 1e-12)
        if at_level.size < RAIL_RUN_SAMPLES:
            continue
        breaks = np.flatnonzero(np.diff(at_level) > 1)
        starts = np.concatenate([[0], breaks + 1])
        ends = np.concatenate([breaks, [at_level.size - 1]])
        for start, end in zip(starts, ends):
            run = int(end - start + 1)
            if run >= RAIL_RUN_SAMPLES:
                total += run
    return total / x.size


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


def detect_rpeaks_matched_filter(ecg, fs_hz, template_peaks: Sequence[int], *,
                                 bandpass_low_hz: float = 5.0, bandpass_high_hz: float = 15.0,
                                 refractory_s: float = REFRACTORY_S) -> np.ndarray:
    """Second, independent detector: matched filtering against the median QRS.

    A QRS template is built from the median of the bandpassed signal around the
    first-pass detections, then the signal is correlated with that template and
    peaks are picked above half the median correlation with a fixed refractory
    distance. A different detection principle (correlation instead of
    derivative/energy thresholding) makes an agreement check meaningful.
    """
    from scipy.signal import find_peaks

    x, fs = validate_signal(ecg, fs_hz, min_seconds=1.0)
    sos = butter(2, [bandpass_low_hz, bandpass_high_hz], btype="band", fs=fs, output="sos")
    filtered = sosfiltfilt(sos, x)
    half = int(round(0.06 * fs))
    candidates = [int(p) for p in template_peaks if half <= p < filtered.size - half]
    if len(candidates) < 3:
        raise ECGReferenceError("ecg_cross_check_unavailable", "fewer than 3 template peaks")
    segments = np.stack([filtered[p - half:p + half] for p in candidates])
    template = np.median(segments, axis=0)
    template = template - template.mean()
    norm = float(np.linalg.norm(template))
    if norm <= 0:
        raise ECGReferenceError("ecg_cross_check_unavailable", "degenerate QRS template")
    template = template / norm
    correlation = np.correlate(filtered, template, mode="same")
    # Refractory distance is driven by the first-pass rhythm (never below the
    # fixed 250 ms floor) so a slow rhythm cannot produce double detections.
    median_rr = float(np.median(np.diff(candidates))) if len(candidates) > 1 else refractory_s * fs
    distance = max(int(round(0.25 * fs)), int(round(0.5 * median_rr)))
    peaks, _ = find_peaks(correlation, distance=max(1, distance))
    if peaks.size == 0:
        return np.array([], dtype=np.int64)
    # Threshold relative to the correlation AT the first-pass peaks — the T wave
    # correlates poorly with a QRS template, so this rejects it without needing
    # an absolute amplitude rule.
    reference_corr = correlation[np.asarray(candidates, dtype=np.int64)]
    threshold = 0.6 * float(np.median(reference_corr))
    peaks = peaks[correlation[peaks] >= threshold]
    return np.asarray(peaks, dtype=np.int64)


def cross_check_detectors(primary: np.ndarray, secondary: np.ndarray, fs_hz: float,
                          tolerance: float = CROSS_CHECK_TOLERANCE) -> dict:
    """Compare two independent detections; disagreement means an ambiguous window."""
    if primary.size < 2 or secondary.size < 2:
        return {"status": "unavailable", "reason": "ecg_cross_check_unavailable"}
    rr_primary = float(np.median(rr_intervals_s(primary, fs_hz)))
    rr_secondary = float(np.median(rr_intervals_s(secondary, fs_hz)))
    relative_rr_diff = abs(rr_primary - rr_secondary) / max(rr_primary, 1e-9)
    relative_count_diff = abs(int(primary.size) - int(secondary.size)) / max(int(primary.size), 1)
    ok = relative_rr_diff <= tolerance and relative_count_diff <= tolerance
    return {
        "status": "ok" if ok else "disagreement",
        "reason": None if ok else "ecg_cross_check_disagreement",
        "primary_median_rr_s": round(rr_primary, 6),
        "secondary_median_rr_s": round(rr_secondary, 6),
        "relative_rr_difference": round(relative_rr_diff, 6),
        "primary_beats": int(primary.size),
        "secondary_beats": int(secondary.size),
        "relative_beat_count_difference": round(relative_count_diff, 6),
        "tolerance": tolerance,
    }


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
    rr_dispersion: Optional[float] = None
    cross_check: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "rejection_reasons": list(self.rejection_reasons),
            "hr_bpm": self.hr_bpm,
            "rr_median_s": self.rr_median_s,
            "rr_mad_s": self.rr_mad_s,
            "rr_implausible_fraction": self.rr_implausible_fraction,
            "rr_dispersion": self.rr_dispersion,
            "n_rpeaks": self.n_rpeaks,
            "n_rr_intervals": self.n_rr_intervals,
            "coverage_ratio": self.coverage_ratio,
            "window_start_s": self.window_start_s,
            "window_end_s": self.window_end_s,
            "cross_check": self.cross_check,
        }


def _reject(reason: str | list[str], start_s: float, end_s: float, *, implausible: float = 1.0,
            n_peaks: int = 0, n_rr: int = 0, dispersion: Optional[float] = None,
            cross_check: Optional[dict] = None) -> dict:
    reasons = [reason] if isinstance(reason, str) else list(reason)
    return WindowReference("rejected", reasons, None, None, None, implausible, n_peaks, n_rr, None,
                           start_s, end_s, dispersion, cross_check).to_dict()


def window_reference_hr(ecg, fs_hz, start_s: float, end_s: float, *,
                        min_window_seconds: float = MIN_WINDOW_SECONDS,
                        min_peaks: int = MIN_RPEAKS_PER_WINDOW) -> dict:
    """Window-level reference HR. Never fabricates; rejects instead."""
    fs = validate_fs(fs_hz)
    try:
        x = _finite_1d(ecg)
    except ECGReferenceError as exc:
        return _reject(exc.token, float(start_s), float(end_s))

    try:
        start_s = float(start_s)
        end_s = float(end_s)
    except (TypeError, ValueError):
        return _reject("ecg_window_bounds_invalid", float("nan"), float("nan"))
    if not (math.isfinite(start_s) and math.isfinite(end_s)) or end_s <= start_s:
        return _reject("ecg_window_bounds_invalid", start_s, end_s)
    if (end_s - start_s) < min_window_seconds:
        return _reject("ecg_window_too_short", start_s, end_s)

    total_s = x.size / fs
    if start_s >= total_s or end_s > total_s + (1.0 / fs):
        return _reject("ecg_window_out_of_bounds", start_s, end_s)

    i0, i1 = int(math.floor(start_s * fs)), int(math.ceil(end_s * fs))
    segment = x[max(0, i0):min(x.size, i1)]
    try:
        validate_signal(segment, fs, min_seconds=min_window_seconds)
    except ECGReferenceError as exc:
        return _reject(exc.token, start_s, end_s)

    try:
        peaks = detect_rpeaks(segment, fs)
    except ECGReferenceError as exc:
        return _reject(exc.token, start_s, end_s)
    if peaks.size < min_peaks:
        return _reject("ecg_too_few_rpeaks", start_s, end_s, n_peaks=int(peaks.size))

    rr = rr_intervals_s(peaks, fs)
    implausible = _implausible_fraction(rr)
    if implausible > MAX_IMPLAUSIBLE_RR_FRACTION:
        return _reject("ecg_rr_out_of_range", start_s, end_s, implausible=implausible,
                       n_peaks=int(peaks.size), n_rr=int(rr.size))

    valid_rr = rr[(rr >= MIN_RR_S) & (rr <= MAX_RR_S)]
    rr_median = float(np.median(valid_rr))
    rr_mad = float(np.median(np.abs(valid_rr - rr_median))) if valid_rr.size else None
    dispersion = (rr_mad / rr_median) if rr_mad is not None and rr_median > 0 else None

    # Second independent detector on the same window; disagreement = ambiguity.
    try:
        secondary = detect_rpeaks_matched_filter(segment, fs, peaks)
    except ECGReferenceError as exc:
        return _reject(exc.token, start_s, end_s, implausible=implausible,
                       n_peaks=int(peaks.size), n_rr=int(rr.size), dispersion=round(dispersion, 6) if dispersion else None)
    check = cross_check_detectors(peaks, secondary, fs)
    check = {k: v for k, v in check.items()}

    if dispersion is not None and dispersion > MAX_RR_DISPERSION:
        return _reject("ecg_rr_dispersion_high", start_s, end_s, implausible=implausible,
                       n_peaks=int(peaks.size), n_rr=int(rr.size),
                       dispersion=round(dispersion, 6), cross_check=check)

    if check["status"] != "ok":
        return _reject(check["reason"] or "ecg_cross_check_unavailable", start_s, end_s,
                       implausible=implausible, n_peaks=int(peaks.size), n_rr=int(rr.size),
                       dispersion=round(dispersion, 6) if dispersion is not None else None, cross_check=check)

    hr = 60.0 / rr_median
    coverage = float(min(1.0, max(0.0, (float(peaks[-1]) - float(peaks[0])) / fs / (end_s - start_s))))
    return WindowReference("ok", [], round(hr, 6), round(rr_median, 6),
                           None if rr_mad is None else round(rr_mad, 6),
                           implausible, int(peaks.size), int(rr.size),
                           round(coverage, 6), start_s, end_s,
                           round(dispersion, 6) if dispersion is not None else None,
                           check).to_dict()


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
