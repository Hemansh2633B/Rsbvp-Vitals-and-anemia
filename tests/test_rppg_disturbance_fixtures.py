"""Regression tests on deterministic RGB disturbance fixtures.

The repository had one *clean* synthetic fixture. These tests cover the hard
case: signals that look plausible but must not be accepted. Each fixture isolates
one documented failure mode (see
``tests/fixtures/generate_rppg_disturbance_fixtures.py``).

Evidence category: TESTED-FIXTURE. These traces are synthetic software input.
They show that the gates behave as designed; they say nothing about accuracy on
real skin, real lighting or real motion, and no number here may be quoted as a
measurement result.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rppg_core import quality as Q
from rppg_core.pipeline import bandpass_filter

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "rppg_disturbance_manifest.json").read_text(encoding="utf-8"))
ROIS = tuple(MANIFEST["rois"])


def load(name: str) -> dict[str, np.ndarray]:
    """Load one fixture as {column: float array}; absent samples become NaN."""
    import csv

    path = FIXTURES / MANIFEST["fixtures"][name]["file"]
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    columns: dict[str, np.ndarray] = {}
    for key in rows[0]:
        columns[key] = np.array([float(row[key]) if row[key] else np.nan for row in rows])
    return columns


def roi_trace(columns: dict[str, np.ndarray], roi: str) -> tuple[np.ndarray, np.ndarray]:
    """Timestamps and green channel for one ROI, with absent samples removed."""
    green = columns[f"{roi}_g"]
    keep = np.isfinite(green)
    return columns["timestamp_s"][keep], green[keep]


def assess(columns: dict[str, np.ndarray], roi: str = "forehead"):
    t, green = roi_trace(columns, roi)
    fs = 1.0 / float(np.median(np.diff(t)))
    spectral = Q.spectral_quality(bandpass_filter(green, fs), fs)
    rgb = np.stack([np.nan_to_num(columns[f"{roi}_{c}"]) for c in "rgb"], axis=1)
    return Q.assess_window(
        trace=Q.trace_report(t),
        acquisition=Q.acquisition_report(rgb),
        spectral=spectral,
        roi_coverage=float(np.isfinite(columns[f"{roi}_g"]).mean()),
        age_s=float(t[-1] - t[0]),
    ), spectral


# ---------------------------------------------------------------------------
# the fixtures themselves
# ---------------------------------------------------------------------------
def test_every_documented_fixture_exists_and_loads():
    assert len(MANIFEST["fixtures"]) == 8
    for name, meta in MANIFEST["fixtures"].items():
        columns = load(name)
        assert "timestamp_s" in columns
        assert np.isfinite(columns["timestamp_s"]).all(), name
        assert np.all(np.diff(columns["timestamp_s"]) > 0), name
        assert (FIXTURES / meta["file"]).is_file()
        assert meta["description"], "each fixture must document what it contains"


def test_fixtures_are_deterministic():
    """Re-running the generator must reproduce the committed files byte for byte."""
    import subprocess
    import sys

    before = {p.name: p.read_bytes() for p in FIXTURES.glob("rppg_disturbance_*.csv")}
    subprocess.run([sys.executable, str(FIXTURES / "generate_rppg_disturbance_fixtures.py")],
                   check=True, capture_output=True)
    for name, payload in before.items():
        assert (FIXTURES / name).read_bytes() == payload, f"{name} is not reproducible"


# ---------------------------------------------------------------------------
# the clean baseline must still pass
# ---------------------------------------------------------------------------
def test_clean_fixture_is_accepted():
    assessment, spectral = assess(load("clean_72bpm"))
    assert assessment.status == "valid"
    assert assessment.available is True
    assert spectral.peak_hz == pytest.approx(1.2, abs=0.05)


# ---------------------------------------------------------------------------
# each disturbance must be rejected, for the documented reason
# ---------------------------------------------------------------------------
def test_competing_pulse_is_rejected_for_weak_peak_separation():
    assessment, spectral = assess(load("second_pulse_competing"))
    assert assessment.status == "low_signal_quality"
    assert spectral.separation_ratio is not None and spectral.separation_ratio < Q.SPECTRAL_MIN_SEPARATION
    assert any("separation" in reason for reason in assessment.reasons)


def test_noise_without_a_pulse_fails_concentration():
    assessment, spectral = assess(load("no_pulse_noise"))
    assert assessment.status == "low_signal_quality"
    assert spectral.peak_fraction < Q.SPECTRAL_MIN_CONCENTRATION
    assert any("concentration" in reason for reason in assessment.reasons)


def test_saturated_channels_fail_the_acquisition_check():
    load_columns = load("clipped_channels")
    rgb = np.stack([np.nan_to_num(load_columns[f"forehead_{c}"]) for c in "rgb"], axis=1)
    report = Q.acquisition_report(rgb)
    assert report.clip_fraction > Q.CLIP_MAX_FRACTION
    assert report.passing is False
    assessment, _ = assess(load_columns)
    assert assessment.status == "low_signal_quality"
    assert "acquisition_clipping_or_flat" in assessment.reasons


def test_flat_green_channel_leaves_no_spectral_peak():
    assessment, spectral = assess(load("flat_channel"))
    assert assessment.status == "low_signal_quality"
    assert spectral.peak_hz is None or spectral.passing is False


def test_illumination_step_does_not_produce_a_clean_measurement():
    assessment, _spectral = assess(load("illumination_step"))
    assert assessment.status != "valid", "a 22-count brightness step must not pass as clean"


def test_motion_burst_is_not_accepted_as_a_clean_measurement():
    assessment, _spectral = assess(load("motion_burst"))
    assert assessment.status != "valid"


# ---------------------------------------------------------------------------
# per-ROI accounting
# ---------------------------------------------------------------------------
def test_missing_roi_samples_are_reflected_in_per_roi_coverage():
    columns = load("missing_roi_samples")
    coverage = {roi: float(np.isfinite(columns[f"{roi}_g"]).mean()) for roi in ROIS}
    assert coverage["left_cheek"] == pytest.approx(0.648, abs=0.01)
    assert coverage["forehead"] == pytest.approx(1.0)
    assert coverage["right_cheek"] == pytest.approx(1.0)


def test_a_roi_below_the_coverage_gate_fails_extraction():
    columns = load("missing_roi_samples")
    # Drop even more of the left cheek so the ROI itself falls below the gate.
    green = columns["left_cheek_g"].copy()
    green[: int(0.6 * green.size)] = np.nan
    columns["left_cheek_g"] = green
    coverage = float(np.isfinite(green).mean())
    assert coverage < Q.MIN_ROI_COVERAGE
    assessment, _ = assess(columns, roi="left_cheek")
    assert assessment.concepts["roi_extraction"] == "fail"
    assert assessment.status != "valid"


def test_rois_are_evaluated_independently():
    """A defect confined to one ROI must not be hidden by the other two."""
    columns = load("clean_72bpm")
    assert assess(columns, roi="forehead")[0].status == "valid"
    assert assess(columns, roi="left_cheek")[0].status == "valid"
    broken = dict(columns)
    broken["right_cheek_g"] = np.full_like(columns["right_cheek_g"], 120.0)
    assert assess(broken, roi="right_cheek")[0].status != "valid"
    # ... and the untouched ROIs are unaffected
    assert assess(broken, roi="forehead")[0].status == "valid"
