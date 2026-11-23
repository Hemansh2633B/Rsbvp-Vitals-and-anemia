"""Unit tests for the fair-comparison metrics module."""
import math

from research.backends import metrics


def test_error_metrics_known_values():
    pairs = [(60.0, 63.0), (70.0, 68.0), (80.0, 85.0)]
    result = metrics.error_metrics(pairs)
    assert result["n_pairs"] == 3
    assert result["mae_bpm"] == (3 + 2 + 5) / 3
    assert result["bias_bpm"] == (3 - 2 + 5) / 3
    assert math.isclose(result["rmse_bpm"], math.sqrt((9 + 4 + 25) / 3))
    assert result["loa_lower_95_bpm"] is not None
    assert result["within_5_bpm_fraction"] == 1.0
    assert result["within_3_bpm_fraction"] == 2 / 3


def test_error_metrics_empty():
    result = metrics.error_metrics([])
    assert result["n_pairs"] == 0
    assert result["mae_bpm"] is None
    assert result["loa_upper_95_bpm"] is None


def test_error_metrics_constant_series_has_no_pearson():
    result = metrics.error_metrics([(70.0, 70.0), (70.0, 71.0), (70.0, 69.0)])
    assert result["pearson_r"] is None  # zero reference variance must not invent a correlation


def test_availability_summary_counts_reasons():
    class FakeRecord:
        def __init__(self, bpm, quality, output_type="window"):
            self.estimated_hr_bpm = bpm
            self.signal_quality = quality
            self.backend_output_type = output_type
    records = [
        FakeRecord(70.0, "ok"),
        FakeRecord(None, "rejected:nonfinite_samples"),
        FakeRecord(None, "unavailable:flat_signal"),
        FakeRecord(None, "aggregate", "aggregate"),
    ]
    summary = metrics.availability_summary(records)
    assert summary["windows_total"] == 3
    assert summary["windows_with_estimate"] == 1
    assert summary["windows_rejected_or_unavailable"] == 2
    assert summary["rejection_or_unavailability_reasons"]["nonfinite_samples"] == 1


def test_participant_bootstrap_is_deterministic():
    participant_pairs = {
        "p1": [(70.0, 72.0), (72.0, 71.0), (74.0, 75.0)],
        "p2": [(66.0, 63.0), (68.0, 66.0), (65.0, 61.0)],
        "p3": [(80.0, 84.0), (82.0, 85.0)],
    }
    first = metrics.participant_bootstrap_mae(participant_pairs, n_boot=200, seed=42)
    second = metrics.participant_bootstrap_mae(participant_pairs, n_boot=200, seed=42)
    assert first == second
    assert first["mae_ci95_bpm"][0] <= first["mae_ci95_bpm"][1]


def test_window_key_format():
    assert metrics.window_key("rec", 1.23456) == "rec|1.235"
