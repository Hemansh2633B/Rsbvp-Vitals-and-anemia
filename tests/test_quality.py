"""Sprint-7 regression tests for the explainable quality model.

Software behavior only — no physiological validation is implied. Covers:
low/high illumination (clipping/underexposure), motion, face displacement,
ROI dropout, wrong sampling rate, irregular timestamps, short/long gaps,
weak pulsatile selectivity, estimator disagreement and warmup.
"""
import numpy as np
import pytest

from gui.rppg_core.quality import (
    MIN_WINDOW_SECONDS,
    acquisition_report,
    agreement_report,
    assess_window,
    spectral_quality,
    trace_report,
)
from research.backends import reference_methods as rm

FS = 30.0


def pulse(seconds=12.0, fs=FS, bpm=70.0, gain=1.0, offset=150.0, noise_std=0.2, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    return offset + gain * 9.0 * np.sin(2 * np.pi * (bpm / 60) * t) + rng.normal(0, noise_std, len(t))


# ---------------------------------------------------------------- spectral

def test_clean_pulse_passes_all_spectral_checks():
    sq = spectral_quality(pulse(), FS)
    assert sq.passing
    assert sq.peak_hz == pytest.approx(70.0 / 60.0, abs=0.1)
    assert not sq.failing_checks


def test_white_noise_is_rejected_as_low_concentration():
    rng = np.random.default_rng(3)
    sq = spectral_quality(rng.normal(0, 10, int(12 * FS)), FS)
    assert not sq.passing
    assert any("low_concentration" in f or "no_spectral_peak" in f for f in sq.failing_checks)


def test_weak_pulse_buried_in_noise_is_not_accepted():
    rng = np.random.default_rng(11)
    sig = rng.normal(0, 9.0, int(12 * FS)) + 1.1 * np.sin(2 * np.pi * 70 / 60 * np.arange(int(12 * FS)) / FS)
    sq = spectral_quality(sig, FS)
    assert not sq.passing
    assert any(f.startswith(("low_concentration", "weak_separation", "no_spectral_peak")) for f in sq.failing_checks)


def test_competing_peak_reduces_separation_and_flags_ambiguity():
    t = np.arange(int(12 * FS)) / FS
    # Two in-band components; the second within 0.25 Hz would count as harmonics
    # guard, so place it at +1 Hz with nearly equal amplitude to force separation.
    mixed = 9.0 * np.sin(2 * np.pi * 1.10 * t) + 8.6 * np.sin(2 * np.pi * 2.10 * t)
    sq = spectral_quality(mixed, FS)
    assert sq.separation_ratio is not None
    assert sq.separation_ratio < 1.5
    assert any("weak_separation" in f for f in sq.failing_checks)


def test_reference_methods_mirror_gui_quality():
    sq_gui = spectral_quality(pulse(), FS)
    bpm, frac, snr, sep = rm.spectral_features(pulse(), FS)
    assert bpm == pytest.approx(sq_gui.peak_hz * 60, abs=1e-6)
    assert frac == pytest.approx(sq_gui.peak_fraction, rel=1e-9)
    assert snr == pytest.approx(sq_gui.snr_db, rel=1e-9)
    assert sep == pytest.approx(sq_gui.separation_ratio, rel=1e-9)


# ------------------------------------------------------------ acquisition

def test_black_image_fails_acquisition():
    rep = acquisition_report(np.zeros((100, 3)))
    assert not rep.passing
    assert rep.clip_fraction > 0.9


def test_white_clipped_image_fails_acquisition():
    rep = acquisition_report(np.full((100, 3), 255.0))
    assert not rep.passing


def test_normal_face_exposure_passes_acquisition():
    rng = np.random.default_rng(5)
    rep = acquisition_report(rng.uniform(90, 220, (500, 3)))
    assert rep.passing


def test_flat_sensor_trace_fails_dynamic_range():
    rep = acquisition_report(np.full((100, 3), 128.0))
    assert rep.dynamic_range == 0
    assert not rep.passing


# ---------------------------------------------------- acquisition/motion/ROI

def test_excessive_motion_is_unavailable():
    t = np.arange(int(12 * FS))
    rep = trace_report(t / FS)
    out = assess_window(trace=rep, excessive_motion=True)
    assert out.status == "excessive_motion" and not out.available


def test_face_not_detected_short_circuits():
    out = assess_window(face_detected=False)
    assert out.status == "face_not_detected" and out.reasons == ("face_not_detected",)


def test_roi_lost_short_circuits_before_quality():
    out = assess_window(roi_coverage=0.0)
    assert out.status == "roi_lost"
    assert out.reasons == ("roi_lost",)


def test_partial_roi_dropout_below_coverage_gate():
    rep = acquisition_report(np.full((10, 3), 150.0) + np.arange(30).reshape(10, 3) % 40)
    out = assess_window(trace=trace_report(np.arange(int(12 * FS)) / FS),
                        acquisition=rep, spectral=spectral_quality(pulse(), FS),
                        agreement=agreement_report({"a": 70.0, "b": 70.0}),
                        roi_coverage=0.3)
    assert out.status == "low_signal_quality"
    assert any("roi_coverage" in r for r in out.reasons)


# ------------------------------------------------------------- timestamps

def test_wrong_sampling_rate_rejected():
    out = assess_window(trace=trace_report(np.arange(200) / 8.0), spectral=spectral_quality(pulse(), FS))
    assert out.status == "insufficient_frames"


def test_irregular_timestamps_rejected():
    t = np.arange(int(12 * FS)) / FS
    t[150:] += 1.0  # all later samples shifted: one 1.0 s gap
    out = assess_window(trace=trace_report(t), spectral=spectral_quality(pulse(), FS))
    assert out.status == "irregular_timestamps"


def test_long_timestamp_gap_detected_in_trace_report():
    t = np.arange(int(12 * FS)) / FS
    keep = np.ones_like(t, dtype=bool)
    keep[150:150 + 9] = False  # 0.3 s gap
    rep = trace_report(t[keep])
    assert rep.max_gap_s == pytest.approx(10 / FS, abs=1e-9)


def test_short_gap_does_not_reject():
    rep = trace_report(np.arange(int(12 * FS)) / FS)  # uniform
    assert rep.max_gap_s == pytest.approx(1 / FS)
    assert rep.regular


def test_warming_up_until_window_complete():
    short = pulse(seconds=5.0)
    out = assess_window(trace=trace_report(np.arange(len(short)) / FS), spectral=spectral_quality(short, FS))
    assert out.status == "warming_up"
    assert "more seconds" in out.reason


# ------------------------------------------------------ estimator agreement

def test_estimator_disagreement_flags_low_signal_quality():
    out = assess_window(trace=trace_report(np.arange(int(12 * FS)) / FS),
                        acquisition=acquisition_report(np.full((10, 3), 150.0) + np.arange(30).reshape(10, 3) % 40),
                        spectral=spectral_quality(pulse(), FS),
                        agreement=agreement_report({"green": 70.0, "pos": 92.0}))
    assert out.status == "low_signal_quality"
    assert any("estimator_disagreement" in r for r in out.reasons)


def test_estimator_agreement_passes_when_consistent():
    out = assess_window(trace=trace_report(np.arange(int(12 * FS)) / FS),
                        acquisition=acquisition_report(np.full((10, 3), 150.0) + np.arange(30).reshape(10, 3) % 40),
                        spectral=spectral_quality(pulse(), FS),
                        agreement=agreement_report({"green": 70.0, "pos": 71.0, "chrom": 69.0}))
    assert out.status == "valid" and out.available


def test_low_light_clipped_acquisition_never_reports_valid():
    # Low illumination + clipping at the black rail: conservative path must reject
    # even though a 1.166 Hz sinusoid dominates the periodogram.
    t = np.arange(int(12 * FS)) / FS
    clipped = np.clip(2.5 * np.sin(2 * np.pi * 70 / 60 * t) + 1.0, 0, 255)
    out = assess_window(trace=trace_report(t),
                        acquisition=acquisition_report(np.column_stack([clipped, clipped, clipped])),
                        spectral=spectral_quality(pulse(), FS),
                        agreement=agreement_report({"green": 70.0, "pos": 70.0}))
    assert out.status == "low_signal_quality" and not out.available


# Sprint 8 regression coverage: the six quality concepts are reported
# separately on every verdict path; nothing is blended into a single number.
CONCEPT_KEYS = ("face_tracking", "roi_extraction", "temporal_acquisition",
                "pulse_signal", "algorithm_agreement", "availability")


def test_concepts_present_and_separated_on_face_failure():
    out = assess_window(face_detected=False)
    assert set(out.concepts) == set(CONCEPT_KEYS)
    assert out.concepts["face_tracking"] == "fail"
    assert out.concepts["availability"] == "fail"
    assert all(v in ("pass", "fail", "not_evaluated") for v in out.concepts.values())


def test_concepts_all_pass_on_clean_window():
    t = np.arange(int(12 * FS)) / FS
    out = assess_window(trace=trace_report(t), spectral=spectral_quality(pulse(), FS),
                        roi_coverage=0.9)
    assert out.status == "valid"
    assert out.concepts == {k: "pass" for k in CONCEPT_KEYS}


def test_concepts_roi_extraction_fails_below_coverage():
    t = np.arange(int(12 * FS)) / FS
    out = assess_window(trace=trace_report(t), spectral=spectral_quality(pulse(), FS),
                        roi_coverage=0.30)
    assert out.concepts["roi_extraction"] == "fail"
    assert out.concepts["availability"] == "fail"
    assert out.status == "low_signal_quality"
    assert any("insufficient_roi_coverage" in r for r in out.reasons)


def test_concepts_temporal_acquisition_fails_on_gap():
    t = np.arange(int(12 * FS)) / FS
    t = np.concatenate([t[t < 5], t[t > 7]])  # 2 s hole: exceeds the 0.25 s gap gate
    out = assess_window(trace=trace_report(t))
    assert out.status == "irregular_timestamps"
    assert out.concepts["temporal_acquisition"] == "fail"


def test_concepts_not_evaluated_when_not_applicable():
    out = assess_window(excessive_motion=True)
    assert out.concepts["pulse_signal"] == "fail"          # cannot be trusted mid-motion
    assert out.concepts["algorithm_agreement"] == "not_evaluated"  # never reaches agreement
    assert out.concepts["availability"] == "fail"
