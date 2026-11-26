"""Camera-test record validator tests. Infrastructure checks only — no camera,
no browser, and no claim that any physical test was executed."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.camera import validate_manual_test_record as v

EXAMPLE = Path(__file__).resolve().parents[1] / "research" / "camera" / "manual_test_record.example.json"


def _record(**overrides):
    rec = json.loads(EXAMPLE.read_text())
    for dotted, value in overrides.items():
        target = rec
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        if value is None:
            target.pop(parts[-1], None)
        else:
            target[parts[-1]] = value
    return rec


def test_example_record_is_valid():
    record = json.loads(EXAMPLE.read_text())
    assert v.validate_record(record) == []


def test_missing_required_fields_are_reported():
    record = _record(**{"environment.camera_model": "", "quality_gate.status": None})
    problems = v.validate_record(record)
    assert any(p.startswith("missing_field:environment.camera_model") for p in problems)
    assert any(p.startswith("missing_field:quality_gate.status") for p in problems)


def test_bad_enums_rejected():
    record = _record(**{"result": "perfect", "environment.lighting": "mood", "capture.roi_availability.forehead": "mostly"})
    problems = v.validate_record(record)
    assert any(p.startswith("bad_field:result") for p in problems)
    assert any(p.startswith("bad_field:environment.lighting") for p in problems)
    assert any(p.startswith("bad_field:capture.roi_availability.forehead") for p in problems)


def test_embedded_media_or_participant_identifiers_rejected():
    record = _record()
    record["capture"]["video_path"] = "/home/operator/face.mp4"
    record["session"]["participant_name"] = "Jane Doe"
    problems = v.validate_record(record)
    assert any(p.startswith("forbidden_key:") for p in problems)


def test_unconsented_or_unidentified_session_rejected():
    record = _record(**{"session.consent_confirmed": False})
    problems = v.validate_record(record)
    assert any(p.startswith("missing_field:session.consent_confirmed") for p in problems)


def test_out_of_range_values_rejected():
    record = _record(**{"environment.approx_fps": 0, "capture.duration_s": -5,
                        "capture.dropped_interval_fraction": 1.5})
    problems = v.validate_record(record)
    assert any(p.startswith("bad_field:environment.approx_fps") for p in problems)
    assert any(p.startswith("bad_field:capture.duration_s") for p in problems)
    assert any(p.startswith("bad_field:capture.dropped_interval_fraction") for p in problems)


def test_cli_exit_codes(tmp_path, capsys):
    assert v.main([str(EXAMPLE)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "nope"}')
    assert v.main([str(bad)]) == 1


TEMPLATE = Path(__file__).resolve().parents[1] / "research" / "camera" / "sprint14_test_record_TEMPLATE.json"


def test_sprint14_template_is_labelled_unexecuted():
    record = json.loads(TEMPLATE.read_text())
    assert record["schema"] == v.SCHEMA
    assert record["execution_status"] == "NOT EXECUTED"
    assert record["session"]["consent_confirmed"] is False
    assert record["session"]["date_utc"] == "1970-01-01"
    assert "TEMPLATE" in record["notes"]
    # Every scenario must be marked not-run; a filled-in template would be a
    # fabricated result.
    assert all(scenario["executed"] is False for scenario in record["scenarios"])
    assert all(scenario["outcome"] is None for scenario in record["scenarios"])


def test_sprint14_template_cannot_pass_validation():
    # The template must be structurally incapable of being mistaken for a real
    # session: no consent has been given, so the validator refuses it. This is the
    # guard that keeps a placeholder from drifting into the evidence base.
    record = json.loads(TEMPLATE.read_text())
    problems = v.validate_record(record)
    assert any(p.startswith("missing_field:session.consent_confirmed") for p in problems)


def test_sprint14_template_records_the_sprint14_fields():
    record = json.loads(TEMPLATE.read_text())
    completion = record["session_completion"]
    for field in ("completion_state_reached", "stop_invited_only_with_available_result",
                  "reset_cleared_all_values", "accepted_readings", "rejected_readings",
                  "acceptance_pct", "independent_windows", "density_ratio", "uneven_density"):
        assert field in completion
    for field in ("observed_sampling_rate_hz", "duplicate_frame_fraction", "largest_gap_ms",
                  "interruption_recovered", "recovery_time_s"):
        assert field in record["capture"]
    assert record["capture"]["permission_flow"]["denied_then_granted"] is None


def test_template_carries_no_participant_payload():
    # Reuse the validator's forbidden-key scan directly.
    record = json.loads(TEMPLATE.read_text())
    problems = []
    v._scan_forbidden(record, problems)
    assert problems == []
