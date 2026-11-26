"""Acquisition-integrity checks must be honest about what the camera delivered.

The rPPG estimators assume uniform sampling. A browser can duplicate frames,
stall, drop frames or deliver a rate too low to analyse; if that is not detected
the result is a confident-looking number computed from a signal that was not
recorded the way the estimator believes.

These are software tests on synthetic timestamps. They verify bookkeeping, not
physiology.
"""
from __future__ import annotations

import numpy as np
import pytest

from rppg_core.quality import (
    DUPLICATE_EPSILON_S,
    STALL_INTERVAL_MULTIPLE,
    MIN_SAMPLING_RATE_HZ,
    trace_report,
)


def regular(fs: float, seconds: float, t0: float = 0.0) -> np.ndarray:
    return t0 + np.arange(int(round(fs * seconds))) / fs


# ---------------------------------------------------------------------------
# regular capture
# ---------------------------------------------------------------------------
def test_regular_capture_reports_its_rate_and_is_usable():
    report = trace_report(regular(30, 10))
    assert report.n_samples == 300
    assert report.fs_hz == pytest.approx(30, rel=1e-6)
    assert report.max_gap_s == pytest.approx(1 / 30, rel=1e-6)
    assert report.regular is True
    assert report.has_duplicate_samples is False
    assert report.has_irregular_timing is False


def test_rate_below_the_analysable_floor_is_not_regular():
    report = trace_report(regular(8, 10))
    assert report.fs_hz == pytest.approx(8)
    assert report.fs_hz < MIN_SAMPLING_RATE_HZ
    assert report.regular is False


# ---------------------------------------------------------------------------
# duplicated samples (read loop faster than the sensor)
# ---------------------------------------------------------------------------
def test_duplicated_samples_are_detected_and_excluded_from_the_rate():
    base = regular(30, 5)
    times = np.sort(np.concatenate([base, base + DUPLICATE_EPSILON_S / 2]))
    report = trace_report(times)
    assert report.duplicate_interval_fraction == pytest.approx(0.5, abs=0.02)
    assert report.has_duplicate_samples is True
    # the rate must describe the real sensor rate, not collapse to zero
    assert report.fs_hz == pytest.approx(30, rel=0.05)
    assert report.regular is False


def test_equal_timestamps_are_rejected_rather_than_smoothed():
    """A clock that repeats exactly is a defect: report it, never repair it."""
    times = np.repeat(regular(30, 5), 2)
    report = trace_report(times)
    assert report.fs_hz is None
    assert report.regular is False


# ---------------------------------------------------------------------------
# gaps and stalls
# ---------------------------------------------------------------------------
def test_dropped_frame_gap_is_reported():
    times = regular(30, 10)
    times = times[(times < 4) | (times > 4.6)]
    report = trace_report(times)
    assert report.max_gap_s is not None and report.max_gap_s > 0.5
    assert report.dropped_interval_fraction and report.dropped_interval_fraction > 0
    assert report.regular is False


def test_single_stall_is_flagged_even_though_jitter_cv_stays_small():
    """One 120 ms stall in 300 samples barely moves the CV but breaks uniformity."""
    times = regular(30, 10) + np.where(np.arange(300) >= 150, 0.12, 0.0)
    report = trace_report(times)
    assert report.max_gap_s is not None and report.max_gap_s < 0.25
    assert report.stalled is True
    assert report.has_irregular_timing is True
    assert report.regular is False


def test_stall_threshold_is_documented_and_used():
    assert STALL_INTERVAL_MULTIPLE > 1.0
    times = regular(30, 4)
    # carve out a stall of exactly 3x the frame interval
    stall_at = 2.0
    times = times[(times < stall_at) | (times > stall_at + 3 / 30)]
    assert trace_report(times).stalled is True


# ---------------------------------------------------------------------------
# degenerate input
# ---------------------------------------------------------------------------
def test_single_sample_is_not_usable():
    report = trace_report([1.5])
    assert report.n_samples == 1
    assert report.fs_hz is None
    assert report.regular is False


def test_non_finite_timestamps_are_ignored():
    times = np.array([0.0, 1 / 30, np.nan, 3 / 30, 4 / 30, np.inf])
    report = trace_report(times)
    assert report.n_samples == 4
    assert report.fs_hz == pytest.approx(30, rel=0.05)


def test_empty_trace_is_not_usable():
    report = trace_report([])
    assert report.n_samples == 0
    assert report.regular is False


# ---------------------------------------------------------------------------
# the assessment consumes the timing verdict
# ---------------------------------------------------------------------------
def test_assess_window_marks_temporal_acquisition_failed_for_a_gap():
    from rppg_core.quality import assess_window

    times = regular(30, 12)
    times = times[(times < 4) | (times > 5.0)]
    assessment = assess_window(trace=trace_report(times), face_detected=True,
                               roi_coverage=0.9)
    assert assessment.concepts["temporal_acquisition"] == "fail"
    assert assessment.available is False


def test_assess_window_marks_duplicates_as_a_temporal_failure():
    from rppg_core.quality import assess_window

    base = regular(30, 12)
    times = np.sort(np.concatenate([base, base + DUPLICATE_EPSILON_S / 2]))
    assessment = assess_window(trace=trace_report(times), face_detected=True,
                               roi_coverage=0.9)
    assert assessment.concepts["temporal_acquisition"] == "fail"
    assert assessment.available is False


def test_clean_capture_passes_the_temporal_concept():
    from rppg_core.quality import assess_window

    assessment = assess_window(trace=trace_report(regular(30, 12)), face_detected=True,
                               roi_coverage=0.9)
    assert assessment.concepts["temporal_acquisition"] == "pass"


# ---------------------------------------------------------------------------
# browser/Python parity
# ---------------------------------------------------------------------------
PARITY_FIXTURE = "tests/fixtures/capture_integrity_cases.json"


def test_parity_fixture_matches_the_browser_module():
    """The same timestamps must yield the same verdict in Python and TypeScript.

    The browser is the acquisition layer for the live pathway and Python is the
    research pathway; if they disagree about whether a capture was regular, the
    two report different things about the same recording.
    """
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / PARITY_FIXTURE
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    assert cases, "the parity fixture must contain cases"

    for case in cases:
        report = trace_report(case["times"])
        expected = case["expected"]
        label = case["name"]
        if expected["median_fs_hz"] is None:
            assert report.fs_hz is None, label
        else:
            assert report.fs_hz == pytest.approx(expected["median_fs_hz"], rel=0.02), label
        assert report.regular is expected["regular"], label
        assert report.has_duplicate_samples is expected["has_duplicate_samples"], label
        assert report.has_irregular_timing is expected["has_irregular_timing"], label
