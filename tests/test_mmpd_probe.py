"""MMPD probe tests — CI-safe: synthetic GIFs only, no network, no dataset.

These tests verify honesty properties: the probe runs end-to-end, always
emits the NOT-RUN accuracy banner, and never invents physiological numbers.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gui"))
sys.path.insert(0, str(REPO))
from research.mmpd import mmpd_probe  # noqa: E402


def _make_gif(path: Path, frames: int = 40, size=(64, 48), frame_ms: int = 30, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    imgs = []
    base = np.full((size[1], size[0], 3), (140, 110, 90), dtype=np.uint8)  # skin-ish BGR→RGB-ish
    for i in range(frames):
        noise = rng.integers(-6, 7, base.shape, dtype=np.int16)
        frame = np.clip(base.astype(np.int16) + noise + (8 * np.sin(i / 5.0)), 0, 255).astype(np.uint8)
        imgs.append(Image.fromarray(frame, "RGB"))
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=frame_ms, loop=0)
    return path


def test_gif_smoke_report_schema_and_honesty(tmp_path):
    gif_dir = tmp_path / "gifs"
    gif_dir.mkdir()
    _make_gif(gif_dir / "sample_a.gif", seed=1)
    _make_gif(gif_dir / "sample_b.gif", seed=2)
    out = tmp_path / "out"
    report = mmpd_probe.gif_smoke(gif_dir, out)
    assert report["schema"] == "rsbvp.mmpd-gif-smoke.v1"
    assert report["record_count"] == 2
    assert "NOT RUN" in report["honesty"]["accuracy_evaluation"]
    for record in report["records"]:
        assert "NOT RUN" in record["honesty"]["accuracy_evaluation"]
        flat = json.dumps(record).lower()
        for banned in ('"mae"', '"rmse"', '"pearson"', '"bland_altman"', '"agreement_bpm"'):
            assert banned not in flat, f"records must not carry a {banned} field"
        assert record["frames"] == 40
        assert record["duration_s"] > 0
        assert 0.0 <= record["face_detection_rate"] <= 1.0
        assert set(record["roi_coverage"]) == {"forehead", "left_cheek", "right_cheek"}
        for region, est in (record["diagnostic_estimates_bpm"] or {}).items():
            assert est is None or isinstance(est, dict)
            if isinstance(est, dict):
                for method in ("GREEN", "POS", "CHROM", "ICA", "PBV"):
                    value = est.get(method)
                    assert value is None or 42.0 <= value <= 210.0
    payload = (out / "mmpd_gif_smoke.json").read_text()
    json.loads(payload)  # strict parse; allow_nan=False enforced at write time
    assert (out / "mmpd_gif_smoke.md").exists()
    md = (out / "mmpd_gif_smoke.md").read_text()
    assert "no reference PPG" in md
    assert "accuracy" in md.lower()  # the disclaimer must be explicit


def test_gif_frame_durations_parsed(tmp_path):
    gif = _make_gif(tmp_path / "one.gif", frames=30, frame_ms=40, seed=3)
    record = mmpd_probe.probe_gif(gif)
    assert record["frames"] == 30
    assert record["frame_duration_ms"] == 40
    assert record["uniform_frame_duration"] is True
    assert record["gif_fps_effective"] == pytest.approx(25.0, abs=0.01)


def test_inspect_mat_lists_keys_without_values(tmp_path):
    import scipy.io
    root = tmp_path / "MMPD_Dataset"
    (root / "subject7").mkdir(parents=True)
    scipy.io.savemat(root / "subject7" / "p7_0.mat", {
        "video": np.zeros((4, 2, 2, 3), dtype=np.uint8),
        "GT_ppg": np.arange(10, dtype=float),
        "light": np.array(["LED-low"]),
        "motion": np.array(["Stationary"]),
    })
    out = tmp_path / "out"
    report = mmpd_probe.inspect_mat(root, out)
    assert report["schema"] == "rsbvp.mmpd-mat-inspect.v1"
    assert report["subject_dirs"] == 1 and report["mat_files"] == 1
    keys = report["sampled_inventory"][0]["keys"]
    assert "video" in keys and "GT_ppg" in keys
    assert keys["GT_ppg"][0] == [1, 10]         # shape only (MATLAB 2-D)
    assert keys["GT_ppg"][1] == "float64"       # dtype only
    assert keys["video"][0] == [4, 2, 2, 3]
    written = json.loads((out / "mmpd_mat_inspect.json").read_text())
    assert written["sampled_inventory"][0]["keys"]["GT_ppg"][0] == [1, 10]


def test_inspect_mat_counts_subjects(tmp_path):
    root = tmp_path / "MMPD_Dataset"
    for subject in ("subject1", "subject2", "subject3"):
        (root / subject).mkdir(parents=True)
    report = mmpd_probe.inspect_mat(root, tmp_path / "out")
    assert report["subject_dirs"] == 3
    assert report["mat_files"] == 0
