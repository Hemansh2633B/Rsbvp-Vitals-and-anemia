"""Independent reference implementations of classical unsupervised rPPG methods.

These implementations were written for RSBVP directly from the published
algorithms. They operate on timestamp-regularized ROI *mean RGB traces*
(shape ``(n, 3)``), which is the data the RSBVP browser/offline pipelines
export. They are trace-domain reference implementations, not bit-exact ports
of any specific codebase, and they differ deliberately from the in-repository
legacy pipeline so that the benchmark can expose implementation sensitivity.

    GREEN : Verkruysse et al., Optics Express 2008.
    ICA   : Poh et al.,  Optics Express 2010 / IEEE TBME 2011.
    CHROM : de Haan & Jeanne, IEEE TBME 2013.
    POS   : Wang et al., IEEE TBME 2017.
    PBV   : de Haan & van Leest, Physiological Measurement 2014
            (trace-domain approximation: signature-gated chrominance;
            the authoritative video-domain PBV runs in the rPPG-Toolbox).

LGI and OMIT are video-domain algorithms (they require per-pixel spatial
processing) and are intentionally NOT approximated here; the reference
backend reports them as unsupported on trace input.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, sosfiltfilt, periodogram

DEFAULT_PASSBAND_HZ = (0.7, 3.5)
DEFAULT_WINDOW_SECONDS = 1.6


class FlatSignalError(ValueError):
    """Raised when a trace carries no measurable modulation."""


def bandpass(signal, fs, low_hz=DEFAULT_PASSBAND_HZ[0], high_hz=DEFAULT_PASSBAND_HZ[1], order=3):
    x = np.asarray(signal, dtype=float)
    if x.ndim != 1:
        raise ValueError("bandpass expects a 1-D signal")
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError("fs must be positive and finite")
    if not (0 < low_hz < high_hz < fs / 2.0):
        raise ValueError("passband must satisfy 0 < low < high < fs/2")
    sos = butter(order, [low_hz, high_hz], btype="bandpass", fs=fs, output="sos")
    if len(x) <= 3 * (2 * len(sos) + 1):
        return x - x.mean()
    try:
        return sosfiltfilt(sos, x)
    except ValueError:
        return x - x.mean()


def estimate_hr_bpm(signal, fs, min_hz=DEFAULT_PASSBAND_HZ[0], max_hz=DEFAULT_PASSBAND_HZ[1]):
    """Hann-periodogram peak estimate. Returns (bpm, peak_fraction) or (None, None).

    ``peak_fraction`` is the peak power divided by the total in-band power; it
    is a coarse, uncalibrated spectral-concentration measure — not a validated
    quality score.
    """
    x = np.asarray(signal, dtype=float)
    if x.ndim != 1 or len(x) < max(8, int(4 * fs)) or not np.isfinite(x).all():
        return None, None
    centered = x - x.mean()
    if np.std(centered) < 1e-10:
        return None, None
    freqs, power = periodogram(centered, fs=fs, window="hann")
    mask = (freqs >= min_hz) & (freqs <= max_hz)
    if not mask.any():
        return None, None
    band = power[mask]
    total = float(band.sum())
    if not np.isfinite(total) or total <= 0:
        return None, None
    peak_index = int(np.argmax(band))
    peak_fraction = float(band[peak_index] / total)
    peak_hz = float(freqs[mask][peak_index])
    return peak_hz * 60.0, peak_fraction


def _check_rgb(rgb):
    x = np.asarray(rgb, dtype=float)
    if x.ndim != 2 or x.shape[1] != 3:
        raise ValueError("rgb must have shape (n, 3)")
    if len(x) < 16:
        raise ValueError("at least 16 samples are required")
    if not np.isfinite(x).all():
        raise ValueError("rgb contains missing/non-finite samples")
    if (x <= 0).any():
        raise ValueError("rgb trace-domain methods require positive mean intensities")
    return x


def _normalized(rgb):
    x = _check_rgb(rgb)
    return x / x.mean(axis=0, keepdims=True) - 1.0


def green(rgb, fs, min_hz=DEFAULT_PASSBAND_HZ[0], max_hz=DEFAULT_PASSBAND_HZ[1]):
    x = _check_rgb(rgb)
    if np.std(x[:, 1]) < 1e-10:
        raise FlatSignalError("green channel is flat")
    return bandpass(x[:, 1], fs, min_hz, max_hz), {"algorithm": "GREEN"}


def chrom(rgb, fs, min_hz=DEFAULT_PASSBAND_HZ[0], max_hz=DEFAULT_PASSBAND_HZ[1],
          window_seconds=DEFAULT_WINDOW_SECONDS):
    normalized = _normalized(rgb)
    r, g, b = normalized.T
    xs = 3.0 * r - 2.0 * g
    ys = 1.5 * r + g - 1.5 * b
    win = max(4, int(round(window_seconds * fs)))
    if len(xs) < win:
        win = len(xs)
    step = max(1, win // 2)
    accumulator = np.zeros(len(xs))
    weight = np.zeros(len(xs))
    for start in range(0, len(xs), step):
        end = min(len(xs), start + win)
        if end - start < 4:
            continue
        alpha = np.std(xs[start:end]) / max(np.std(ys[start:end]), 1e-12)
        accumulator[start:end] += xs[start:end] - alpha * ys[start:end]
        weight[start:end] += 1.0
    out = np.divide(accumulator, weight, out=np.zeros_like(accumulator), where=weight > 0)
    out = bandpass(out, fs, min_hz, max_hz)
    return out, {"algorithm": "CHROM", "source_window_seconds": float(window_seconds)}


def pos(rgb, fs, min_hz=DEFAULT_PASSBAND_HZ[0], max_hz=DEFAULT_PASSBAND_HZ[1],
        window_seconds=DEFAULT_WINDOW_SECONDS):
    normalized = _normalized(rgb)
    projection = np.array([[0.0, 1.0, -1.0], [-2.0, 1.0, 1.0]])
    signals = projection @ normalized.T  # (2, n)
    s1, s2 = signals
    win = max(4, int(round(window_seconds * fs)))
    if len(s1) < win:
        win = len(s1)
    step = max(1, win // 2)
    accumulator = np.zeros(len(s1))
    weight = np.zeros(len(s1))
    for start in range(0, len(s1), step):
        end = min(len(s1), start + win)
        if end - start < 4:
            continue
        alpha = np.std(s1[start:end]) / max(np.std(s2[start:end]), 1e-12)
        accumulator[start:end] += s1[start:end] + alpha * s2[start:end]
        weight[start:end] += 1.0
    out = np.divide(accumulator, weight, out=np.zeros_like(accumulator), where=weight > 0)
    out = out - out.mean()
    out = bandpass(out, fs, min_hz, max_hz)
    return out, {"algorithm": "POS", "source_window_seconds": float(window_seconds)}


def _fastica_deflation(xw: np.ndarray, max_iter: int = 200, tol: float = 1e-7) -> list[np.ndarray]:
    """Deterministic deflated FastICA on whitened data (logcosh nonlinearity)."""
    n_features = xw.shape[1]
    components: list[np.ndarray] = []
    for i in range(n_features):
        w = np.zeros(n_features)
        w[i % n_features] = 1.0
        # Deterministic, spread-out initialization avoids degenerate symmetry.
        w = w + 0.25 * np.arange(1, n_features + 1) / n_features
        w /= np.linalg.norm(w)
        for _ in range(max_iter):
            wx = xw @ w
            g = np.tanh(wx)
            gp = 1.0 - g * g
            w_new = (xw.T * g).mean(axis=1) - gp.mean() * w
            for comp in components:
                w_new = w_new - comp * float(comp @ w_new)  # deflation
            norm = np.linalg.norm(w_new)
            if norm < 1e-12:
                break
            w_new /= norm
            if abs(float(w_new @ w)) > 1.0 - tol:
                w = w_new
                break
            w = w_new
        components.append(w)
    return components


def ica(rgb, fs, min_hz=DEFAULT_PASSBAND_HZ[0], max_hz=DEFAULT_PASSBAND_HZ[1]):
    x = _check_rgb(rgb)
    prefiltered = np.column_stack([bandpass(x[:, c], fs, min_hz, max_hz) for c in range(3)])
    centered = prefiltered - prefiltered.mean(axis=0, keepdims=True)
    covariance = np.cov(centered, rowvar=False)
    if not np.isfinite(covariance).all() or np.max(np.abs(covariance)) < 1e-12:
        raise FlatSignalError("RGB traces carry no measurable covariance")
    eigvals, eigvecs = np.linalg.eigh(covariance)
    # Canonicalize eigenvector signs so results do not depend on LAPACK mood.
    for j in range(eigvecs.shape[1]):
        k = int(np.argmax(np.abs(eigvecs[:, j])))
        if eigvecs[k, j] < 0:
            eigvecs[:, j] *= -1.0
    whitening = np.diag(1.0 / np.sqrt(np.maximum(eigvals, 1e-12))) @ eigvecs.T
    xw = centered @ whitening.T
    components = _fastica_deflation(xw)
    sources = [comp @ xw.T for comp in components]
    # Rank candidates by in-band spectral concentration (Poh et al. selection).
    ranked = sorted(
        ((estimate_hr_bpm(src, fs, min_hz, max_hz)[1] or 0.0, idx) for idx, src in enumerate(sources)),
        key=lambda item: item[0],
        reverse=True,
    )
    best_index = ranked[0][1] if ranked else 0
    waveform = sources[best_index]
    waveform = waveform - waveform.mean()
    std = waveform.std()
    if std > 1e-12:
        waveform = waveform / std
    return waveform, {"algorithm": "ICA", "selected_component": int(best_index)}


def pbv(rgb, fs, min_hz=DEFAULT_PASSBAND_HZ[0], max_hz=DEFAULT_PASSBAND_HZ[1],
        window_seconds=DEFAULT_WINDOW_SECONDS):
    """Trace-domain PBV approximation (signature-gated chrominance).

    The published PBV algorithm exploits the blood-volume-pulse signature to
    down-weight specular (non-blood) variation in the chrominance projection.
    On mean-RGB traces the best reproducible analogue is: build the CHROM
    projection, derive a reference signature from the bandpassed green channel,
    and keep only windowed energy that correlates positively with that
    signature. Video-domain PBV must be evaluated via the rPPG-Toolbox/pyVHR
    backends; this reference exists for cross-checking only.
    """
    x = _check_rgb(rgb)
    signature = bandpass(x[:, 1], fs, min_hz, max_hz)
    base, meta = chrom(rgb, fs, min_hz, max_hz, window_seconds)
    win = max(4, int(round(window_seconds * fs)))
    if len(signature) < win:
        win = len(signature)
    step = max(1, win // 2)
    accumulator = np.zeros(len(signature))
    weight = np.zeros(len(signature))
    for start in range(0, len(signature), step):
        end = min(len(signature), start + win)
        if end - start < 4:
            continue
        sig = signature[start:end] - signature[start:end].mean()
        seg = base[start:end] - base[start:end].mean()
        denom = np.linalg.norm(sig) * np.linalg.norm(seg)
        correlation = float(sig @ seg / denom) if denom > 1e-12 else 0.0
        gate = max(0.0, correlation)  # suppress anti-correlated (specular) segments
        accumulator[start:end] += base[start:end] * gate
        weight[start:end] += gate
    if weight.sum() <= 0:
        # No positively correlated segment exists; fall back to the plain
        # chrominance estimate rather than emit a zero-valued fabrication.
        return base, {**meta, "algorithm": "PBV", "signature_gate_fallback": "chrom"}
    out = np.divide(accumulator, weight, out=np.zeros_like(accumulator), where=weight > 0)
    out = bandpass(out, fs, min_hz, max_hz)
    return out, {**meta, "algorithm": "PBV", "signature_gate_fallback": None}


METHODS = {
    "GREEN": green,
    "ICA": ica,
    "CHROM": chrom,
    "POS": pos,
    "PBV": pbv,
}

TRACE_ONLY_UNSUPPORTED = {
    "LGI": "LGI requires per-pixel spatial processing of video frames; use the rppg_toolbox or pyvhr backends",
    "OMIT": "OMIT (Face2PPG) requires video frames; use the rppg_toolbox or pyvhr backends",
}
