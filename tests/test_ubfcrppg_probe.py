"""Regression tests for the UBFC-rPPG readiness probe.

Uses a synthetic stand-in archive tree (tiny OpenCV-written AVI + a fabricated
ground_truth.txt). The stand-in is NOT the real UBFC-rPPG archive and asserts
nothing about real physiological data; it verifies probe logic only.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.rppg import ubfcrppg_probe as probe_mod


def _write_tiny_avi(path: Path, *, frames: int = 24, size=(48, 36), fps=30.0) -> bool:
    cv2 = pytest.importorskip("cv2")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    if not writer.isOpened():
        writer.release()
        return False
    rng = np.random.default_rng(7)
    for index in range(frames):
        width, height = size
        frame = rng.integers(90, 160, size=(height, width, 3), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return True


def _stand_in_archive(root: Path) -> Path:
    archive = root / "ubfc-rppg"
    # subject1: complete pair
    s1 = archive / "subject1"
    s1.mkdir(parents=True)
    if not _write_tiny_avi(s1 / "vid.avi", frames=24):
        pytest.skip("OpenCV cannot write AVI in this environment")
    s1.joinpath("ground_truth.txt").write_text(
        " ".join(f"{100 + np.sin(i / 5):.6f}" for i in range(24)) + "\n", encoding="utf-8")
    # subject2: video only
    s2 = archive / "subject2"
    s2.mkdir()
    if not _write_tiny_avi(s2 / "vid.avi", frames=12):
        pytest.skip("OpenCV cannot write AVI in this environment")
    # subject3: ground truth only
    s3 = archive / "subject3"
    s3.mkdir()
    s3.joinpath("ground_truth.txt").write_text("1.5 2.5 3.5\n", encoding="utf-8")
    # not-a-subject directory ignored
    (archive / "README_notes").mkdir()
    return archive


def test_probe_missing_archive_reports_not_available(tmp_path):
    report = probe_mod.probe(tmp_path / "does-not-exist")
    assert report["status"] == "not_available"
    assert report["summary"]["subject_dirs"] == 0
    assert any("does not exist" in p for p in report["problems"])


def test_probe_empty_archive_reports_not_available(tmp_path):
    archive = tmp_path / "ubfc-rppg"
    archive.mkdir()
    report = probe_mod.probe(archive)
    assert report["status"] == "not_available"
    assert any("subject" in p for p in report["problems"])


def test_probe_reports_structure_without_inventing_semantics(tmp_path):
    archive = _stand_in_archive(tmp_path)
    report = probe_mod.probe(archive)
    assert report["status"] == "available_for_inspection"
    recordings = {item["recording_id"]: item for item in report["recordings"]}
    assert set(recordings) == {"subject1", "subject2", "subject3"}

    s1 = recordings["subject1"]
    assert s1["ground_truth"]["first_line_sample_count"] == 24
    assert s1["ground_truth"]["first_line_float_tokens_parseable"] is True
    assert s1["video"]["frame_count"] == 24
    assert s1["problems"] == []

    s2 = recordings["subject2"]
    assert "missing ground_truth.txt" in s2["problems"]
    s3 = recordings["subject3"]
    assert "missing vid.avi" in s3["problems"]

    # never infers column semantics or subsets
    assert "NOT DETERMINED" in report["subset_assignment"]
    joined_notes = json.dumps(report)
    assert "blood pressure" not in joined_notes.lower()


def test_probe_nonfloat_ground_truth_flags_unknown_semantics(tmp_path):
    archive = tmp_path / "ubfc-rppg"
    s1 = archive / "subject9"
    s1.mkdir(parents=True)
    if not _write_tiny_avi(s1 / "vid.avi", frames=10):
        pytest.skip("OpenCV cannot write AVI in this environment")
    s1.joinpath("ground_truth.txt").write_text("timestamp bvp bpm\n0.0 100 70\n", encoding="utf-8")
    report = probe_mod.probe(archive)
    item = report["recordings"][0]
    assert item["ground_truth"]["first_line_float_tokens_parseable"] is False
    assert any("UNKNOWN" in note for note in item["ground_truth"]["notes"])


def test_cli_writes_reports_and_is_deterministic(tmp_path, capsys):
    archive = _stand_in_archive(tmp_path)
    out_dir = tmp_path / "out"
    rc = probe_mod.main(["--archive-dir", str(archive), "--output-dir", str(out_dir)])
    assert rc == 0
    payload = json.loads((out_dir / "data_readiness.json").read_text(encoding="utf-8"))
    assert payload["status"] == "available_for_inspection"
    md = (out_dir / "data_readiness.md").read_text(encoding="utf-8")
    assert "Bobbia" in md
    assert "cannot" in md.lower() or "NOT inferred" in md
    # second run over the same archive produces the same recordings/problems
    rc = probe_mod.main(["--archive-dir", str(archive), "--output-dir", str(out_dir)])
    payload2 = json.loads((out_dir / "data_readiness.json").read_text(encoding="utf-8"))
    assert payload2["recordings"] == payload["recordings"]


def test_cli_requires_explicit_root(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("RSBVP_DATA_ROOT", raising=False)
    rc = probe_mod.main(["--output-dir", str(tmp_path / "out")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "RSBVP_DATA_ROOT" in captured.err
