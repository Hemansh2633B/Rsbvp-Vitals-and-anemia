import numpy as np
import pytest
from rppg_core.research import chrom_rppg, quality_status, timestamps_to_fs, resample_rgb_traces, measurement_gate
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


def test_timestamp_resampling_bridges_only_short_frame_gaps():
    t=np.arange(100)/30
    rgb=np.column_stack([100+np.sin(t),120+np.sin(t),90+np.sin(t)])
    tdrop=np.delete(t,20); xdrop=np.delete(rgb,20,axis=0)
    grid,traces,fs=resample_rgb_traces(tdrop,{'forehead':xdrop})
    assert fs == pytest.approx(30,abs=1)
    assert len(grid)>=99 and np.isfinite(traces['forehead']).all()
    tgap=np.concatenate([t[:30],t[30:]+.4]); xgap=np.concatenate([rgb[:30],rgb[30:]])
    with pytest.raises(ValueError): resample_rgb_traces(tgap,{'forehead':xgap})


def test_measurement_gate_rejects_unreliable_or_disagreeing_signals():
    assert measurement_gate([70,72,71],[.5,.4,.4],12)['valid']
    assert measurement_gate([70,110,72],[.5,.4,.4],12)['valid'] is False
    assert measurement_gate([70,72],[.1,.2],12)['state']=='low_signal_quality'
    assert measurement_gate([70,72],[.5,.5],5)['state']=='warming_up'
    assert measurement_gate([70,72],[.5,.5],12,candidate=100)['valid'] is False


# Sprint 8 CHROM contract tests. Software behavior only - not a validation of
# CHROM as a physiological estimator.
def test_chrom_rejects_invalid_rgb_inputs():
    fs = 30.0
    t = np.arange(30 * 20) / fs
    good = np.column_stack([100*(1+0.01*np.sin(2*np.pi*1.2*t)),
                            120*(1-0.01*np.sin(2*np.pi*1.2*t)),
                            90*(1+0.005*np.sin(2*np.pi*1.2*t))])
    with pytest.raises(ValueError):                       # non-positive means
        bad = good.copy(); bad[::7, 1] = 0.0
        chrom_rppg(bad, fs)
    with pytest.raises(ValueError):                       # non-finite samples
        bad = good.copy(); bad[3, 0] = np.nan
        chrom_rppg(bad, fs)
    with pytest.raises(ValueError):                       # too few samples
        chrom_rppg(good[:6], fs)
    with pytest.raises(ValueError):                       # wrong shape
        chrom_rppg(good[:, :2], fs)
    with pytest.raises(ValueError):                       # fs below Nyquist bound for 3.5 Hz
        chrom_rppg(good, 5.0)


def test_chrom_output_is_finite_and_standardized():
    fs = 30.0
    t = np.arange(600) / fs
    pulse = 0.01 * np.sin(2*np.pi*1.2*t)
    rgb = np.column_stack([100*(1+pulse), 120*(1-pulse), 90*(1+pulse*.5)])
    y, meta = chrom_rppg(rgb, fs)
    assert np.isfinite(y).all()
    assert abs(y.mean()) < 1e-8
    assert meta["passband_hz"] == [0.7, 3.5]


def test_measurement_gate_none_estimates_never_validate():
    gate = measurement_gate([None, None, 70.0], [None, None, 0.9], 15.0)
    assert gate["valid"] is False
    assert gate["state"] == "low_signal_quality"
