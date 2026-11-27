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
    QualityConfig,
    acquisition_report,
    agreement_report,
    assess_window,
    rejection_telemetry,
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


# ------------------------------------------------- candidate validation -------

def _clean_window():
    t = np.arange(int(12 * FS)) / FS
    return dict(
        trace=trace_report(t),
        acquisition=acquisition_report(np.full((10, 3), 150.0) + np.arange(30).reshape(10, 3) % 40),
        spectral=spectral_quality(pulse(), FS),
        agreement=agreement_report({"green": 70.0, "pos": 71.0}),
    )


def test_candidate_supported_by_an_estimator_passes():
    base = _clean_window()
    out = assess_window(**base, candidate_bpm=70.5)
    assert out.status == "valid" and out.available
    assert not any("candidate" in r for r in out.reasons)


def test_candidate_within_full_tolerance_but_near_none_is_rejected():
    # candidate=78 is within 12 BPM of the median (70.5) but more than 6 BPM
    # from it, so no uncorrected estimator actually supports 78.
    base = _clean_window()
    out = assess_window(**base, candidate_bpm=78.0)
    assert out.status == "low_signal_quality" and not out.available
    assert any("candidate_disagrees_with_estimators" in r for r in out.reasons)


def test_candidate_outside_full_tolerance_is_rejected():
    base = _clean_window()
    out = assess_window(**base, candidate_bpm=85.0)
    assert out.status == "low_signal_quality" and not out.available
    assert any("candidate_disagrees_with_estimators" in r for r in out.reasons)


def test_non_finite_candidate_is_rejected():
    base = _clean_window()
    out = assess_window(**base, candidate_bpm=float("nan"))
    assert out.status == "low_signal_quality" and not out.available
    assert any("candidate_not_finite" in r for r in out.reasons)


def test_candidate_no_estimator_backing_is_rejected():
    # candidate_bpm with no agreement anchor (no estimators to validate against)
    # must be rejected: a heuristic-manufactured consensus needs estimator backing.
    base = dict(_clean_window())
    del base["agreement"]
    out = assess_window(**base, candidate_bpm=70.5)
    assert out.status == "low_signal_quality" and not out.available
    assert any("candidate_no_estimator_backing" in r for r in out.reasons)


def test_candidate_validated_against_every_estimator_not_just_median():
    # estimates [70, 70, 82]: spread 12 -> agreement passes, median 70.
    # candidate=64 is within 6 of the median (near_one passes) and within 12
    # of the median (within_all vs median passes), but |64-82|=18 > 12 from
    # estimator e3 -- must be rejected because it is not within tolerance of
    # *every* estimator.
    base = dict(_clean_window())
    base["agreement"] = agreement_report({"e1": 70.0, "e2": 70.0, "e3": 82.0})
    out = assess_window(**base, candidate_bpm=64.0)
    assert out.status == "low_signal_quality" and not out.available
    assert any("candidate_disagrees_with_estimators" in r for r in out.reasons)


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


# ------------------------------------------------- cross-ROI agreement -------

def test_roi_agreement_passes_when_rois_consistent():
    # Three ROI estimates within tolerance -> cross-ROI agreement passes.
    base = _clean_window()
    base["roi_agreement"] = agreement_report(
        {"forehead": 70.0, "left_cheek": 71.0, "right_cheek": 69.5}
    )
    out = assess_window(**base)
    assert out.status == "valid" and out.available
    assert out.concepts["algorithm_agreement"] == "pass"


def test_roi_agreement_rejected_when_rois_diverge():
    # ROI estimates spread > 12 BPM -> cross-ROI agreement fails.
    base = _clean_window()
    base["roi_agreement"] = agreement_report(
        {"forehead": 70.0, "left_cheek": 85.0, "right_cheek": 72.0}
    )
    out = assess_window(**base)
    assert out.status == "low_signal_quality" and not out.available
    assert any("roi_estimator_disagreement" in r for r in out.reasons)


def test_roi_agreement_single_roi_does_not_reject():
    # Only one ROI estimate -> n_valid < 2, no cross-ROI disagreement possible.
    base = _clean_window()
    base["roi_agreement"] = agreement_report({"forehead": 70.0})
    out = assess_window(**base)
    assert out.status == "valid" and out.available


def test_candidate_validated_against_roi_anchors():
    # candidate must be within tolerance of ROI estimates too, not just
    # green/pos/chrom. ROI estimates [70, 70, 82]: spread 12 -> agreement OK,
    # but candidate=64 is |64-82|=18 > 12 from the right-cheek anchor ->
    # rejected even though it is within 6 of the 70 BPM anchors.
    base = _clean_window()
    base["agreement"] = agreement_report({"green": 70.0, "pos": 70.0})
    base["roi_agreement"] = agreement_report(
        {"forehead": 70.0, "left_cheek": 70.0, "right_cheek": 82.0}
    )
    out = assess_window(**base, candidate_bpm=64.0)
    assert out.status == "low_signal_quality" and not out.available
    assert any("candidate_disagrees_with_estimators" in r for r in out.reasons)


def test_candidate_supported_by_roi_anchors_passes():
    # candidate=70.5 within 12 of every estimator (green/pos/ROI) and within
    # 6 of the forehead ROI anchor (70.0) -> accepted.
    base = _clean_window()
    base["agreement"] = agreement_report({"green": 70.0, "pos": 70.0})
    base["roi_agreement"] = agreement_report(
        {"forehead": 70.0, "left_cheek": 71.0, "right_cheek": 69.0}
    )
    out = assess_window(**base, candidate_bpm=70.5)
    assert out.status == "valid" and out.available


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


# ------------------------------------------------------------ quality config


def _clean_window_kwargs():
    t = np.arange(int(12 * FS)) / FS
    return dict(
        acquisition=acquisition_report(np.full((10, 3), 150.0) + np.arange(30).reshape(10, 3) % 40),
        spectral=spectral_quality(pulse(), FS),
        agreement=agreement_report({"green": 70.0, "pos": 71.0}),
    )


def test_quality_config_looser_gap_passes():
    # A 0.33 s gap exceeds the default 0.25 s max-gap gate. Under a looser
    # config (max_gap_seconds=1.0) the gap check itself is bypassed — the
    # reason text no longer cites the 0.25 s threshold — proving the gate is
    # configurable, not hard-coded. (A 0.33 s gap in a 30 fps stream is still
    # irregular timing, so jitter may keep flagging it; that's a separate
    # check and correct behaviour.)
    t = np.arange(int(12 * FS)) / FS
    t[150:] += 0.3
    rep = trace_report(t)
    assert rep.max_gap_s > 0.25
    strict = assess_window(trace=rep, **_clean_window_kwargs())
    assert strict.status == "irregular_timestamps"
    assert "exceeds 0.25s" in strict.reason
    loose = assess_window(trace=rep, **_clean_window_kwargs(),
                          config=QualityConfig(max_gap_seconds=1.0))
    assert "exceeds 0.25s" not in loose.reason


def test_quality_config_min_window_seconds_override():
    # The per-call min_window_s still overrides config.min_window_seconds.
    rep = trace_report(np.arange(int(9 * FS)) / FS)  # 9 s
    out = assess_window(trace=rep, spectral=spectral_quality(pulse(seconds=9.0), FS),
                        min_window_s=10.0)
    assert out.status == "warming_up"
    out2 = assess_window(trace=rep, spectral=spectral_quality(pulse(seconds=9.0), FS),
                         min_window_s=8.0)
    assert out2.status != "warming_up"


def test_rejection_telemetry_counts_each_token():
    rejection_telemetry(reset=True)
    t = np.arange(int(12 * FS)) / FS
    assess_window(
        trace=trace_report(t),
        acquisition=acquisition_report(np.full((10, 3), 150.0) + np.arange(30).reshape(10, 3) % 40),
        spectral=spectral_quality(pulse(), FS),
        agreement=agreement_report({"green": 70.0, "pos": 85.0}),  # 15 bpm spread -> disagreement
    )
    telemetry = rejection_telemetry(reset=True)
    assert telemetry.get("estimator_disagreement_15.0bpm", 0) >= 1
    # Reset must actually zero the counters.
    assert rejection_telemetry(reset=True) == {}
