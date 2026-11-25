"""Dataset-independent tests for the ECG reference pathway.

All ECG signals are synthetic (Gaussian QRS/P/T morphology + noise). No
participant data is used, created or collected.
"""
from __future__ import annotations

import numpy as np
import pytest

from research.ecg import reference as ecgref


def synthetic_ecg(fs=1000.0, seconds=30.0, hr_bpm=60.0, noise=0.02, seed=0):
    t = np.arange(0, seconds, 1.0 / fs)
    period = 60.0 / hr_bpm
    ecg = np.zeros_like(t)
    for beat in np.arange(period, seconds - 0.5, period):
        ecg += np.exp(-((t - beat) ** 2) / (2 * 0.008 ** 2))
        ecg += -0.25 * np.exp(-((t - (beat - 0.04)) ** 2) / (2 * 0.010 ** 2))
        ecg += 0.15 * np.exp(-((t - (beat + 0.30)) ** 2) / (2 * 0.030 ** 2))
        ecg += 0.08 * np.exp(-((t - (beat - 0.20)) ** 2) / (2 * 0.025 ** 2))
    rng = np.random.default_rng(seed)
    return t, ecg + noise * rng.standard_normal(t.size)


@pytest.mark.parametrize("hr_bpm", [48.0, 60.0, 75.0, 96.0, 120.0])
def test_rpeak_count_and_hr_match_synthetic_truth(hr_bpm):
    fs = 1000.0
    _, ecg = synthetic_ecg(fs=fs, seconds=40.0, hr_bpm=hr_bpm, noise=0.01)
    peaks = ecgref.detect_rpeaks(ecg, fs)
    expected = int((40.0 - 1.0) // (60.0 / hr_bpm))
    assert abs(peaks.size - expected) <= 2, f"{peaks.size} peaks, expected ~{expected}"
    rr = ecgref.rr_intervals_s(peaks, fs)
    assert np.median(rr) == pytest.approx(60.0 / hr_bpm, rel=0.03)


def test_window_hr_uses_median_rr_and_reports_quality():
    fs = 1000.0
    _, ecg = synthetic_ecg(fs=fs, seconds=40.0, hr_bpm=72.0)
    result = ecgref.window_reference_hr(ecg, fs, 5.0, 35.0)
    assert result["status"] == "ok"
    assert result["hr_bpm"] == pytest.approx(72.0, rel=0.05)
    assert result["rejection_reasons"] == []
    assert result["n_rpeaks"] >= 30
    assert result["rr_implausible_fraction"] == 0.0
    assert 0.0 < result["coverage_ratio"] <= 1.0


@pytest.mark.parametrize("fs", [0.0, 10.0, 50.0, 5000.0, float("nan"), float("inf"), "fast", None])
def test_invalid_sampling_rates_are_rejected(fs):
    _, ecg = synthetic_ecg(fs=1000.0, seconds=10.0)
    with pytest.raises(ecgref.ECGReferenceError) as info:
        ecgref.validate_fs(fs)
    assert info.value.token == "ecg_fs_invalid"


def test_nonfinite_and_empty_signals_rejected():
    _, ecg = synthetic_ecg(seconds=10.0)
    for token, bad in [
        ("ecg_nonfinite_samples", np.where(np.arange(ecg.size) == 5, np.nan, ecg)),
        ("ecg_nonfinite_samples", np.where(np.arange(ecg.size) == 5, np.inf, ecg)),
        ("ecg_empty", np.array([])),
        ("ecg_flat_signal", np.zeros(5000)),
        ("ecg_not_1d", np.zeros((2, 100))),
    ]:
        with pytest.raises(ecgref.ECGReferenceError) as info:
            ecgref.detect_rpeaks(bad, 1000.0)
        assert info.value.token == token


def test_saturated_signal_rejected():
    _, ecg = synthetic_ecg(seconds=5.0)
    clipped = np.clip(ecg * 50, -1.0, 1.0)
    with pytest.raises(ecgref.ECGReferenceError) as info:
        ecgref.validate_signal(clipped, 1000.0)
    assert info.value.token == "ecg_saturated"


def test_irregular_timestamps_rejected_and_regular_accepted():
    n, fs = 5000, 1000.0
    good = np.arange(n) / fs
    assert ecgref.validate_timestamps(good, n, fs).shape == (n,)
    intervals = (1.0 / fs) * (1.0 + 0.4 * np.sin(np.arange(n - 1)))  # 40% swing, still increasing
    jittered = np.concatenate([[0.0], np.cumsum(intervals)])
    with pytest.raises(ecgref.ECGReferenceError) as info:
        ecgref.validate_timestamps(jittered, n, fs)
    assert info.value.token == "ecg_timestamps_irregular"
    decreasing = good.copy()
    decreasing[10] = decreasing[9]
    with pytest.raises(ecgref.ECGReferenceError) as info:
        ecgref.validate_timestamps(decreasing, n, fs)
    assert info.value.token == "ecg_timestamps_not_increasing"
    with pytest.raises(ecgref.ECGReferenceError) as info:
        ecgref.validate_timestamps(good[:-5], n, fs)
    assert info.value.token == "ecg_timestamps_length_mismatch"


def test_implausible_rr_intervals_reject_the_window():
    """>25% of R-R intervals outside 0.3–2.0 s must reject, never average away."""
    fs = 1000.0
    _, ecg = synthetic_ecg(fs=fs, seconds=30.0, hr_bpm=60.0, noise=0.0)
    # A tachycardia-like stretch with 0.25 s spacing (240 BPM): every R-R is
    # below the documented 0.3 s guard, so the window must be rejected.
    t = np.arange(0, 30.0, 1.0 / fs)
    for beat in np.arange(9.0, 23.0, 0.25):
        ecg += 3.0 * np.exp(-((t - beat) ** 2) / (2 * 0.005 ** 2))
    result = ecgref.window_reference_hr(ecg, fs, 8.0, 24.0)
    assert result["status"] == "rejected"
    assert "ecg_rr_out_of_range" in result["rejection_reasons"]
    assert result["hr_bpm"] is None


def test_too_few_rpeaks_and_short_windows_rejected():
    fs = 1000.0
    _, ecg = synthetic_ecg(fs=fs, seconds=30.0, hr_bpm=60.0)
    short = ecgref.window_reference_hr(ecg, fs, 10.0, 13.0)
    assert short["status"] == "rejected" and "ecg_window_too_short" in short["rejection_reasons"]
    out_of_bounds = ecgref.window_reference_hr(ecg, fs, 25.0, 40.0)
    assert out_of_bounds["status"] == "rejected"
    assert "ecg_window_out_of_bounds" in out_of_bounds["rejection_reasons"]
    # Noise without QRS structure must not yield a "reference" heart rate.
    noise_only = 1e-3 * np.random.default_rng(3).standard_normal(int(fs * 10))
    none = ecgref.window_reference_hr(noise_only, fs, 0.0, 10.0)
    assert none["status"] == "rejected" and none["hr_bpm"] is None
    assert "ecg_qrs_prominence_low" in none["rejection_reasons"]


def test_window_bounds_validation():
    _, ecg = synthetic_ecg(seconds=30.0)
    for start, end in [(10.0, 10.0), (12.0, 10.0), (float("nan"), 20.0), ("a", 2.0)]:
        result = ecgref.window_reference_hr(ecg, 1000.0, start, end)
        assert result["status"] == "rejected"
        assert "ecg_window_bounds_invalid" in result["rejection_reasons"]


def test_reference_never_uses_spectral_peak_of_ecg(monkeypatch):
    """Guard: the ECG pathway must call the R-peak detector, not a spectrum."""
    fs = 1000.0
    _, ecg = synthetic_ecg(fs=fs, seconds=40.0, hr_bpm=90.0)
    called = {"n": 0}
    original = ecgref.detect_rpeaks

    def counting(*args, **kwargs):
        called["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ecgref, "detect_rpeaks", counting)
    result = ecgref.window_reference_hr(ecg, fs, 5.0, 35.0)
    assert called["n"] == 1
    assert result["status"] == "ok"
    assert "spectral" not in str(result).lower()


def test_window_references_for_starts_returns_none_for_rejected_windows():
    fs = 1000.0
    _, ecg = synthetic_ecg(fs=fs, seconds=60.0, hr_bpm=66.0)
    refs = ecgref.window_references_for_starts(ecg, fs, [0.0, 30.0, 55.0], window_seconds=30.0)
    assert refs[0.0] is not None and refs[30.0] is not None
    assert refs[55.0] is None  # runs past the end of the recording
    assert all(v is None or 40.0 <= v <= 210.0 for v in refs.values())
