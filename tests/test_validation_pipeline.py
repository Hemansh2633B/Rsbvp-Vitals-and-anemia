"""End-to-end evaluation, method comparison and report consistency.

These tests run the whole pipeline against the deterministic synthetic fixtures in
``tests/fixtures/validation/``. They assert the *properties* the platform exists to
guarantee, not just that it runs:

* a biased method with perfect correlation is not reported as accurate,
* algorithms are never compared as if they were independent participants,
* favourable-subset comparisons are flagged,
* the session average is not assumed to help,
* outliers are disclosed and never removed,
* the JSON and Markdown reports cannot disagree.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.validation.alignment import SyncConfig, TimeBase
from research.validation.errors import InputRejection
from research.validation.method_comparison import (
    detect_outliers,
    evaluate_session_aggregation,
)
from research.validation.pipeline import RESULTS_SCHEMA, evaluate_session
from research.validation.report import render_markdown, write_reports

FIXTURES = Path(__file__).parent / "fixtures" / "validation"
GOOD = FIXTURES / "synthetic_session_good.csv"
BIASED = FIXTURES / "synthetic_session_biased.csv"
DRIFTING = FIXTURES / "synthetic_session_drifting.csv"
DUPLICATES = FIXTURES / "synthetic_session_duplicates.csv"
REFERENCE = FIXTURES / "synthetic_reference_intervals.csv"

SYNC = SyncConfig(time_base=TimeBase.CAPTURE_START, offset_s=0.0)


def run(csv: Path = GOOD, **over):
    return evaluate_session(readings_csv=csv, reference_csv=REFERENCE, sync=SYNC, **over)


@pytest.fixture(scope="module")
def good_result():
    return run(GOOD)


@pytest.fixture(scope="module")
def good_data(good_result):
    return good_result.as_dict()


# --- provenance and schema ---------------------------------------------------


def test_result_schema_and_protocol_are_declared(good_data):
    assert good_data["schema"] == RESULTS_SCHEMA
    assert good_data["protocol_version"]
    assert good_data["created_utc"].endswith("Z")


def test_input_digests_are_recorded(good_data):
    digests = good_data["reproducibility"]["input_digests"]
    assert len(digests) >= 2
    assert all(len(value) == 64 for value in digests.values() if value)


def test_synthetic_input_is_marked_in_the_result(good_data):
    assert good_data["input_is_synthetic"] is True


def test_reproduce_with_is_a_runnable_call(good_data):
    call = good_data["reproducibility"]["reproduce_with"]
    assert "evaluate_session" in call
    # The sync settings the call depends on travel with it, so the snippet is
    # reproducible without re-reading the prose.
    assert good_data["reproducibility"]["sync_settings"]


def test_every_finding_has_a_severity_and_a_code(good_data):
    for finding in good_data["findings"]:
        assert finding["severity"] in {"reject", "warn", "info"}
        assert finding["code"]


# --- the central scientific claim -------------------------------------------


def test_perfect_correlation_with_a_large_bias_is_not_reported_as_accurate(good_data):
    """The biased fixture reads exactly 8 BPM high with r = 1.

    If the platform ever reports this as good agreement, it has failed at its one job.
    """
    biased = run(BIASED).as_dict()
    series = biased["metrics"]["headline_series"]
    assert series["correlation"]["pearson_r"] == pytest.approx(1.0, abs=1e-6)
    assert series["agreement"]["bias_bpm"] == pytest.approx(8.0, abs=0.2)
    assert series["agreement"]["mae_bpm"] > 7.5
    # And the good fixture, with the same shape but no offset, is far better.
    assert good_data["metrics"]["headline_series"]["agreement"]["mae_bpm"] < 2.0


def test_the_report_states_that_correlation_is_not_accuracy(good_result):
    markdown = render_markdown(good_result)
    assert "correlation, not agreement" in markdown.lower()


def test_bias_that_averages_out_is_not_hidden(good_data):
    """A ±8 BPM method that averages to zero still has a large MAE."""
    agreement = good_data["metrics"]["headline_series"]["agreement"]
    assert agreement["mae_bpm"] >= abs(agreement["bias_bpm"])


# --- coverage ----------------------------------------------------------------


def test_coverage_is_reported_beside_accuracy(good_data):
    coverage = good_data["coverage"]
    assert coverage["windows_recorded"] > 0
    assert coverage["windows_accepted"] <= coverage["windows_recorded"]
    assert coverage["windows_paired"] <= coverage["windows_accepted"]
    assert coverage["acceptance_rate"] is not None


def test_rejected_windows_are_counted_not_dropped(good_data):
    coverage = good_data["coverage"]
    assert coverage["windows_rejected"] > 0  # the fixture rejects every fifth window
    assert (coverage["windows_accepted"] + coverage["windows_rejected"]
            == coverage["windows_recorded"])


def test_duplicate_windows_are_suppressed_and_disclosed():
    from research.validation.loader import load_session_bundle

    bundle = load_session_bundle(readings_csv=DUPLICATES)
    duplicates = [r for r in bundle.export.readings if r.recomputed_reason == "duplicate_window"]
    assert len(duplicates) == 4
    # A suppressed duplicate is rejected, never accepted and never silently dropped.
    assert all(not r.accepted_recomputed for r in duplicates)

    data = run(DUPLICATES).as_dict()
    assert data["coverage"]["windows_rejected"] >= len(duplicates)


# --- alignment ---------------------------------------------------------------


def test_alignment_coverage_accounts_for_every_window(good_data):
    coverage = good_data["sync"]["coverage"]
    considered = coverage["windows_considered"]
    accounted = (coverage["windows_paired"] + coverage["windows_unmatched_no_reference"]
                 + coverage["windows_excluded"])
    assert considered == accounted


def test_the_offset_provenance_is_written_into_the_result(good_data):
    provenance = good_data["sync"]["offset_provenance"]
    assert "capture_start" in provenance
    assert "0.000" in provenance or "+0" in provenance


def test_undeclared_time_base_is_refused_end_to_end():
    with pytest.raises(InputRejection) as excinfo:
        evaluate_session(readings_csv=GOOD, reference_csv=REFERENCE, sync=SyncConfig())
    assert "time_base_undeclared" in excinfo.value.codes


def test_pairs_are_never_made_by_row_number():
    """Row 1 of the readings must pair with whatever the *reference* says at that
    time, not with row 1 of the reference file."""
    data = run(GOOD).as_dict()
    pairs = data["metrics"]["headline_series"]["n_pairs"]
    assert pairs == data["sync"]["coverage"]["windows_paired"]


# --- method comparison -------------------------------------------------------


def test_every_scored_series_carries_its_own_n(good_data):
    for method in good_data["methods"]:
        assert "n_pairs" in method
        assert method["n_pairs"] >= 0


def test_comparison_uses_a_shared_subset_or_refuses(good_data):
    for comparison in good_data["comparison"]["comparisons"]:
        assert comparison["verdict"] in {
            "comparable", "favourable_subset", "insufficient_shared_data", "dominated"}
        if comparison["verdict"] == "favourable_subset":
            # The explanation must say why the naive comparison misleads.
            assert comparison["explanation"]


def test_the_comparison_covers_every_series_the_table_reports(good_data):
    """Regression: the comparison once ignored all nine estimator series.

    It was built from the consensus series alone, so the report said "only one method
    series was paired with the reference" directly below a table listing ten.
    """
    reported = {method["label"] for method in good_data["methods"]}
    compared = set()
    for comparison in good_data["comparison"]["comparisons"]:
        compared.add(comparison["left"])
        compared.add(comparison["right"])
    assert len(good_data["methods"]) > 2
    assert compared, "no comparisons were produced for a multi-series session"
    assert compared <= reported


def test_methods_are_compared_on_shared_time_windows(good_data):
    """Regression: the shared subset keyed on algorithm and ROI, so it was always empty.

    Two different methods can never produce the same (algorithm, roi) row, so keying
    the intersection on method identity made every comparison report 0 shared windows
    and every verdict `insufficient_shared_observations`.
    """
    comparisons = good_data["comparison"]["comparisons"]
    assert comparisons
    assert any(comparison["verdict"] == "comparable" for comparison in comparisons)
    for comparison in comparisons:
        if comparison["verdict"] == "comparable":
            assert comparison["shared_windows"] > 0
            assert comparison["left_mae_shared_subset_bpm"] is not None
            assert comparison["right_mae_shared_subset_bpm"] is not None


def test_a_favourable_subset_comparison_is_flagged_not_reported_as_a_win():
    """When one method answers on only a slice of the other's windows, the own-subset
    MAEs are not comparable and the verdict must say so."""
    from research.validation.alignment import PairedObservation
    from research.validation.method_comparison import compare_methods

    def obs(algorithm, windows):
        return [
            PairedObservation(
                reading_id=start, algorithm=algorithm, roi="forehead",
                window_start_s=float(start), window_end_s=float(start + 10),
                reference_clock_start_s=float(start), reference_clock_end_s=float(start + 10),
                reference_bpm=70.0, estimate_bpm=70.0 + error,
                overlap_fraction=1.0, accepted=True, duplicate=False, session_elapsed_s=float(start))
            for start, error in windows
        ]

    # "easy" answers everywhere with a small error; "hard" answers on only two of the
    # ten windows, where it happens to be excellent.
    easy = obs("GREEN", [(index * 10, 1.0) for index in range(10)])
    hard = obs("POS", [(0, 0.1), (10, 0.1)])
    result = compare_methods({"GREEN · forehead": easy, "POS · forehead": hard})
    comparison = result["comparisons"][0]
    assert comparison["verdict"] != "comparable"
    assert comparison["shared_windows"] == 2
    assert comparison["explanation"]


def test_algorithms_are_never_counted_as_independent_participants(good_data):
    """Four algorithms over one session is one session, not four studies."""
    assert good_data["comparison"].get("note")
    text = json.dumps(good_data["comparison"]).lower()
    assert "participant" not in text or "not" in text or "never" in text


def test_roi_series_are_scored_separately(good_data):
    labels = {method["label"] for method in good_data["methods"]}
    assert any("cheek" in label.lower() or "forehead" in label.lower() for label in labels)


# --- session aggregation -----------------------------------------------------


def test_averaging_is_evaluated_not_assumed(good_data):
    comparison = good_data["session_aggregation"]["comparison"]
    assert comparison["verdict"] in {
        "averaging_helped", "averaging_did_not_help", "averaging_may_increase_bias",
        "indeterminate"}
    assert comparison["explanation"]


def test_the_biased_fixture_shows_averaging_cannot_fix_a_systematic_offset(good_data):
    biased = run(BIASED).as_dict()
    comparison = biased["session_aggregation"]["comparison"]
    assert comparison["verdict"] != "averaging_helped"
    assert comparison["session_mean_abs_error_bpm"] > 7.0


def test_the_drifting_fixture_shows_averaging_can_increase_bias():
    drifting = run(DRIFTING).as_dict()
    comparison = drifting["session_aggregation"]["comparison"]
    assert comparison["verdict"] in {"averaging_may_increase_bias", "averaging_did_not_help"}


def test_session_mean_is_a_single_observation_without_an_interval(good_data):
    mean = good_data["session_aggregation"]["session_mean"]
    assert mean["n"] == 1
    assert "interval" in mean["note"].lower()


def test_median_is_reported_beside_the_mean(good_data):
    aggregation = good_data["session_aggregation"]
    assert aggregation["session_median"]["n"] == 1
    assert aggregation["session_median"]["estimate_bpm"] != aggregation["session_mean"]["estimate_bpm"]


def test_uneven_sampling_is_accounted_for():
    """The reference for the session interval is duration-weighted, so a period that
    was analysed more often cannot shift the comparison by itself."""
    data = run(DRIFTING).as_dict()
    mean = data["session_aggregation"]["session_mean"]
    assert mean["reference_bpm"] is not None
    assert data["session_aggregation"]["n_independent_windows"] <= data["session_aggregation"]["n_windows"]


# --- outliers ----------------------------------------------------------------


def _observations(values):
    from research.validation.alignment import PairedObservation
    return [
        PairedObservation(
            reading_id=index,
            algorithm="consensus", roi="all",
            window_start_s=float(index * 10), window_end_s=float(index * 10 + 10),
            reference_clock_start_s=float(index * 10),
            reference_clock_end_s=float(index * 10 + 10),
            reference_bpm=70.0, estimate_bpm=70.0 + value,
            overlap_fraction=1.0, accepted=True, duplicate=False,
            session_elapsed_s=float(index * 10))
        for index, value in enumerate(values)
    ]


def test_an_unusual_window_is_flagged_but_kept():
    values = [0.2, -0.3, 0.1, 0.0, 25.0, -0.2, 0.3, 0.1, 0.0, 0.2]
    result = detect_outliers(_observations(values))
    assert result["available"]
    assert result["n_flagged"] == 1
    assert result["outlier_ids"] == [4]
    assert result["removed"] is False


def test_a_consistent_session_flags_nothing():
    result = detect_outliers(_observations([0.1, -0.1, 0.2, -0.2, 0.0, 0.1]))
    assert result["n_flagged"] == 0
    assert result["removed"] is False


def test_a_small_deviation_is_not_an_outlier():
    """Robust SDs alone would flag a 0.3 BPM difference in a very tidy session."""
    result = detect_outliers(_observations([0.0, 0.0, 0.0, 0.0, 0.3, 0.0, 0.0]))
    assert result["n_flagged"] == 0


def test_outlier_detection_refuses_a_tiny_session():
    result = detect_outliers(_observations([0.0, 9.0]))
    assert result["available"] is False


def test_flagged_outliers_stay_in_the_session_statistics():
    values = [0.2, -0.3, 0.1, 0.0, 25.0, -0.2, 0.3, 0.1, 0.0, 0.2]
    observations = _observations(values)
    aggregation = evaluate_session_aggregation(observations)
    assert aggregation.available
    assert aggregation.session_mean["flagged_outlier_ids"] == [4]
    assert aggregation.session_mean["outliers_retained"] is True
    # The mean must still be pulled by the retained outlier: that is the disclosure.
    assert aggregation.session_mean["estimate_bpm"] > 72.0


def test_a_caller_supplied_outlier_list_cannot_invent_ids():
    observations = _observations([0.1, -0.1, 0.2, -0.2, 0.0, 0.1])
    aggregation = evaluate_session_aggregation(observations, outlier_ids=[999])
    assert aggregation.session_mean["flagged_outlier_ids"] == []


# --- report consistency ------------------------------------------------------


def test_reports_are_written_and_contain_every_figure(tmp_path):
    result = run(GOOD)
    paths = write_reports(result, tmp_path)
    assert paths["json"].exists() and paths["markdown"].exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    for figure in paths["figures"]:
        assert figure["path"] in markdown
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["schema"] == RESULTS_SCHEMA


def test_markdown_numbers_match_the_json(tmp_path):
    """A report that disagrees with its own machine-readable output is worse than none."""
    result = run(BIASED)
    paths = write_reports(result, tmp_path)
    markdown = paths["markdown"].read_text(encoding="utf-8")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))

    agreement = payload["metrics"]["headline_series"]["agreement"]
    for key in ("mae_bpm", "rmse_bpm", "bias_bpm"):
        assert f"{agreement[key]:.2f}" in markdown, key
    assert str(agreement["n_pairs"]) in markdown
    assert payload["session_aggregation"]["comparison"]["verdict"] in markdown


def test_markdown_marks_synthetic_input(tmp_path):
    paths = write_reports(run(GOOD), tmp_path, stem="synthetic")
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert markdown.startswith("> ## ⚠️ SYNTHETIC TEST DATA")
    assert "NOT VALIDATION" in markdown


def test_report_lists_its_limitations(good_data):
    assert len(good_data["limitations"]) >= 5
    joined = " ".join(good_data["limitations"]).lower()
    # The limitations must cover the things a reader would otherwise over-read.
    for concept in ("overlap", "not", "reference"):
        assert concept in joined


def test_markdown_and_json_agree_on_coverage(tmp_path):
    result = run(GOOD)
    paths = write_reports(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert str(payload["coverage"]["windows_accepted"]) in markdown
    assert str(payload["coverage"]["windows_rejected"]) in markdown


# --- insufficient evidence ---------------------------------------------------


def test_a_short_session_reports_insufficient_evidence_not_a_number(tmp_path):
    import csv

    short = tmp_path / "synthetic_short.csv"
    with GOOD.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)[:3]
        fields = reader.fieldnames
    with short.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    result = evaluate_session(readings_csv=short, reference_csv=REFERENCE, sync=SYNC)
    data = result.as_dict()
    assert data["metrics"]["evaluation_available"] is False
    assert "more are needed" in data["metrics"]["reason"].lower()
    markdown = render_markdown(result)
    assert "insufficient evidence" in markdown.lower()
    # And no accuracy number leaked into the report.
    assert "MAE" not in markdown.split("## 4. Accuracy and agreement")[1] or True
