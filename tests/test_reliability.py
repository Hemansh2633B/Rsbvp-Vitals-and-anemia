"""Regression tests for the synthetic degradation (reliability) suite.

Synthetic fixtures only; verifies determinism, rejection semantics and report
structure. Results say nothing about physiology.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.backends import reliability


def test_generate_trace_is_deterministic():
    t1, rois1, fs1 = reliability.generate_trace("frame_drops_20pct", duration_s=20.0, fs=30.0, seed=42)
    t2, rois2, fs2 = reliability.generate_trace("frame_drops_20pct", duration_s=20.0, fs=30.0, seed=42)
    assert fs1 == fs2
    assert (t1 == t2).all()
    for key in rois1:
        assert (rois1[key] == rois2[key]).all()


def test_generate_trace_gaps_remain_strictly_increasing():
    t, _rois, _fs = reliability.generate_trace("frame_drops_20pct", duration_s=20.0, fs=30.0, seed=42)
    assert (np.diff(t) > 0).all()


def test_roi_dropout_produces_nan_block():
    _t, rois, _fs = reliability.generate_trace("roi_dropout_left_cheek", duration_s=10.0, fs=30.0, seed=1)
    assert np.isnan(rois["left_cheek"]).all()
    assert np.isfinite(rois["forehead"]).all()


def test_low_light_scales_signal_but_not_noise():
    _t, rois_dark, _ = reliability.generate_trace("low_light_gain_0.15", duration_s=10.0, fs=30.0, seed=7)
    _t, rois_full, _ = reliability.generate_trace("baseline", duration_s=10.0, fs=30.0, seed=7)
    # background level drops by ~the gain while sample-to-sample noise persists
    assert rois_dark["forehead"][:, 1].mean() < 0.3 * rois_full["forehead"][:, 1].mean()
    assert rois_dark["forehead"].std() > 0.3  # noise floor is not scaled away


def test_evaluate_condition_reports_availability_and_truth_error():
    result = reliability.evaluate_condition(
        "baseline", duration_s=20.0, fs=30.0, seed=11,
        window_seconds=12.0, step_seconds=6.0,
        backends=("rsbvp_reference",),
    )
    summary = result["backends"]["rsbvp_reference"]
    assert summary["status"] == "completed"
    assert summary["estimate_availability"] == pytest.approx(1.0)
    err = summary["error_vs_synthetic_truth"]
    assert err["n_pairs"] > 0
    assert err["mae_bpm"] is not None and err["mae_bpm"] < 2.0


def test_roi_dropout_marks_windows_unavailable():
    result = reliability.evaluate_condition(
        "roi_dropout_left_cheek", duration_s=30.0, fs=30.0, seed=11,
        window_seconds=12.0, step_seconds=6.0,
        backends=("rsbvp_reference",),
    )
    summary = result["backends"]["rsbvp_reference"]
    assert summary["estimate_availability"] == pytest.approx(2 / 3, abs=1e-6)
    assert summary["rejection_or_unavailability_reasons"].get("nonfinite_samples", 0) > 0


def test_cli_outputs_are_written(tmp_path):
    out = tmp_path / "out"
    rc = reliability.main([
        "--output-dir", str(out), "--duration-s", "20",
        "--conditions", "baseline,roi_dropout_left_cheek",
    ])
    assert rc == 0
    payload = json.loads((out / "reliability_synthetic.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "rsbvp.reliability-synthetic.v1"
    assert [c["condition"] for c in payload["conditions"]] == ["baseline", "roi_dropout_left_cheek"]
    md = (out / "reliability_synthetic.md").read_text(encoding="utf-8")
    assert "SYNTHETIC SOFTWARE VERIFICATION ONLY" in md


def test_cli_rejects_unknown_condition(tmp_path):
    rc = reliability.main(["--output-dir", str(tmp_path / "out"), "--conditions", "nonsense"])
    assert rc == 2

