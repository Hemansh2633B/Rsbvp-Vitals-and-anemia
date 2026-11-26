"""Session aggregation (Python pathway).

Mirrors gui/frontend/src/rppg/sessionAggregate.test.ts. Synthetic readings only:
these tests prove the arithmetic and the acceptance rules, not physiological
accuracy, and no dataset is involved.
"""
from __future__ import annotations

import math

import pytest

from rppg_core import session as S

NOW = 1_767_000_000_000.0


def reading(value=72.0, *, metric="heart_rate", algorithm=S.CONSENSUS, verdict="valid",
            reason=None, start=0.0, quality=0.6, analyzed_at=NOW, elapsed=None):
    return S.Reading(
        metric=metric, value=value, algorithm=algorithm, roi="all",
        quality_score=quality, quality_verdict=verdict, fs_hz=30.0, n_samples=300,
        window_start_s=start, window_end_s=start + 10.0, rejection_reason=reason,
        analyzed_at_ms=analyzed_at, session_elapsed_s=elapsed if elapsed is not None else start,
        window_index=int(start // 10),
    )


def collect(values, **kwargs):
    """One reading per non-overlapping 10 s window."""
    c = S.SessionCollector()
    for i, v in enumerate(values):
        r = reading(v, start=i * 10.0, analyzed_at=NOW + i * 10_000.0, **kwargs)
        c.add(r, now_ms=r.analyzed_at_ms)
    return c


class TestAcceptanceRules:
    def test_accepts_valid_finite_plausible(self):
        assert S.classify_reading(reading()) == (True, None)

    def test_rejects_failed_verdict_and_keeps_the_pipeline_reason(self):
        ok, reason = S.classify_reading(
            reading(verdict="low_signal_quality", reason="spectral concentration below 20%"))
        assert not ok and reason == "spectral concentration below 20%"

    def test_rejects_missing_estimate_instead_of_zero_filling(self):
        ok, reason = S.classify_reading(
            reading(value=None, verdict="roi_lost", reason="All skin ROIs are lost"))
        assert not ok and reason == "All skin ROIs are lost"

    def test_flags_valid_verdict_without_a_number_as_a_contract_violation(self):
        assert S.classify_reading(reading(value=None))[1] == "valid_verdict_without_estimate"

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_is_missing_not_a_value(self, value):
        assert S.classify_reading(reading(value=value))[1] == "valid_verdict_without_estimate"

    def test_rejects_stale_reading_describing_a_moment_already_past(self):
        r = reading()
        assert S.classify_reading(r, now_ms=r.analyzed_at_ms + S.DEFAULT_CONFIG.stale_after_ms + 1) == (
            False, "stale_reading")

    @pytest.mark.parametrize("value", [0.0, 3.0, 900.0, -72.0])
    def test_rejects_implausible_values_as_data_errors(self, value):
        assert S.classify_reading(reading(value=value))[1].startswith("implausible_value")

    def test_rejects_unknown_metric(self):
        assert S.classify_reading(reading(metric="spo2"))[1] == "unsupported_metric:spo2"

    def test_hrv_and_anemia_metrics_are_explicitly_not_aggregated(self):
        for key in ("rmssd", "sdnn", "spo2", "hemoglobin"):
            assert key in S.NOT_AGGREGATED
        assert "anemia" in S.NOT_AGGREGATED["hemoglobin"].lower()


class TestArithmetic:
    def test_mean_and_median_of_accepted_only(self):
        a = S.summarize(collect([60, 70, 80, 90, 100]).readings, "heart_rate")
        assert a.verdict == "available"
        assert a.mean == 80 and a.median == 80
        assert (a.min, a.max, a.range) == (60, 100, 40)
        # Sample SD (n-1), not population SD.
        assert a.sd == pytest.approx(15.811388, abs=1e-6)

    def test_even_count_median_is_the_middle_pair_mean(self):
        assert S.summarize(collect([60, 70, 80, 90]).readings, "heart_rate").median == 75

    def test_median_is_none_not_zero_without_accepted_readings(self):
        a = S.summarize(collect([None, None]).readings, "heart_rate")
        assert a.median is None and a.mean is None and a.verdict == "insufficient"

    def test_rejected_readings_are_counted_but_never_averaged(self):
        c = S.SessionCollector()
        for i, v in enumerate([70, 72, 74, 76, 78]):
            r = reading(v, start=i * 10.0, analyzed_at=NOW + i * 10_000.0)
            c.add(r, now_ms=r.analyzed_at_ms)
        bad = reading(200, verdict="low_signal_quality", reason="low SNR",
                      start=50.0, analyzed_at=NOW + 50_000.0)
        c.add(bad, now_ms=bad.analyzed_at_ms)
        a = S.summarize(c.readings, "heart_rate")
        assert a.mean == 74                       # outlier excluded by the gate
        assert (a.n_accepted, a.n_rejected, a.n_total) == (5, 1, 6)
        assert a.acceptance_pct == pytest.approx(83.333, abs=1e-2)

    def test_mean_moves_with_an_outlier_median_does_not(self):
        a = S.summarize(collect([70, 70, 70, 70, 150]).readings, "heart_rate")
        assert a.mean == 86 and a.median == 70

    def test_single_accepted_reading_has_no_reported_spread(self):
        a = S.summarize(collect([72]).readings, "heart_rate")
        assert a.sd is None and a.min == a.max == 72


class TestInsufficientData:
    def test_below_threshold_is_insufficient_not_a_number(self):
        a = S.summarize(collect([72, 73, 74]).readings, "heart_rate")
        assert a.verdict == "insufficient"
        assert "at least 5" in a.reason
        assert a.mean == 73          # visible in details, never presented as the result

    def test_overlapping_windows_are_insufficient_regardless_of_count(self):
        c = S.SessionCollector()
        for i in range(6):
            r = reading(72, start=100.0, analyzed_at=NOW + i * 1000.0)
            c.add(r, now_ms=r.analyzed_at_ms)
        a = S.summarize(c.readings, "heart_rate")
        assert a.n_accepted == 6 and a.n_independent_accepted == 1
        assert a.verdict == "insufficient" and "independent" in a.reason

    def test_thresholds_are_configurable(self):
        config = S.AggregationConfig(min_accepted_readings=2, min_independent_windows=2)
        a = S.summarize(collect([70, 72]).readings, "heart_rate", config=config)
        assert a.verdict == "available"

    def test_no_readings_state_is_distinct_from_insufficient(self):
        a = S.summarize([], "heart_rate")
        assert a.verdict == "no_readings" and a.mean is None
        assert S.summarize_session([])["completion"] == "idle"


class TestMetricSeparation:
    def test_heart_rate_and_respiratory_rate_are_never_combined(self):
        c = S.SessionCollector()
        for i in range(6):
            for metric, value in (("heart_rate", 72 + i), ("respiratory_rate", 15 + i)):
                r = reading(value, metric=metric, start=i * 10.0, analyzed_at=NOW + i * 10_000.0)
                c.add(r, now_ms=r.analyzed_at_ms)
        summary = S.summarize_session(c.readings)
        hr = next(a for a in summary["metrics"] if a.metric == "heart_rate")
        rr = next(a for a in summary["metrics"] if a.metric == "respiratory_rate")
        assert (hr.unit, rr.unit) == ("BPM", "br/min")
        assert hr.mean == 74.5 and rr.mean == 17.5

    def test_respiratory_band_comes_from_its_own_spec(self):
        # 72 is plausible for heart rate and impossible for breathing; if the
        # bounds were shared, this reading would be wrongly accepted.
        c = S.SessionCollector()
        r = reading(72, metric="respiratory_rate")
        c.add(r, now_ms=r.analyzed_at_ms)
        a = S.summarize(c.readings, "respiratory_rate")
        assert (a.n_accepted, a.n_rejected) == (0, 1)

    def test_algorithms_stay_separate_and_no_consensus_is_invented(self):
        c = S.SessionCollector()
        for i in range(6):
            for algorithm, value in (("green", 70), ("pos", 90)):
                r = reading(value, algorithm=algorithm, start=i * 10.0, analyzed_at=NOW + i * 10_000.0)
                c.add(r, now_ms=r.analyzed_at_ms)
        summary = S.summarize_session(c.readings)
        by_alg = {a.algorithm: a for a in summary["per_algorithm"]}
        assert by_alg["green"].mean == 70 and by_alg["pos"].mean == 90
        consensus = next(a for a in summary["metrics"] if a.metric == "heart_rate")
        assert consensus.n_total == 0 and consensus.mean is None
        assert summary["has_result"] is False


class TestIndependence:
    def test_sliding_windows_count_far_fewer_independent_observations(self):
        c = S.SessionCollector()
        for k in range(51):  # 10 s window re-analysed every 1 s for 60 s
            r = reading(72, start=float(k), analyzed_at=NOW + k * 1000.0)
            c.add(r, now_ms=r.analyzed_at_ms)
        a = S.summarize(c.readings, "heart_rate")
        assert a.n_accepted == 51
        assert a.n_independent_accepted == 6
        assert a.overlap_factor == pytest.approx(8.5, abs=1e-6)

    def test_standard_error_uses_independent_subset(self):
        values = [70, 72, 74, 76, 78, 80]
        a = S.summarize(collect(values).readings, "heart_rate")
        assert a.n_independent_accepted == 6
        assert a.standard_error == pytest.approx(a.sd / math.sqrt(6))

    def test_standard_error_is_none_without_independence(self):
        c = S.SessionCollector()
        for i in range(6):
            r = S.Reading(metric="heart_rate", value=72.0, algorithm=S.CONSENSUS, roi="all",
                          quality_score=0.6, quality_verdict="valid", fs_hz=None, n_samples=None,
                          window_start_s=None, window_end_s=None, rejection_reason=None,
                          analyzed_at_ms=NOW + i * 1000.0, session_elapsed_s=None)
            c.add(r, now_ms=r.analyzed_at_ms)
        a = S.summarize(c.readings, "heart_rate")
        assert a.n_independent_accepted is None and a.standard_error is None

    def test_touching_windows_are_independent_overlapping_ones_are_not(self):
        rs = [reading(70, start=0.0), reading(71, start=10.0), reading(72, start=15.0)]
        assert S.count_independent_windows(rs) == 2


class TestHistoryAndReset:
    def test_aggregation_never_overwrites_history(self):
        c = collect([70, 72])
        before = [m.value for m in c.readings]
        S.summarize(c.readings, "heart_rate")
        assert [m.value for m in c.readings] == before

    def test_rejected_readings_are_kept_with_their_reason(self):
        c = S.SessionCollector()
        c.add(reading(70), now_ms=NOW)
        c.add(reading(None, verdict="roi_lost", reason="All skin ROIs are lost"), now_ms=NOW)
        rejected = c.rejected()
        assert len(rejected) == 1
        assert rejected[0].final_rejection_reason == "All skin ROIs are lost"
        assert rejected[0].value is None

    def test_reset_clears_history_and_restarts_ids(self):
        c = collect([70, 72, 74])
        c.reset()
        assert len(c) == 0 and c.readings == []
        assert c.add(reading(70), now_ms=NOW).id == 1


class TestCompletion:
    def test_completion_requires_the_target_and_not_before(self):
        assert S.summarize_session(collect([72] * 4).readings)["completion"] == "collecting"
        done = S.summarize_session(collect([72] * S.DEFAULT_CONFIG.target_accepted_readings).readings)
        assert done["completion"] == "complete"
        assert "stop the camera" in done["completion_reason"]

    def test_progress_message_counts_accepted_readings_below_the_average_threshold(self):
        # Regression: with 1-4 accepted readings the summary used to claim
        # "Waiting for readings that pass the quality checks", which was false -
        # readings had passed, there were just not enough of them yet.
        summary = S.summarize_session(collect([72, 73]).readings)
        assert summary["completion"] == "collecting"
        assert "2 of 8 accepted readings collected" in summary["completion_reason"]

    def test_progress_message_is_honest_when_everything_was_rejected(self):
        c = S.SessionCollector()
        for i in range(3):
            c.add(reading(None, verdict="roi_lost", reason="All skin ROIs are lost", start=i * 10.0),
                  now_ms=NOW)
        summary = S.summarize_session(c.readings)
        assert "No readings accepted yet (3 rejected" in summary["completion_reason"]

    def test_acceptance_band_reflects_observed_acceptance_only(self):
        c = S.SessionCollector()
        for i in range(5):
            c.add(reading(72, start=i * 10.0), now_ms=NOW)
        for i in range(5):
            c.add(reading(200, verdict="low_signal_quality", reason="low SNR", start=50.0 + i * 10),
                  now_ms=NOW)
        summary = S.summarize_session(c.readings)
        assert summary["acceptance_pct"] == 50.0
        assert summary["acceptance_band"] == "fair"


class TestExports:
    def test_readings_csv_has_one_row_per_reading_including_rejections(self):
        c = S.SessionCollector()
        c.add(reading(70), now_ms=NOW)
        c.add(reading(None, verdict="insufficient_frames",
                      reason="Insufficient frames or irregular sampling"), now_ms=NOW)
        lines = S.build_readings_csv(c.readings).split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("reading_id,metric,unit,value,algorithm")
        assert "heart_rate,BPM,70,consensus" in lines[1]
        assert ",false," in lines[2]
        assert "Insufficient frames or irregular sampling" in lines[2]

    def test_csv_quotes_a_reason_containing_a_comma(self):
        c = S.SessionCollector()
        c.add(reading(None, verdict="low_signal_quality", reason="weak separation, 1.03"), now_ms=NOW)
        assert '"weak separation, 1.03"' in S.build_readings_csv(c.readings)

    def test_aggregate_export_carries_independence_caveats(self):
        summary = S.summarize_session(collect([70, 72, 74, 76, 78]).readings)
        out = S.build_aggregate_export(summary, "sess-1", "2026-11-26T00:00:00Z")
        assert out["schema"] == S.SCHEMA
        hr = next(m for m in out["metrics"] if m["metric"] == "heart_rate")
        assert hr["mean"] == 74 and hr["independent_windows"] == 5
        assert "does not establish physiological accuracy" in " ".join(out["statistics_notes"])
        assert out["frames_images_included"] is False
        assert out["aggregation_config"]["min_accepted_readings"] == 5

    def test_export_is_json_serialisable(self):
        import json
        summary = S.summarize_session(collect([70, 72, 74, 76, 78]).readings)
        json.dumps(S.build_aggregate_export(summary, "sess-1", "2026-11-26T00:00:00Z"))

    def test_synthetic_readings_are_labelled_synthetic_in_this_module(self):
        # Guards the honesty requirement: these tests never touch a dataset.
        assert "Synthetic" in (__doc__ or "")
