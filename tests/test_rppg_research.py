import numpy as np
import pytest
from rppg_core.research import chrom_rppg, quality_status, timestamps_to_fs
from rppg_core.pipeline import bandpass_filter, compute_fft_spectrum, MIN_BPM, MAX_BPM


def test_research_band_and_fft_search():
    assert MIN_BPM == 42 and MAX_BPM == 210
    fs = 30.0
    t = np.arange(30 * 20) / fs
    x = np.sin(2 * np.pi * 1.2 * t)
    axis, spec = compute_fft_spectrum(x, fs, trim_start_seconds=0)
    assert axis is not None and spec is not None
    assert axis[np.argmax(spec)] == pytest.approx(72, abs=1)
    slow = np.sin(2 * np.pi * 0.75 * t)
    low_axis, low_spec = compute_fft_spectrum(slow, fs, trim_start_seconds=0)
    assert low_axis[np.argmax(low_spec)] == pytest.approx(45, abs=1)
    assert low_axis.min() < 42.5 and low_axis.max() > 209.5


def test_sos_filter_and_reject_invalid_nyquist():
    fs = 30
    t = np.arange(900) / fs
    y = bandpass_filter(np.sin(2*np.pi*t), fs)
    assert np.isfinite(y).all()
    with pytest.raises(ValueError):
        bandpass_filter(np.ones(100), 5)


def test_chrom_synthetic_known_pulse():
    fs = 30
    t = np.arange(600) / fs
    pulse = 0.01 * np.sin(2*np.pi*1.2*t)
    rgb = np.column_stack([100*(1+pulse), 120*(1-pulse), 90*(1+pulse*.5)])
    y, meta = chrom_rppg(rgb, fs)
    assert meta['algorithm'] == 'CHROM'
    assert np.std(y) > 0


def test_timestamps_and_quality_rejection():
    fs, drop = timestamps_to_fs([0, .04, .08, .16, .20])
    assert fs == pytest.approx(25) and drop > 0
    assert quality_status(face_detected=False, frame_count=100, required_frames=30) == 'face_not_detected'
    assert quality_status(face_detected=True, frame_count=2, required_frames=30) == 'warming_up'
    assert quality_status(face_detected=True, frame_count=40, required_frames=30, signal_valid=False) == 'low_signal_quality'
