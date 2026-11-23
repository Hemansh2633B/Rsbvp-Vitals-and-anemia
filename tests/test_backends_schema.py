"""Schema contract tests for the standardized benchmark records."""
import json
import math

import pytest

from research.backends.schema import (
    BACKEND_RECORD_SCHEMA_VERSION,
    BenchmarkRecord,
    SchemaError,
    read_records_csv,
    read_records_json,
    records_from_json,
    records_to_json,
    validate_record,
    write_records_csv,
    write_records_json,
    write_waveforms_csv,
)


def make_record(**overrides):
    payload = dict(
        recording_id="rec-1",
        timestamp_s=0.0,
        algorithm="GREEN",
        roi="forehead",
        pulse_signal=[0.1, -0.2, None],
        estimated_hr_bpm=70.0,
        signal_quality="ok",
        sampling_rate_hz=30.0,
        backend="rsbvp_native",
        backend_version="1.0.0",
        model_checkpoint=None,
        configuration_hash="a" * 64,
        window_end_s=11.966,
        participant_id="p-1",
    )
    payload.update(overrides)
    return BenchmarkRecord(**payload)


def test_roundtrip_json_preserves_missing_values(tmp_path):
    record = make_record()
    path = write_records_json([record], tmp_path / "records.json")
    loaded = read_records_json(path)
    assert len(loaded) == 1
    assert loaded[0].pulse_signal == [0.1, -0.2, None]
    assert loaded[0].estimated_hr_bpm == 70.0
    assert loaded[0].participant_id == "p-1"
    assert loaded[0].schema_version == BACKEND_RECORD_SCHEMA_VERSION


def test_json_rejects_nan_and_infinity():
    record = make_record()
    payload = json.loads(records_to_json([record]))
    payload["records"][0]["estimated_hr_bpm"] = float("inf")
    with pytest.raises(SchemaError):
        records_from_json(json.dumps(payload))


def test_nan_scalar_fields_become_null():
    record = make_record(estimated_hr_bpm=float("nan"), sampling_rate_hz=float("inf"))
    assert record.estimated_hr_bpm is None
    assert record.sampling_rate_hz is None


def test_missing_timestamp_rejected():
    with pytest.raises(SchemaError):
        make_record(timestamp_s=float("nan"))


def test_negative_sampling_rate_rejected():
    with pytest.raises(SchemaError):
        make_record(sampling_rate_hz=-1.0)


def test_estimated_hr_out_of_range_rejected():
    with pytest.raises(SchemaError):
        make_record(estimated_hr_bpm=900.0)


def test_configuration_hash_must_be_sha256_hex():
    with pytest.raises(SchemaError):
        make_record(configuration_hash="not-a-hash")


def test_unknown_keys_rejected():
    payload = make_record().to_dict()
    payload["surprise_field"] = 1
    with pytest.raises(SchemaError):
        BenchmarkRecord.from_dict(payload)


def test_csv_roundtrip_preserves_missing_values(tmp_path):
    record = make_record(estimated_hr_bpm=None, pulse_signal=None, signal_quality="rejected:nonfinite_samples")
    csv_path = write_records_csv([record], tmp_path / "records.csv")
    loaded = read_records_csv(csv_path)
    assert len(loaded) == 1
    assert loaded[0].estimated_hr_bpm is None
    assert loaded[0].pulse_signal is None
    assert loaded[0].signal_quality == "rejected:nonfinite_samples"


def test_waveform_csv_exports_every_sample_and_preserves_gaps(tmp_path):
    record = make_record(pulse_signal=[1.0, None, 3.0, 4.0], sampling_rate_hz=2.0, timestamp_s=10.0)
    path = write_waveforms_csv([record], tmp_path / "waveforms.csv")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("schema_version,recording_id,algorithm,roi,sample_index,timestamp_s,pulse_signal")
    assert len(lines) == 5  # header + 4 samples
    assert "10" in lines[1].split(",")[5] and lines[1].split(",")[4] == "0"
    assert lines[2].endswith(",")  # missing sample preserved as empty cell, never zero
    assert "11.5" in lines[4]  # 10.0 + 3/2.0


def test_aggregate_records_allowed():
    record = make_record(
        pulse_signal=None,
        estimated_hr_bpm=None,
        signal_quality="aggregate",
        backend_output_type="aggregate",
        roi="whole_video",
        backend_report={"parsed_metrics": {"fft_mae": 5.0}},
    )
    assert record.backend_output_type == "aggregate"


def test_invalid_output_type_rejected():
    with pytest.raises(SchemaError):
        make_record(backend_output_type="sideways")


def test_validate_record_is_idempotent():
    record = make_record()
    assert validate_record(record) is record


def test_pulse_signal_never_fabricated_by_cleaner():
    record = make_record(pulse_signal=[float("nan"), 1.0, float("inf")])
    assert record.pulse_signal == [None, 1.0, None]
