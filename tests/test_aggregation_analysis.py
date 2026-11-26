"""Tests for the session-aggregation analysis (research/session/aggregation_analysis.py).

The analysis exists to decide whether the headline statistic (the all-window mean)
should change. These tests pin its methodology so a future edit cannot quietly
produce a more flattering comparison.

All scenarios are synthetic. Nothing here is evidence about real cameras or
physiology.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "aggregation_analysis", ROOT / "research" / "session" / "aggregation_analysis.py")
A = importlib.util.module_from_spec(_spec)
# Register before execution: dataclasses resolves annotations via sys.modules.
sys.modules[_spec.name] = A
_spec.loader.exec_module(A)


class TestNonOverlappingSelection:
    def test_selects_a_maximal_non_overlapping_set(self):
        starts = np.array([0.0, 5.0, 10.0, 15.0])
        ends = starts + 10.0
        chosen = A.non_overlapping_indices(starts, ends)
        assert chosen == [0, 2]

    def test_touching_windows_are_not_overlapping(self):
        starts = np.array([0.0, 10.0, 20.0])
        ends = starts + 10.0
        assert A.non_overlapping_indices(starts, ends) == [0, 1, 2]

    def test_empty_input_yields_empty_selection(self):
        assert A.non_overlapping_indices(np.array([]), np.array([])) == []


class TestTruthDefinition:
    def test_truth_is_time_weighted_not_reading_weighted(self):
        # This is the property that makes the comparison meaningful: averaging the
        # truth per reading would let a densely analysed stretch define the target,
        # which is the bias under test.
        session = A.simulate_session(
            duration_s=90.0, truth=60.0, drift_bpm_per_s=0.2, reading_sd=0.0, slow_after_s=40.0)
        reading_weighted = session["base_truth"] + session["drift_bpm_per_s"] * session["centres"].mean()
        time_weighted = A.mean_truth(session)
        # With a slow second half, the reading-weighted mean sits lower (earlier)
        # than the time-weighted mean.
        assert reading_weighted < time_weighted
        # And the time-weighted truth lands near the middle of the time span.
        assert abs(time_weighted - (60.0 + 0.2 * 45.0)) < 3.0


class TestEstimatorComparison:
    def test_estimators_agree_on_a_steady_session(self):
        session = A.simulate_session(**A.SCENARIOS["steady_60s"])
        estimates = A.compare(session, "steady_60s")
        all_window, non_overlapping = estimates[0].value, estimates[1].value
        assert abs(all_window - non_overlapping) < 1.0

    def test_plain_gap_does_not_bias_the_all_window_mean(self):
        # A rejected stretch leaves the remaining time uniformly covered, so an
        # equal-weight mean is still approximately unbiased. Documenting this
        # prevents "gaps cause bias" becoming folklore.
        session = A.simulate_session(**A.SCENARIOS["rejected_gap"])
        truth = A.mean_truth(session)
        estimates = A.compare(session, "rejected_gap")
        for estimate in estimates:
            assert abs(estimate.signed_error) < 1.5

    def test_uneven_density_with_drift_biases_the_all_window_mean(self):
        # The finding that motivates reporting density: when one stretch is
        # analysed far more often AND the value drifts, equal weighting per reading
        # over-weights the dense stretch.
        session = A.simulate_session(**A.SCENARIOS["uneven_density_with_drift"])
        estimates = A.compare(session, "uneven_density_with_drift")
        all_window, non_overlapping = estimates[0], estimates[1]
        assert abs(all_window.signed_error) > 2.0        # materially biased
        assert abs(non_overlapping.signed_error) < abs(all_window.signed_error)
        assert abs(all_window.value - non_overlapping.value) > 2.0

    def test_no_estimator_is_declared_better_in_general(self):
        # The analysis must not smuggle in a verdict: each scenario is reported,
        # and the module exposes both estimates side by side.
        report = A.run_all()
        assert set(report.keys()) >= {"scenarios", "outlier", "note"}
        for row in report["scenarios"]:
            assert {"all_window_mean", "non_overlapping_mean", "difference_bpm"} <= set(row)
        assert "synthetic" in report["note"].lower()


class TestAutocorrelation:
    def test_reports_high_autocorrelation_for_overlapping_windows(self):
        session = A.simulate_session(**A.SCENARIOS["drift_120s"])
        acf = A.lag1_autocorrelation(session["values"])
        # Neighbouring overlapping readings are near-duplicates.
        assert acf is not None and acf > 0.8

    def test_returns_none_when_undefined(self):
        assert A.lag1_autocorrelation(np.array([5.0])) is None
        assert A.lag1_autocorrelation(np.array([7.0, 7.0, 7.0])) is None


class TestOutlierSensitivity:
    def test_single_wild_reading_moves_the_mean_more_than_the_median(self):
        report = A.run_all()
        outlier = report["outlier"]
        mean_shift = abs(outlier["all_window_mean"] - outlier["non_overlapping_mean"])
        median_shift = abs(outlier["median_all"] - outlier["non_overlapping_mean"])
        assert mean_shift > 0
        # The median is the more robust summary; this is why both are displayed.
        assert abs(outlier["median_all"] - outlier["median_non_overlapping"]) < mean_shift


class TestReproducibility:
    def test_same_seed_gives_identical_results(self):
        first = A.run_all()
        second = A.run_all()
        assert first == second

    def test_report_is_json_serialisable(self):
        import json
        json.dumps(A.run_all())

    def test_no_confidence_interval_is_claimed(self):
        # The bootstrap interval is over windows and the docstrings say so; a
        # future edit that renames it a confidence interval must fail here.
        source = (ROOT / "research" / "session" / "aggregation_analysis.py").read_text(encoding="utf-8")
        assert "not a formal confidence interval" in source.lower()
        assert "bootstrap" in source.lower()
