"""Session export parsing and validation.

The theme of this file: a malformed export must be *refused with a reason*, never
coerced into something evaluable. Each rejection case asserts the code as well as the
exception, because the code is what a researcher sees and what scripts react to.

Every fixture here is synthetic and labelled as such.
"""
from __future__ import annotations

import io
import json

import pytest

from research.validation.errors import InputRejection, Severity
from research.validation.loader import (
    SESSION_SCHEMA,
    load_session_bundle,
    load_session_csv,
    load_session_json,
)

HEADER = ("reading_id,metric,unit,value,algorithm,roi,accepted,rejection_reason,"
          "quality_score,quality_verdict,sampling_rate_hz,n_samples,window_start_s,"
          "window_end_s,session_elapsed_s,window_index,recorded_utc")

GOOD_ROW = ("1,heart_rate,BPM,70.0,consensus,all,true,,0.6,valid,30,300,0,10,10,1,"
            "2026-01-01T00:00:01.000Z")


def csv_of(*rows: str, header: str = HEADER) -> io.StringIO:
    return io.StringIO("\n".join([header, *rows]) + "\n")


def codes(exc: InputRejection) -> set[str]:
    return set(exc.codes)


def rejection_of(loaded) -> InputRejection:
    """What ``evaluate_session`` would raise for this input.

    The loaders themselves return findings rather than raising, so that a caller can
    report *every* problem at once (and so the pipeline can aggregate findings from
    the session and the reference before deciding). This helper applies the same
    decision the pipeline makes.
    """
    assert loaded.worst is Severity.REJECT, (
        f"expected a blocking finding, got {[f.code for f in loaded.findings]}")
    return InputRejection(loaded.findings)


# --- happy path --------------------------------------------------------------


def test_accepts_a_well_formed_export():
    loaded = load_session_bundle(readings_csv=csv_of(GOOD_ROW))
    assert len(loaded.export.readings) == 1
    reading = loaded.export.readings[0]
    assert reading.value == 70.0
    assert reading.accepted_recomputed is True
    assert reading.recomputed_reason is None
    assert loaded.worst is Severity.INFO


def test_an_empty_value_is_missing_not_zero():
    """The app writes an empty cell when it produced nothing. Zero is a value."""
    row = ("1,heart_rate,BPM,,consensus,all,false,low_signal_quality,,low_signal_quality,"
           "30,300,0,10,10,1,2026-01-01T00:00:01.000Z")
    loaded = load_session_bundle(readings_csv=csv_of(row))
    reading = loaded.export.readings[0]
    assert reading.value is None
    assert reading.value_parse_error is None
    assert reading.accepted_recomputed is False


def test_recomputes_acceptance_with_the_shared_rule():
    rows = [
        GOOD_ROW,
        # rejected by the quality verdict
        ("2,heart_rate,BPM,72.0,consensus,all,false,low_signal_quality,,low_signal_quality,"
         "30,300,10,20,20,2,2026-01-01T00:00:02.000Z"),
        # implausible value: passes the verdict but fails the plausibility bound
        ("3,heart_rate,BPM,900.0,consensus,all,false,implausible,,valid,"
         "30,300,20,30,30,3,2026-01-01T00:00:03.000Z"),
    ]
    loaded = load_session_bundle(readings_csv=csv_of(*rows))
    reasons = [r.recomputed_reason for r in loaded.export.readings]
    assert loaded.export.readings[0].accepted_recomputed
    assert reasons[1] == "low_signal_quality"
    assert "implausible_value" in reasons[2]


def test_duplicate_window_is_refused_but_kept_in_history():
    dup = GOOD_ROW.replace("1,", "2,", 1)  # same window bounds, different id
    loaded = load_session_bundle(readings_csv=csv_of(GOOD_ROW, dup))
    # The file claims both accepted, so the acceptance check must flag the conflict
    # *and* the rule must refuse the second window.
    assert len(loaded.export.readings) == 2
    assert loaded.export.readings[1].recomputed_reason == "duplicate_window"


def test_roi_is_part_of_window_identity():
    """Three ROIs of one window are three measurements, not three copies."""
    rows = []
    for index, roi in enumerate(("forehead", "left_cheek", "right_cheek"), start=1):
        rows.append(f"{index},heart_rate,BPM,7{index}.0,green,{roi},true,,0.6,valid,"
                    f"30,300,0,10,10,1,2026-01-01T00:00:0{index}.000Z")
    loaded = load_session_bundle(readings_csv=csv_of(*rows))
    assert [r.recomputed_reason for r in loaded.export.readings] == [None, None, None]
    assert len(loaded.export.by_series()) == 3


def test_blank_lines_are_not_records():
    loaded = load_session_bundle(readings_csv=csv_of(GOOD_ROW, "", GOOD_ROW.replace("1,", "2,", 1)
                                                    .replace("0,10,10,1", "10,20,20,2")))
    assert len(loaded.export.readings) == 2


# --- rejection ---------------------------------------------------------------


def test_missing_required_column_is_rejected():
    header = HEADER.replace(",window_end_s", "")
    with pytest.raises(InputRejection) as excinfo:
        # Structural problems raise directly: without the columns there is no table.
        load_session_csv(csv_of(GOOD_ROW, header=header))
    assert "missing_columns" in codes(excinfo.value)


def test_empty_file_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_session_csv(io.StringIO(""))
    assert "empty_file" in codes(excinfo.value)


def test_no_data_rows_is_rejected():
    # A header-only file is structurally valid, so the loader returns a finding and
    # the pipeline rejects it. Asserting the finding keeps that division visible.
    readings, findings, _ = load_session_csv(io.StringIO(HEADER + "\n"))
    assert readings == []
    assert any(f.code == "no_readings" and f.severity is Severity.REJECT for f in findings)


def test_unparseable_value_is_rejected_not_coerced():
    row = GOOD_ROW.replace(",70.0,", ",seventy,")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "unparseable_number" in codes(exc)


def test_non_finite_value_is_rejected():
    row = GOOD_ROW.replace(",70.0,", ",inf,")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "non_finite_number" in codes(exc)


def test_invalid_timestamp_is_rejected():
    row = GOOD_ROW.replace("2026-01-01T00:00:01.000Z", "2026-01-01 00:00:01")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "invalid_timestamp" in codes(exc)


def test_local_time_timestamp_is_rejected_not_assumed_utc():
    """A local-time string in a UTC column would shift a session if we guessed."""
    row = GOOD_ROW.replace("2026-01-01T00:00:01.000Z", "2026-01-01T00:00:01")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "invalid_timestamp" in codes(exc)


def test_duplicate_reading_id_is_rejected():
    row2 = GOOD_ROW.replace("0,10,10,1", "10,20,20,2")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(GOOD_ROW, row2)))
    assert "duplicate_reading_id" in codes(exc)


def test_reversed_window_bounds_are_rejected():
    row = GOOD_ROW.replace(",0,10,10,1,", ",10,0,10,1,")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "invalid_window_bounds" in codes(exc)


def test_missing_provenance_is_rejected():
    """A row with no algorithm or ROI cannot be attributed, so it cannot be compared."""
    row = GOOD_ROW.replace(",consensus,all,", ",,,")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert {"missing_algorithm", "missing_roi"} <= codes(exc)


def test_acceptance_mismatch_is_rejected():
    """If the file's decision disagrees with the shared rule, the file is not
    comparable with this evaluation — that is a blocker, not a warning."""
    row = GOOD_ROW.replace(",true,", ",false,")
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "acceptance_mismatch" in codes(exc)


def test_estimator_only_export_is_rejected():
    """Without consensus rows the session result the app showed cannot be rebuilt."""
    row = f"1,heart_rate,BPM,70.0,green,forehead,true,,0.6,valid,30,300,0,10,10,1," \
          f"2026-01-01T00:00:01.000Z"
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(row)))
    assert "no_consensus_series" in codes(exc)


def test_all_values_empty_is_rejected():
    rows = [GOOD_ROW.replace(",70.0,", ",,").replace(",true,", ",false,")
            .replace(",,0.6,valid", ",low_signal,,0.6,low_signal")]
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(*rows)))
    assert "no_values" in codes(exc)


def test_all_findings_are_reported_at_once():
    """Reporting one problem per run wastes a researcher's time."""
    bad_time = GOOD_ROW.replace("2026-01-01T00:00:01.000Z", "not-a-time")
    reversed_bounds = (GOOD_ROW.replace("1,", "2,", 1)
                       .replace(",0,10,10,1,", ",10,0,10,2,"))
    exc = rejection_of(load_session_bundle(readings_csv=csv_of(bad_time, reversed_bounds)))
    found = codes(exc)
    assert {"invalid_timestamp", "invalid_window_bounds"} <= found


# --- JSON summary ------------------------------------------------------------


def summary_payload(**over) -> dict:
    payload = {
        "schema": SESSION_SCHEMA,
        "capture_session_id": "sess-synthetic-001",
        "metrics": [{
            "metric": "heart_rate", "primary": True, "verdict": "available",
            "accepted_readings": 5, "rejected_readings": 0, "mean": 70.0,
        }],
        "acquisition": {"backend": "rsbvp-browser-liveDsp", "algorithms": ["Green", "POS"],
                        "rois": ["forehead"]},
        "frames_images_included": False,
        "frames_uploaded": False,
    }
    payload.update(over)
    return payload


def test_summary_json_round_trip():
    payload, findings, synthetic = load_session_json(io.StringIO(json.dumps(summary_payload())))
    assert payload["capture_session_id"] == "sess-synthetic-001"
    assert not [f for f in findings if f.severity is Severity.REJECT]


def test_unknown_schema_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_session_json(io.StringIO(json.dumps(summary_payload(schema="rsbvp.session-aggregate.v2"))))
    assert "unknown_schema" in codes(excinfo.value)


def test_summary_claiming_to_include_frames_is_rejected():
    payload, findings, _ = load_session_json(
        io.StringIO(json.dumps(summary_payload(frames_images_included=True))))
    assert any(f.code == "frames_present" and f.severity is Severity.REJECT
               for f in findings)


def test_experimental_metric_marked_primary_is_rejected():
    payload = summary_payload()
    payload["metrics"].append({"metric": "respiratory_rate", "primary": True,
                               "verdict": "available", "accepted_readings": 5})
    _, findings, _ = load_session_json(io.StringIO(json.dumps(payload)))
    assert any(f.code == "experimental_metric_primary" and f.severity is Severity.REJECT
               for f in findings)


def test_missing_acquisition_is_a_warning_not_a_blocker():
    payload = summary_payload()
    del payload["acquisition"]
    _, findings, _ = load_session_json(io.StringIO(json.dumps(payload)))
    assert any(f.code == "missing_acquisition" and f.severity is Severity.WARN
               for f in findings)


def test_invalid_json_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_session_json(io.StringIO("{not json"))
    assert "invalid_json" in codes(excinfo.value)


# --- bundle ------------------------------------------------------------------


def test_bundle_without_any_input_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_session_bundle()
    assert "no_input" in codes(excinfo.value)


def test_readings_only_bundle_is_usable_with_a_warning():
    loaded = load_session_bundle(readings_csv=csv_of(GOOD_ROW))
    assert loaded.worst is Severity.INFO
    assert loaded.export.summary is None


def test_summary_only_bundle_warns_that_windows_are_unavailable():
    loaded = load_session_bundle(summary_json=io.StringIO(json.dumps(summary_payload())))
    assert any(f.code == "no_readings_csv" for f in loaded.findings)


def test_bundle_marks_synthetic_input_from_the_filename():
    loaded = load_session_bundle(readings_csv=csv_of(GOOD_ROW),
                                summary_json=io.StringIO(json.dumps(summary_payload())),
                                )
    # Streams have no filename, so nothing claims synthetic; assert the flag is a
    # real signal rather than always true.
    assert loaded.export.synthetic is False
