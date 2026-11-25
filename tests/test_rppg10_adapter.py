"""Dataset-independent tests for the rPPG-10 adapter and frozen protocol.

Everything here is synthetic: videos are generated locally with OpenCV, ECG is
a synthetic waveform, and no participant data is used, created or collected.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from research.rppg10 import adapter, protocol

cv2 = pytest.importorskip("cv2", reason="OpenCV required for video fixtures")


def _write_video(path: Path, *, frames: int, fps: float = 30.0, size=(64, 64), level: int = 120) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    if not writer.isOpened():
        pytest.skip("OpenCV video writer/codec unavailable in this environment")
    frame = np.full((size[1], size[0], 3), level, np.uint8)
    for _ in range(frames):
        writer.write(frame)
    writer.release()


def _synthetic_subject(root: Path, subject: int, *, frames: int = 90, roi_count: int = 3,
                       ecg_samples: int = 3000, level: int = 120) -> Path:
    folder = root / f"Subject_{subject}"
    names = ["Forehead", "Cheek1", "Cheek2"][:roi_count]
    for offset, name in enumerate(names):
        _write_video(folder / f"Subject_{subject}_{name}.avi", frames=frames, level=level + offset)
    np.save(folder / f"Subject_{subject}_ECG.npy", np.zeros(ecg_samples, dtype=np.float64))
    return folder


def _synthetic_ecg(fs=1000.0, seconds=30.0, hr_bpm=66.0, seed=0):
    t = np.arange(0, seconds, 1.0 / fs)
    ecg = np.zeros_like(t)
    for beat in np.arange(60.0 / hr_bpm, seconds - 0.3, 60.0 / hr_bpm):
        ecg += np.exp(-((t - beat) ** 2) / (2 * 0.008 ** 2))
        ecg += 0.15 * np.exp(-((t - (beat + 0.3)) ** 2) / (2 * 0.03 ** 2))
    return t, ecg + 0.01 * np.random.default_rng(seed).standard_normal(t.size)


# --------------------------------------------------------------------------- #
# discovery / inventory
# --------------------------------------------------------------------------- #
def test_discover_maps_roi_names_and_ecg(tmp_path):
    _synthetic_subject(tmp_path, 1)
    subjects, failures = adapter.discover(tmp_path)
    assert len(subjects) == 1
    record = subjects[0]
    assert record.subject == 1
    assert sorted(record.videos) == ["forehead", "left_cheek", "right_cheek"]
    assert record.ecg is not None and record.ecg.name == "Subject_1_ECG.npy"
    assert failures == []


def test_discover_reports_missing_roi_and_ecg(tmp_path):
    folder = tmp_path / "Subject_2"
    folder.mkdir()
    _write_video(folder / "Subject_2_Forehead.avi", frames=30)
    subjects, _ = adapter.discover(tmp_path)
    assert sorted(subjects[0].videos) == ["forehead"]
    assert subjects[0].ecg is None
    inventory = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False)
    tokens = inventory["validation_failure_tokens"]
    assert "missing_roi_video" in tokens and "missing_ecg" in tokens


def test_discover_rejects_filename_subject_mismatch(tmp_path):
    folder = tmp_path / "Subject_3"
    folder.mkdir()
    _write_video(folder / "Subject_4_Forehead.avi", frames=30)
    _, failures = adapter.discover(tmp_path)
    assert [f.token for f in failures] == ["filename_subject_mismatch"]


def test_missing_root_and_empty_root_fail_loudly(tmp_path):
    with pytest.raises(adapter.AdapterError) as info:
        adapter.discover(tmp_path / "does-not-exist")
    assert info.value.token == "dataset_root_missing"
    with pytest.raises(adapter.AdapterError) as info:
        adapter.discover(tmp_path)
    assert info.value.token == "no_subject_directories"


def test_inventory_derives_file_facts_and_never_reads_ecg_values(tmp_path):
    _synthetic_subject(tmp_path, 5, frames=60, ecg_samples=200000)  # 2 s video vs 200 s ECG
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=True)
    assert result["schema"] == adapter.SCHEMA_INVENTORY
    assert result["subjects_found"] == 1 and result["subjects_complete"] == 1
    ecg = result["records"][0]["ecg"]
    assert ecg["sample_count"] == 200000 and ecg["duration_s"] == pytest.approx(200.0)
    assert ecg["finite_sample_count"] is None  # values deliberately not read
    video = result["records"][0]["videos"]["forehead"]
    assert (video["width"], video["height"]) == (64, 64)
    assert video["frame_count"] == 60
    assert len(video["sha256"]) == 64
    json.loads(json.dumps(result, allow_nan=False))  # strict JSON serialisable
    # 60 frames at 30 fps = 2 s vs the documented 600 s -> reported, not repaired
    assert "video_duration_unexpected" in result["validation_failure_tokens"]
    assert "ecg_video_duration_mismatch" in result["validation_failure_tokens"]


def test_inventory_flags_unexpected_video_size(tmp_path):
    folder = tmp_path / "Subject_6"
    folder.mkdir()
    _write_video(folder / "Subject_6_Forehead.avi", frames=30, size=(32, 32))
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False)
    assert "video_size_unexpected" in result["validation_failure_tokens"]


def test_expected_subjects_and_extra_files_are_reported(tmp_path):
    _synthetic_subject(tmp_path, 7, frames=30, roi_count=3)
    (tmp_path / "Subject_7" / "notes.txt").write_text("provider spreadsheet placeholder", encoding="utf-8")
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False, expected_subjects=[7, 9])
    tokens = result["validation_failure_tokens"]
    assert "expected_subject_missing" in tokens
    assert "additional_file_recorded" in tokens


def test_probe_ecg_rejects_invalid_rate_and_multidimensional_array(tmp_path):
    path = tmp_path / "x_ECG.npy"
    np.save(path, np.zeros(100))
    with pytest.raises(adapter.AdapterError) as info:
        adapter.probe_ecg(path, 0.0)
    assert info.value.token == "ecg_fs_invalid"
    np.save(path, np.zeros((2, 50)))
    with pytest.raises(adapter.AdapterError) as info:
        adapter.probe_ecg(path, 1000.0)
    assert info.value.token == "ecg_not_1d"


def test_corrupt_video_is_reported_not_skipped(tmp_path):
    folder = tmp_path / "Subject_8"
    folder.mkdir()
    (folder / "Subject_8_Forehead.avi").write_bytes(b"not a video")
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False)
    assert "video_unreadable" in result["validation_failure_tokens"]
    assert "video_unreadable" in result["error_tokens"]
    assert result["subjects_complete"] == 0


# --------------------------------------------------------------------------- #
# trace extraction
# --------------------------------------------------------------------------- #
def test_extract_roi_trace_returns_rgb_means_and_timestamps(tmp_path):
    _synthetic_subject(tmp_path, 9, frames=45, roi_count=1, level=100)
    trace = adapter.extract_roi_trace(tmp_path / "Subject_9" / "Subject_9_Forehead.avi")
    assert trace["schema"] == adapter.SCHEMA_TRACE
    assert trace["roi"] == "forehead"
    assert trace["rgb"].shape == (45, 3)
    assert np.all(trace["rgb"] >= 0)
    assert np.all(np.diff(trace["timestamps_s"]) > 0)
    assert trace["measured_fps_hz"] == pytest.approx(30.0, rel=0.1)
    assert trace["dropped_frames"] == []


def test_extract_roi_trace_rejects_wrong_size_and_unreadable(tmp_path):
    folder = tmp_path / "Subject_10"
    folder.mkdir()
    _write_video(folder / "Subject_10_Forehead.avi", frames=20, size=(32, 32))
    with pytest.raises(adapter.AdapterError) as info:
        adapter.extract_roi_trace(folder / "Subject_10_Forehead.avi")
    assert info.value.token == "video_size_unexpected"
    (folder / "Subject_10_Cheek1.avi").write_bytes(b"junk")
    with pytest.raises(adapter.AdapterError) as info:
        adapter.extract_roi_trace(folder / "Subject_10_Cheek1.avi")
    assert info.value.token == "video_unreadable"


def test_write_trace_csv_roundtrip(tmp_path):
    _synthetic_subject(tmp_path, 11, frames=12, roi_count=1)
    trace = adapter.extract_roi_trace(tmp_path / "Subject_11" / "Subject_11_Forehead.avi")
    out = tmp_path / "cache" / "trace.csv"
    adapter.write_trace_csv(out, trace)
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "timestamp_s,r,g,b"
    assert len(out.read_text(encoding="utf-8").splitlines()) == 13


# --------------------------------------------------------------------------- #
# frozen protocol
# --------------------------------------------------------------------------- #
def test_protocol_is_frozen_and_consistent():
    desc = protocol.protocol_description()
    assert desc["protocol_version"] == protocol.PROTOCOL_VERSION
    assert desc["window_seconds"] == 30.0 and desc["overlap"] is False
    assert desc["estimators"] == list(protocol.ESTIMATORS)
    assert desc["no_tuning"] is True
    # gates are the repository's existing ones, not dataset-specific values
    from research.backends import reference_methods as rm
    assert desc["quality_gates"]["min_concentration"] == rm.SPECTRAL_MIN_CONCENTRATION
    assert desc["quality_gates"]["min_snr_db"] == rm.SPECTRAL_MIN_SNR_DB


@pytest.mark.parametrize("duration,expected", [(600.0, 20), (599.0, 19), (30.0, 1), (29.0, 0), (95.0, 3)])
def test_window_starts_are_non_overlapping_and_drop_partials(duration, expected):
    starts = protocol.window_starts(duration)
    assert len(starts) == expected
    if starts:
        assert starts[0] == 0.0
        assert np.allclose(np.diff(starts), protocol.STEP_SECONDS)
        assert starts[-1] + protocol.WINDOW_SECONDS <= duration + 1e-9


def test_window_starts_validates_inputs():
    for bad in [0.0, -5.0, float("nan")]:
        with pytest.raises(ValueError):
            protocol.window_starts(bad)


def _synthetic_rgb(fs: float = 30.0, seconds: float = 30.0, hr_bpm: float = 72.0, seed=1):
    """Trace where the green channel carries a clean pulsatile component."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, 1.0 / fs)
    pulse = 0.01 * np.sin(2 * np.pi * (hr_bpm / 60.0) * t)
    base = np.array([140.0, 110.0, 95.0])
    rgb = base[None, :] + pulse[:, None] * np.array([0.4, 1.0, 0.5])[None, :]
    rgb += 0.002 * rng.standard_normal(rgb.shape)
    return t, rgb


def test_estimate_window_ok_path_recovers_synthetic_rate():
    t, rgb = _synthetic_rgb(hr_bpm=72.0)
    result = protocol.estimate_window(1, "forehead", 0, 0.0, 30.0, t, rgb, 72.0, [])
    assert result.trace_status == "ok"
    assert result.estimates_bpm["green"] == pytest.approx(72.0, abs=4.0)
    assert result.quality["green"].startswith("ok:")
    assert result.reference_bpm == 72.0


def test_estimate_window_rejects_short_trace_and_never_fabricates():
    t, rgb = _synthetic_rgb(seconds=2.0)
    result = protocol.estimate_window(1, "forehead", 0, 0.0, 30.0, t, rgb, 72.0, [])
    assert result.trace_status == "rejected"
    assert result.estimates_bpm == {"green": None, "pos": None, "chrom": None}
    assert all(v.startswith("rejected:") for v in result.quality.values())
    assert "trace_missing_frames" in "_".join(result.trace_reasons)


def test_estimate_window_rejects_nonfinite_trace():
    t, rgb = _synthetic_rgb()
    rgb = rgb.copy()
    rgb[::5, 1] = np.nan  # 20% of frames non-finite
    result = protocol.estimate_window(1, "forehead", 0, 0.0, 30.0, t, rgb, 70.0, [])
    assert result.trace_status == "rejected"
    assert any("nonfinite" in reason for reason in result.trace_reasons)
    assert result.estimates_bpm["green"] is None


def test_estimate_window_rejects_jittered_timestamps():
    t, rgb = _synthetic_rgb()
    t = t.copy()
    t[::4] = t[::4] + 0.02  # 20 ms jitter on 25% of frames
    order = np.argsort(t)
    result = protocol.estimate_window(1, "forehead", 0, 0.0, 30.0, t[order], rgb[order], 72.0, [])
    assert result.trace_status == "rejected"
    assert "trace_timestamp_jitter" in result.trace_reasons


def test_rejected_reference_window_excluded_from_pairs():
    t, rgb = _synthetic_rgb()
    ok = protocol.estimate_window(1, "forehead", 0, 0.0, 30.0, t, rgb, 72.0, [])
    no_ref = protocol.estimate_window(1, "forehead", 1, 30.0, 60.0, t, rgb, None, ["ecg_too_few_rpeaks"])
    aggregate = protocol.aggregate([ok, no_ref])
    green = aggregate["per_roi"]["forehead"]["green"]
    assert green["n_pairs"] == 1
    assert green["windows_total"] == 2
    assert green["windows_with_reference"] == 1
    assert green["usable_coverage"] == pytest.approx(0.5)


def test_participant_grouping_never_multiplies_rois():
    t, rgb = _synthetic_rgb()
    records = []
    for roi in protocol.ROIS:
        records.append(protocol.estimate_window(1, roi, 0, 0.0, 30.0, t, rgb, 72.0, []))
    for roi in protocol.ROIS:
        records.append(protocol.estimate_window(2, roi, 0, 0.0, 30.0, t, rgb, 70.0, []))
    aggregate = protocol.aggregate(records)
    assert aggregate["participant_count"] == 2
    assert aggregate["recording_count"] == 6  # 2 participants x 3 ROIs
    assert aggregate["window_count"] == 6
    for roi in protocol.ROIS:
        assert aggregate["per_roi"][roi]["green"]["participants_with_pairs"] == 2


def test_aggregate_metrics_are_correct_on_known_pairs():
    t, rgb = _synthetic_rgb()
    records = [
        protocol.estimate_window(1, "forehead", 0, 0.0, 30.0, t, rgb, 70.0, []),
        protocol.estimate_window(2, "forehead", 0, 0.0, 30.0, t, rgb, 74.0, []),
    ]
    # Force known estimates so the arithmetic is exact.
    records[0].estimates_bpm = {"green": 71.0, "pos": None, "chrom": None}
    records[1].estimates_bpm = {"green": 73.0, "pos": None, "chrom": None}
    metrics = protocol.aggregate(records)["per_roi"]["forehead"]["green"]
    assert metrics["n_pairs"] == 2
    assert metrics["mae_bpm"] == pytest.approx(1.0)
    assert metrics["rmse_bpm"] == pytest.approx(1.0)
    assert metrics["bias_bpm"] == pytest.approx(0.0)
    assert metrics["participant_bootstrap"]["participants"] == 2


def test_bootstrap_is_deterministic_and_reproducible():
    per_participant = {str(i): 2.0 + i * 0.5 for i in range(1, 6)}
    first = protocol._participant_bootstrap({int(k): v for k, v in per_participant.items()})
    second = protocol._participant_bootstrap({int(k): v for k, v in per_participant.items()})
    assert first == second
    assert first["ci95_bpm"][0] <= first["mean_of_participant_mae_bpm"] <= first["ci95_bpm"][1]


def test_bootstrap_requires_two_participants():
    assert protocol._participant_bootstrap({1: 3.0}) is None


def test_not_run_report_cannot_look_like_a_result():
    text = protocol.markdown_report({"status": "NOT RUN", "blocking_reason": "dataset absent"})
    assert "NOT RUN" in text
    assert "No accuracy metric exists" in text
    assert "MAE (BPM)" not in text  # no result table is rendered


# --------------------------------------------------------------------------- #
# end-to-end (synthetic videos, short duration)
# --------------------------------------------------------------------------- #
def test_end_to_end_benchmark_on_synthetic_dataset(tmp_path):
    """Adapter -> ECG reference -> frozen protocol, on 120 s synthetic videos."""
    root = tmp_path / "rppg10"
    fps, seconds = 30.0, 120.0
    frames = int(fps * seconds)
    for subject, level in [(1, 120), (2, 130)]:
        for offset, name in enumerate(["Forehead", "Cheek1", "Cheek2"]):
            path = root / f"Subject_{subject}" / f"Subject_{subject}_{name}.avi"
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 64))
            if not writer.isOpened():
                pytest.skip("OpenCV video writer/codec unavailable")
            t = np.arange(frames) / fps
            pulse = 0.01 * np.sin(2 * np.pi * (72.0 / 60.0) * t)
            for i in range(frames):
                frame = np.empty((64, 64, 3), np.uint8)
                frame[:, :, 0] = int(level)                     # B
                frame[:, :, 1] = int(level * (1 + pulse[i]))     # G carries the pulse
                frame[:, :, 2] = int(level * (1 + 0.4 * pulse[i]))
                writer.write(frame)
            writer.release()
        _, ecg = _synthetic_ecg(fs=1000.0, seconds=seconds, hr_bpm=72.0)
        np.save(root / f"Subject_{subject}" / f"Subject_{subject}_ECG.npy", ecg)

    out = tmp_path / "out"
    code = __import__("research.rppg10.run_benchmark", fromlist=["main"]).main([
        "benchmark", "--data-root", str(root), "--output-dir", str(out),
        "--ecg-fs-hz", "1000", "--max-seconds", "120", "--allow-deviation",
        "--i-have-verified-the-licence",
    ])
    assert code == 0, "benchmark should run when the inventory is clean"
    payload = json.loads((out / "rppg10_benchmark.json").read_text(encoding="utf-8"))
    assert payload["status"] == "RUN"
    assert payload["results"]["participant_count"] == 2
    assert payload["results"]["recording_count"] == 6
    # Decoded duration is 119.97 s (last frame timestamp), so the trailing partial
    # window is dropped: 3 full 30 s windows x 2 participants x 3 ROIs = 18.
    assert len(payload["windows"]) == 2 * 3 * 3
    assert {w["start_s"] for w in payload["windows"]} == {0.0, 30.0, 60.0}
    green = payload["results"]["per_roi"]["forehead"]["green"]
    assert green["n_pairs"] >= 1, "synthetic pulsatile traces should yield usable GREEN pairs"
    assert green["participants_with_pairs"] == 2
    assert green["mae_bpm"] is not None and green["mae_bpm"] < 15.0
    assert payload["ecg_reference_summary"]["windows_ok"] >= 1
    md = (out / "rppg10_benchmark.md").read_text(encoding="utf-8")
    assert "Per-ROI results" in md
    # 120 s synthetic videos deviate from the documented 600 s: echoed, not hidden
    assert "video_duration_unexpected" in payload["inventory_summary"]["deviation_tokens"]


def test_benchmark_refuses_deviations_without_explicit_flag(tmp_path):
    _synthetic_subject(tmp_path, 1, frames=60, ecg_samples=60000)  # short videos, no structural error
    out = tmp_path / "out"
    code = __import__("research.rppg10.run_benchmark", fromlist=["main"]).main([
        "benchmark", "--data-root", str(tmp_path), "--output-dir", str(out),
        "--ecg-fs-hz", "1000", "--i-have-verified-the-licence",
    ])
    assert code == 2
    payload = json.loads((out / "rppg10_benchmark.json").read_text(encoding="utf-8"))
    assert payload["status"] == "NOT RUN"
    assert "--allow-deviation" in payload["blocking_reason"]


def test_benchmark_refuses_without_licence_confirmation(tmp_path):
    with pytest.raises(SystemExit):
        __import__("research.rppg10.run_benchmark", fromlist=["main"]).main([
            "benchmark", "--data-root", str(tmp_path), "--ecg-fs-hz", "1000",
        ])


def test_benchmark_is_not_run_when_inventory_has_failures(tmp_path):
    _synthetic_subject(tmp_path, 1, frames=30, roi_count=1)  # missing 2 ROIs + wrong duration
    out = tmp_path / "out"
    code = __import__("research.rppg10.run_benchmark", fromlist=["main"]).main([
        "benchmark", "--data-root", str(tmp_path), "--output-dir", str(out),
        "--ecg-fs-hz", "1000", "--i-have-verified-the-licence",
    ])
    assert code == 2
    payload = json.loads((out / "rppg10_benchmark.json").read_text(encoding="utf-8"))
    assert payload["status"] == "NOT RUN"
    assert payload["inventory_summary"]["validation_failures"]
    assert "results" not in payload


def test_readiness_command_writes_not_run_assessment(tmp_path):
    out = tmp_path / "reports"
    code = __import__("research.rppg10.run_benchmark", fromlist=["main"]).main([
        "readiness", "--output-dir", str(out),
    ])
    assert code == 0
    payload = json.loads((out / "rppg10_readiness.json").read_text(encoding="utf-8"))
    assert payload["status"] == "NOT RUN"
    assert payload["honesty"]["accuracy_evaluation"].startswith("NOT RUN")
    assert payload["protocol"]["no_tuning"] is True
    md = (out / "rppg10_readiness.md").read_text(encoding="utf-8")
    assert "NOT RUN" in md and "Limitations" in md or "limitations" in md.lower()


# --------------------------------------------------------------------------- #
# released-archive layout (Sprint 11b): real filenames, zero-byte videos,
# provider-documented exclusion
# --------------------------------------------------------------------------- #
def test_trailing_underscore_filenames_are_accepted(tmp_path):
    """The released archive uses Subject_<n>_<ROI>_.avi, not the documented name."""
    folder = tmp_path / "Subject_1"
    folder.mkdir()
    for roi in ("Forehead", "Cheek1", "Cheek2"):
        _write_video(folder / f"Subject_1_{roi}_.avi", frames=30)
    np.save(folder / "Subject_1_ECG.npy", np.zeros(30000))
    subjects, failures = adapter.discover(tmp_path)
    assert failures == []
    assert sorted(subjects[0].videos) == ["forehead", "left_cheek", "right_cheek"]
    assert subjects[0].videos["forehead"].name == "Subject_1_Forehead_.avi"


def test_zero_byte_videos_are_reported_as_unreadable_errors(tmp_path):
    folder = tmp_path / "Subject_4"
    folder.mkdir()
    for roi in ("Forehead", "Cheek1", "Cheek2"):
        (folder / f"Subject_4_{roi}_.avi").write_bytes(b"")
    np.save(folder / "Subject_4_ECG.npy", np.zeros(30000))
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False)
    # empty files AND the documented Subject_4 exclusion notice, both as errors
    assert set(result["error_tokens"]) == {"video_unreadable", "documented_excluded_subject_present"}
    assert result["subjects_complete"] == 0
    assert all(f["severity"] == "error" for f in result["validation_failures"])


def test_provider_spreadsheet_is_a_deviation_not_an_error(tmp_path):
    _synthetic_subject(tmp_path, 1, frames=30)
    (tmp_path / "Subject Data.xlsx").write_bytes(b"PK\x03\x04placeholder")
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False)
    assert "additional_file_recorded" in result["deviation_tokens"]
    assert result["error_tokens"] == []


def test_documented_excluded_subject_present_blocks_until_declared(tmp_path):
    _synthetic_subject(tmp_path, 4, frames=30)
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False)
    assert "documented_excluded_subject_present" in result["error_tokens"]

    declared = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False, exclude_subjects=[4])
    assert declared["error_tokens"] == []
    assert declared["subjects_found"] == 0
    exclusion = declared["excluded_subjects"][0]
    assert exclusion["subject"] == 4
    assert exclusion["provider_documentation"]  # cites the article's §4.7
    assert exclusion["ecg_present"] is True


def test_exclusion_records_zero_byte_evidence(tmp_path):
    folder = tmp_path / "Subject_4"
    folder.mkdir()
    for roi in ("Forehead", "Cheek1", "Cheek2"):
        (folder / f"Subject_4_{roi}_.avi").write_bytes(b"")
    np.save(folder / "Subject_4_ECG.npy", np.zeros(30000))
    result = adapter.inventory(tmp_path, ecg_fs_hz=1000.0, checksums=False, exclude_subjects=[4])
    exclusion = result["excluded_subjects"][0]
    assert exclusion["video_file_sizes_bytes"] == {"forehead": 0, "right_cheek": 0, "left_cheek": 0}
    assert "0 bytes" in exclusion["adapter_derived_evidence"]


def test_undocumented_exclusion_needs_allow_deviation(tmp_path):
    root = tmp_path / "rppg10"
    for subject in (1, 2):
        # 60 s of video is needed for at least one full 30 s protocol window
        for frame_offset, name in enumerate(["Forehead", "Cheek1", "Cheek2"]):
            path = root / f"Subject_{subject}" / f"Subject_{subject}_{name}_.avi"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_video(path, frames=1800, level=120 + frame_offset)
        np.save(root / f"Subject_{subject}" / f"Subject_{subject}_ECG.npy", np.zeros(60000))
    out = tmp_path / "out"
    runner = __import__("research.rppg10.run_benchmark", fromlist=["main"])
    code = runner.main(["benchmark", "--data-root", str(root), "--output-dir", str(out),
                        "--ecg-fs-hz", "1000", "--exclude-subjects", "2",
                        "--allow-deviation", "--i-have-verified-the-licence"])
    payload = json.loads((out / "rppg10_benchmark.json").read_text(encoding="utf-8"))
    assert code == 0 and payload["status"] == "RUN"
    exclusion = payload["inventory_summary"]["excluded_subjects"][0]
    assert exclusion["provider_documentation"] is None  # undocumented -> surfaced as such
    assert payload["results"]["participant_count"] == 1
