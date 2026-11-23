"""Small independent research utilities; no camera or clinical inference here."""
from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfiltfilt


def chrom_rppg(rgb, fs, min_hz=0.7, max_hz=3.5, window_seconds=1.6):
    """CHROM chrominance projection from Nx3 mean RGB traces.

    Returns (waveform, metadata). Inputs must be temporally sampled means;
    output is not a heart-rate measurement until quality gates pass.
    """
    x = np.asarray(rgb, dtype=float)
    if x.ndim != 2 or x.shape[1] != 3 or len(x) < 8:
        raise ValueError("rgb must have shape (n>=8, 3)")
    if not np.isfinite(fs) or fs <= 2 * max_hz:
        raise ValueError("sampling rate must exceed twice the upper passband")
    if not np.isfinite(x).all() or (x <= 0).any():
        raise ValueError("RGB traces must be finite and positive")
    normalized = x / np.mean(x, axis=0, keepdims=True) - 1.0
    r, g, b = normalized.T
    xs = 3 * r - 2 * g
    ys = 1.5 * r + g - 1.5 * b
    win = max(2, int(round(window_seconds * fs)))
    out = np.zeros(len(x), dtype=float)
    weight = np.zeros(len(x), dtype=float)
    for start in range(0, len(x), max(1, win // 2)):
        end = min(len(x), start + win)
        if end - start < 4:
            continue
        alpha = np.std(xs[start:end]) / max(np.std(ys[start:end]), 1e-8)
        segment = xs[start:end] - alpha * ys[start:end]
        out[start:end] += segment
        weight[start:end] += 1.0
    out = np.divide(out, weight, out=np.zeros_like(out), where=weight > 0)
    sos = butter(3, [min_hz, max_hz], btype="bandpass", fs=fs, output="sos")
    if len(out) > 3 * (2 * len(sos) + 1):
        out = sosfiltfilt(sos, out)
    out -= out.mean()
    scale = out.std()
    if scale > 1e-8:
        out /= scale
    return out, {"algorithm": "CHROM", "fs_hz": float(fs), "passband_hz": [min_hz, max_hz]}


def timestamps_to_fs(timestamps):
    """Estimate sampling frequency robustly from monotonic frame timestamps."""
    t = np.asarray(timestamps, dtype=float)
    if t.ndim != 1 or len(t) < 3 or not np.isfinite(t).all():
        raise ValueError("at least three finite timestamps are required")
    d = np.diff(t)
    if np.any(d <= 0):
        raise ValueError("timestamps must be strictly increasing")
    return float(1.0 / np.median(d)), float(np.mean(d > 1.5 * np.median(d)))


def resample_rgb_traces(timestamps, traces, *, max_gap_seconds=0.25):
    """Regularize timestamped Nx3 traces at median rate without crossing long gaps."""
    t = np.asarray(timestamps, dtype=float)
    fs, _ = timestamps_to_fs(t)
    if not np.isfinite(max_gap_seconds) or max_gap_seconds <= 0:
        raise ValueError("max_gap_seconds must be positive")
    if np.max(np.diff(t)) > max_gap_seconds:
        raise ValueError("timestamp discontinuity exceeds interpolation limit")
    grid = np.arange(t[0], t[-1] + 0.25 / fs, 1.0 / fs)
    result = {}
    for name, values in traces.items():
        x = np.asarray(values, dtype=float)
        if x.shape != (len(t), 3):
            raise ValueError(f"trace {name} must have shape (n, 3)")
        out = np.full((len(grid), 3), np.nan)
        for channel in range(3):
            good = np.isfinite(x[:, channel])
            tg, vg = t[good], x[good, channel]
            if len(tg) < 2:
                continue
            right = np.searchsorted(tg, grid, side="right")
            lo, hi = np.clip(right-1, 0, len(tg)-1), np.clip(right, 0, len(tg)-1)
            gaps = tg[hi] - tg[lo]
            ok = (grid >= tg[0]) & (grid <= tg[-1]) & (gaps <= max_gap_seconds)
            frac = np.divide(grid-tg[lo], gaps, out=np.zeros_like(grid), where=gaps>0)
            out[ok, channel] = vg[lo[ok]]*(1-frac[ok]) + vg[hi[ok]]*frac[ok]
        result[name] = out
    return grid, result, fs


def measurement_gate(estimates, reliabilities, duration_seconds, *, candidate=None, agreement_bpm=12.0, minimum_reliability=0.25):
    """Conservative cross-estimator gate; corrections cannot override rejection."""
    if duration_seconds < 8:
        return {"valid": False, "state": "warming_up", "reason": "At least 8 seconds of usable trace are required"}
    pairs = [(float(v), float(q)) for v, q in zip(estimates, reliabilities)
             if v is not None and q is not None and np.isfinite(v) and np.isfinite(q)]
    trustworthy = [(v, q) for v, q in pairs if q >= minimum_reliability]
    if len(trustworthy) < 2:
        return {"valid": False, "state": "low_signal_quality", "reason": "Fewer than two estimators passed the reliability threshold"}
    values = [v for v, _ in trustworthy]
    if max(values) - min(values) > agreement_bpm:
        return {"valid": False, "state": "low_signal_quality", "reason": "Independent estimator disagreement exceeds the configured tolerance"}
    if candidate is not None and (not np.isfinite(candidate) or abs(float(candidate)-float(np.median(values))) > agreement_bpm):
        return {"valid": False, "state": "low_signal_quality", "reason": "Legacy correction candidate disagrees with uncorrected estimators"}
    return {"valid": True, "state": "valid", "reason": "Independent estimates agree and pass reliability checks"}


def quality_status(*, face_detected, frame_count, required_frames, motion_score=0.0, signal_valid=True):
    if not face_detected:
        return "face_not_detected"
    if frame_count < required_frames:
        return "warming_up" if frame_count > 0 else "insufficient_frames"
    if motion_score > 0.8:
        return "excessive_motion"
    if not signal_valid:
        return "low_signal_quality"
    return "valid"
