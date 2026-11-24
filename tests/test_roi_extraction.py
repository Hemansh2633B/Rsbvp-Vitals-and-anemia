import numpy as np
import cv2
from rppg_core.pipeline import (
    keep_roi_inside_frame, mean_rgb_from_roi, get_multi_rois,
    estimate_smart_fft_pair, bandpass_filter, pos_rppg,
    normalize_signal, MIN_BPM, MAX_BPM,
)
from gui.rppg_core.quality import agreement_report, AGREEMENT_TOLERANCE_BPM


def test_roi_clamping_and_named_regions():
    shape = (100, 120, 3)
    assert keep_roi_inside_frame((-5, -7, 30, 40), shape) == (0, 0, 30, 40)
    rois = get_multi_rois((10, 10, 90, 80), shape)
    assert set(rois) == {'forehead', 'left_cheek', 'right_cheek'}
    assert all(x >= 0 and y >= 0 and x+w <= 120 and y+h <= 100 for x,y,w,h in rois.values())


def test_skin_color_mask_does_not_accept_blue_background():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[:] = (220, 50, 20)  # blue-dominant BGR background
    assert mean_rgb_from_roi(frame, (0, 0, 40, 40)) is None


def _roi_trace(seconds=12.0, fs=30.0, bpm=70.0, seed=7):
    """Synthetic per-ROI RGB trace with a known pulse frequency."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    pulse = np.sin(2 * np.pi * (bpm / 60.0) * t)
    # Per-channel amplitude/phase variation to simulate different ROIs
    rgb = np.column_stack([
        100 * (1 + 0.008 * pulse) + rng.normal(0, 0.3, len(t)),
        120 * (1 + 0.010 * pulse) + rng.normal(0, 0.3, len(t)),
        90  * (1 + 0.006 * pulse) + rng.normal(0, 0.3, len(t)),
    ])
    return rgb


def test_per_roi_fft_estimates_produce_agreement_report():
    # Each ROI yields an HR estimate near 70 BPM; AgreementReport over the
    # per-ROI values reports small spread and passes tolerance.
    fs = 30.0
    roi_traces = {
        "forehead": _roi_trace(fs=fs, bpm=70.0, seed=1),
        "left_cheek": _roi_trace(fs=fs, bpm=71.0, seed=2),
        "right_cheek": _roi_trace(fs=fs, bpm=69.0, seed=3),
    }
    estimates = {}
    for name, trace in roi_traces.items():
        green = trace[:, 1]
        pos_raw = pos_rppg(trace, fs=fs)
        pos_raw = pos_raw - np.mean(pos_raw)
        pos_filt = bandpass_filter(
            normalize_signal(pos_raw), fs=fs, min_bpm=MIN_BPM, max_bpm=MAX_BPM
        )
        _, _, consensus, _, _ = estimate_smart_fft_pair(
            green, pos_filt, fs, min_bpm=MIN_BPM, max_bpm=MAX_BPM,
            trim_start_seconds=3.0,
        )
        assert consensus is not None, f"{name} ROI produced no HR estimate"
        estimates[name] = float(consensus)

    report = agreement_report(estimates)
    assert report.n_valid == 3
    assert report.spread_bpm is not None
    assert report.spread_bpm <= AGREEMENT_TOLERANCE_BPM
    assert report.within_tolerance


def test_per_roi_divergent_estimates_fail_agreement():
    # One ROI diverges strongly -> spread exceeds tolerance -> agreement fails.
    fs = 30.0
    roi_traces = {
        "forehead": _roi_trace(fs=fs, bpm=70.0, seed=1),
        "left_cheek": _roi_trace(fs=fs, bpm=95.0, seed=2),  # far from forehead
        "right_cheek": _roi_trace(fs=fs, bpm=71.0, seed=3),
    }
    estimates = {}
    for name, trace in roi_traces.items():
        green = trace[:, 1]
        pos_raw = pos_rppg(trace, fs=fs)
        pos_raw = pos_raw - np.mean(pos_raw)
        pos_filt = bandpass_filter(
            normalize_signal(pos_raw), fs=fs, min_bpm=MIN_BPM, max_bpm=MAX_BPM
        )
        _, _, consensus, _, _ = estimate_smart_fft_pair(
            green, pos_filt, fs, min_bpm=MIN_BPM, max_bpm=MAX_BPM,
            trim_start_seconds=3.0,
        )
        if consensus is not None:
            estimates[name] = float(consensus)

    report = agreement_report(estimates)
    assert report.n_valid >= 2
    # Divergent estimates should produce a large spread
    assert report.spread_bpm is not None
    assert report.spread_bpm > AGREEMENT_TOLERANCE_BPM
    assert not report.within_tolerance
