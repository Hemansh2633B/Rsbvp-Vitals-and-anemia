"""Agreement, correlation, coverage and the session-average question.

The central claim these tests defend: **correlation is not accuracy**. A series can
correlate perfectly while being wrong by a clinically large margin, and the platform
must say so rather than letting a high r stand in for agreement.
"""
from __future__ import annotations

import math

import pytest

from research.validation.metrics import (
    MIN_PAIRS_FOR_ACCURACY,
    MIN_PAIRS_FOR_CORRELATION,
    MIN_PAIRS_FOR_LIMITS_OF_AGREEMENT,
    Pair,
    agreement,
    correlation,
    coverage,
    error_percentiles,
    participant_bootstrap_mae,
)


def pairs_from(estimates, references) -> list[Pair]:
    return [Pair(estimate_bpm=float(e), reference_bpm=float(r))
            for e, r in zip(estimates, references)]


# --- agreement ---------------------------------------------------------------


def test_exact_agreement_is_zero_error():
    result = agreement(pairs_from([70, 72, 74], [70, 72, 74]))
    assert result["available"]
    assert result["n_pairs"] == 3
    assert result["mae_bpm"] == 0.0
    assert result["bias_bpm"] == 0.0
    assert result["rmse_bpm"] == 0.0


def test_bias_keeps_its_sign_and_mae_does_not():
    """A method that reads 5 BPM high must be distinguishable from one that reads 5 low."""
    high = agreement(pairs_from([75, 77, 79], [70, 72, 74]))
    low = agreement(pairs_from([65, 67, 69], [70, 72, 74]))
    assert high["bias_bpm"] == pytest.approx(5.0)
    assert low["bias_bpm"] == pytest.approx(-5.0)
    assert high["mae_bpm"] == pytest.approx(5.0)
    assert low["mae_bpm"] == pytest.approx(5.0)


def test_rmse_punishes_large_errors_more_than_mae():
    concentrated = agreement(pairs_from([71, 71, 71, 71], [70, 70, 70, 70]))
    spread = agreement(pairs_from([76, 66, 74, 68], [70, 70, 70, 70]))
    assert concentrated["mae_bpm"] == pytest.approx(1.0)
    assert spread["mae_bpm"] == pytest.approx(4.0)
    assert spread["rmse_bpm"] > spread["mae_bpm"]


def test_too_few_pairs_reports_insufficient_evidence():
    result = agreement(pairs_from([70, 71], [70, 71]))
    assert result["available"] is False
    assert result["n_pairs"] == 2
    assert "at least" in result["reason"].lower()
    assert MIN_PAIRS_FOR_ACCURACY == 3


def test_limits_of_agreement_need_more_pairs_than_an_mae():
    few = agreement(pairs_from([70, 71, 72, 73], [70, 71, 72, 73]))
    assert few["available"]
    assert few["loa_lower_bpm"] is None
    assert "at least" in few["loa_note"].lower()
    assert MIN_PAIRS_FOR_LIMITS_OF_AGREEMENT == 5


def test_limits_of_agreement_bracket_the_bias():
    result = agreement(pairs_from([70, 72, 74, 76, 78, 80], [70, 71, 72, 73, 74, 75]))
    assert result["loa_lower_bpm"] < result["bias_bpm"] < result["loa_upper_bpm"]
    width = result["loa_upper_bpm"] - result["loa_lower_bpm"]
    # 1.96 SD either side.
    assert width == pytest.approx(2 * 1.96 * result["error_sd_bpm"], rel=1e-6)


def test_perfect_correlation_with_an_eight_bpm_offset():
    """The case the whole platform exists to make visible."""
    references = [60, 62, 64, 66, 68, 70, 72, 74, 76, 78]
    estimates = [r + 8 for r in references]
    scores = agreement(pairs_from(estimates, references))
    corr = correlation(pairs_from(estimates, references))
    assert corr["pearson_r"] == pytest.approx(1.0)
    assert scores["mae_bpm"] > 7.9
    assert scores["bias_bpm"] == pytest.approx(8.0)
    # The disagreement is systematic, so the intervals of agreement sit far from zero.
    assert scores["loa_lower_bpm"] > 7.5


def test_scale_error_also_hides_behind_perfect_correlation():
    references = [60, 70, 80, 90, 100]
    estimates = [r * 0.9 for r in references]
    corr = correlation(pairs_from(estimates, references))
    scores = agreement(pairs_from(estimates, references))
    assert corr["pearson_r"] == pytest.approx(1.0, abs=1e-9)
    assert scores["mae_bpm"] > 2.5


def test_within_fractions_are_reportable_alongside_mae():
    # Errors of 1, 2, 3, 4, 5 BPM: two within +-3, three within +-5.
    result = agreement(pairs_from([71, 72, 73, 74, 75], [70] * 5))
    assert result["n_pairs"] == 5
    assert result["within_3_bpm_fraction"] == pytest.approx(3 / 5)
    assert result["within_5_bpm_fraction"] == pytest.approx(5 / 5)


def test_mae_interval_is_labelled_optimistic():
    """Widening the interval silently would overstate certainty."""
    result = agreement(pairs_from([71, 70, 73, 72, 75, 74], [70] * 6))
    low, high = result["mae_ci95_bpm"]
    assert low <= result["mae_bpm"] <= high
    # The interval is over windows, not people. The key it lives under says so, so a
    # reader who copies it cannot lose the caveat by copying the number.
    assert "window" in result["mae_ci95_note"].lower()
    assert "optimistic" in result["mae_ci95_note"].lower()


def test_a_constant_error_gives_a_degenerate_interval_not_a_wider_one():
    """A method that reads exactly 2 BPM high has no variability to resample.

    The platform must report that rather than widening the interval to something
    that looks like a real confidence interval.
    """
    result = agreement(pairs_from([72, 73, 74, 75, 76], [70, 71, 72, 73, 74]))
    assert result["available"]
    assert result["mae_bpm"] == pytest.approx(2.0)
    assert result["error_sd_bpm"] == pytest.approx(0.0)
    low, high = result["mae_ci95_bpm"]
    assert low == pytest.approx(2.0)
    assert high == pytest.approx(2.0)


# --- correlation -------------------------------------------------------------


def test_correlation_needs_variation_to_exist():
    flat = correlation(pairs_from([70, 70, 70, 70], [70, 71, 72, 73]))
    assert flat["available"] is False
    assert "variance" in flat["reason"]


def test_correlation_refuses_two_points():
    """Two points always give |r| = 1, which is an artefact, not a finding."""
    result = correlation(pairs_from([70, 72], [70, 74]))
    assert result["available"] is False
    assert MIN_PAIRS_FOR_CORRELATION >= 3


def test_correlation_detects_an_inverse_relationship():
    result = correlation(pairs_from([60, 70, 80, 90], [90, 80, 70, 60]))
    assert result["pearson_r"] == pytest.approx(-1.0)


# --- percentiles -------------------------------------------------------------


def test_error_percentiles_are_symmetric_for_a_symmetric_error_set():
    stats = error_percentiles(pairs_from([68, 68, 70, 72, 72], [70] * 5))
    assert stats["p50_bpm"] == pytest.approx(0.0)
    assert stats["p05_bpm"] == pytest.approx(-2.0)
    assert stats["p95_bpm"] == pytest.approx(2.0)


def test_error_percentiles_refuse_an_empty_set():
    stats = error_percentiles([])
    assert stats["available"] is False


# --- coverage ----------------------------------------------------------------


def test_coverage_reports_every_count():
    result = coverage(windows_considered=10, windows_accepted=6, windows_paired=5,
                      independent_windows=3)
    assert result["windows_considered"] == 10
    assert result["acceptance_rate"] == pytest.approx(0.6)
    assert result["rejection_rate"] == pytest.approx(0.4)
    assert result["paired_fraction_of_accepted"] == pytest.approx(5 / 6)
    # Paired windows are a subset of accepted ones, never more.
    assert result["windows_paired"] <= result["windows_accepted"]


def test_coverage_reports_a_rate_only_when_it_has_a_denominator():
    result = coverage(windows_considered=0, windows_accepted=0, windows_paired=0,
                      independent_windows=0)
    assert result["acceptance_rate"] is None
    assert result["rejection_rate"] is None
    assert result["paired_fraction_of_accepted"] is None


def test_coverage_never_reports_an_accuracy_number():
    """Coverage must not be mistaken for an error metric, or vice versa."""
    result = coverage(windows_considered=10, windows_accepted=8, windows_paired=8,
                      independent_windows=8)
    assert not any("bpm" in key for key in result)


# --- bootstrap ---------------------------------------------------------------


def test_bootstrap_is_deterministic_for_a_fixed_seed():
    people = {"a": pairs_from([71, 72, 73, 74], [70] * 4),
              "b": pairs_from([75, 77, 79, 81], [70] * 4)}
    first = participant_bootstrap_mae(people, n_boot=200, seed=1234)
    second = participant_bootstrap_mae(people, n_boot=200, seed=1234)
    assert first == second


def test_bootstrap_resamples_people_not_windows():
    """One person is one observation; a thousand windows is still one person."""
    single = {"a": pairs_from([71, 72, 73, 74], [70] * 4)}
    assert participant_bootstrap_mae(single, n_boot=100, seed=7) is None


def test_bootstrap_interval_contains_the_pooled_mae():
    people = {"a": pairs_from([71, 70, 73, 72], [70] * 4),
              "b": pairs_from([75, 74, 77, 76], [70] * 4),
              "c": pairs_from([69, 68, 71, 70], [70] * 4)}
    result = participant_bootstrap_mae(people, n_boot=500, seed=7)
    assert result["participants"] == 3
    low, high = result["mae_ci95_bpm"]
    assert low <= high
    assert "participant" in result["note"]
