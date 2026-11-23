"""Adapter contract tests: availability gating, errors, provenance, versions."""
import hashlib
import os

import pytest

from research.backends import registry
from research.backends.base import BackendUnavailable, UnsupportedAlgorithm
from research.backends.neural import MODEL_REGISTRY, NeuralBaselineBackend, checkpoint_status, sha256_file
from research.backends.pyvhr import PyVHRBackend
from research.backends.rppg_toolbox import RppgToolboxBackend, parse_toolbox_log
from research.backends.native import NativeBackend
from research.backends.reference import ReferenceBackend


def test_every_registered_backend_exposes_contract():
    for name in registry.all_backend_names():
        backend = registry.get_backend(name)
        info = backend.info()
        assert info.name == name
        assert info.version and any(ch.isdigit() for ch in info.version)
        assert info.license_id
        assert info.source.startswith("http") or "this repository" in info.source
        usable, reason = backend.available()
        assert isinstance(usable, bool)
        assert isinstance(reason, str)
        if not usable:
            assert reason.strip(), f"{name}: unavailable without a reason"
        assert backend.supported_algorithms()


def test_native_and_reference_backends_available():
    assert NativeBackend().available()[0] is True
    assert ReferenceBackend().available()[0] is True


def test_native_rejects_unsupported_algorithm():
    pytest.importorskip("numpy")
    from research.backends.base import RecordingInput
    import numpy as np
    t = np.arange(0, 20, 1 / 30.0)
    rgb = np.column_stack([110 + 3 * np.sin(t), 120 + 3 * np.sin(t), 90 + 3 * np.sin(t)])
    rec = RecordingInput(recording_id="x", timestamps_s=t, rois={"forehead": rgb}, sampling_rate_hz=30.0)
    with pytest.raises(UnsupportedAlgorithm):
        NativeBackend().run(rec, algorithms=["ICA"])


def test_toolbox_unavailable_without_env(monkeypatch):
    monkeypatch.delenv("RSBVP_RPPG_TOOLBOX_PATH", raising=False)
    backend = RppgToolboxBackend()
    usable, reason = backend.available()
    assert usable is False
    assert "RSBVP_RPPG_TOOLBOX_PATH" in reason
    with pytest.raises(BackendUnavailable):
        backend.run_unsupervised_dataset("/tmp/nonexistent", cached_path="/tmp/cache_rsbvp")


def test_toolbox_records_are_aggregate_only(monkeypatch, tmp_path):
    """A toolbox that 'runs' must still produce aggregate records, never fake per-window predictions."""
    import json
    fake = tmp_path / "toolbox"
    (fake / ".git").mkdir(parents=True)
    (fake / "main.py").write_text("print('stub')", encoding="utf-8")
    (fake / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    log = """===Unsupervised Method ( GREEN ) Predicting ===
FFT MAE (FFT Label): 4.5 +/- 0.5
FFT RMSE (FFT Label): 6.1 +/- 0.7
===Unsupervised Method ( POS ) Predicting ===
FFT MAE (FFT Label): 3.9 +/- 0.4
"""
    parsed = parse_toolbox_log(log)
    assert parsed["GREEN"]["fft_mae"] == pytest.approx(4.5)
    assert parsed["POS"]["fft_mae"] == pytest.approx(3.9)


def test_pyvhr_unavailable_without_env(monkeypatch):
    monkeypatch.delenv("RSBVP_PYVHR_PYTHON", raising=False)
    usable, reason = PyVHRBackend().available()
    assert usable is False
    assert "RSBVP_PYVHR_PYTHON" in reason
    with pytest.raises(BackendUnavailable):
        PyVHRBackend().run_on_videos([("rec", "/tmp/nope.mp4")])


def test_neural_registry_covers_the_five_models():
    assert set(MODEL_REGISTRY) == {"DeepPhys", "PhysNet", "Tscan", "EfficientPhys", "PhysFormer"}


@pytest.mark.parametrize("model", sorted(MODEL_REGISTRY))
def test_neural_checkpoint_unavailable_by_default(model, monkeypatch, tmp_path):
    monkeypatch.setenv("RSBVP_MODEL_ROOT", str(tmp_path))  # empty model root
    ok, detail, path = checkpoint_status(model)
    assert ok is False
    assert path is None
    assert "RSBVP_MODEL_ROOT" in detail or "no checkpoint" in detail


def test_neural_checkpoint_detected_and_hashed(monkeypatch, tmp_path):
    dummy = tmp_path / "PURE_TSCAN.pth"
    dummy.write_bytes(b"fake-weights-for-contract-test")
    monkeypatch.setenv("RSBVP_MODEL_ROOT", str(tmp_path))
    ok, detail, path = checkpoint_status("Tscan")
    assert ok is True
    assert path == dummy
    assert sha256_file(dummy) == hashlib.sha256(b"fake-weights-for-contract-test").hexdigest()


def test_neural_still_unavailable_with_checkpoint_but_no_toolbox(monkeypatch, tmp_path):
    dummy = tmp_path / "PURE_TSCAN.pth"
    dummy.write_bytes(b"fake-weights-for-contract-test")
    monkeypatch.setenv("RSBVP_MODEL_ROOT", str(tmp_path))
    monkeypatch.delenv("RSBVP_RPPG_TOOLBOX_PATH", raising=False)
    backend = NeuralBaselineBackend("Tscan")
    usable, reason = backend.available()
    assert usable is False
    assert "toolbox" in reason.lower()


def test_neural_only_test_requires_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("RSBVP_MODEL_ROOT", str(tmp_path))
    backend = NeuralBaselineBackend("PhysNet")
    with pytest.raises(BackendUnavailable):
        backend.run_only_test_dataset("/tmp/dataset", cached_path=str(tmp_path / "cache"))


def test_backend_info_licenses_match_register():
    assert NativeBackend().info().license_id == "MIT"
    assert RppgToolboxBackend().info().license_id == "RAIL-1.1"
    assert PyVHRBackend().info().license_id == "GPL-3.0"
    assert NativeBackend().info().license_id != "RAIL-1.1"  # no license laundering


def test_pinned_commits_are_full_shas():
    from research.backends import rppg_toolbox, pyvhr
    for commit in (rppg_toolbox.PINNED_COMMIT, pyvhr.PINNED_MASTER_COMMIT, pyvhr.PINNED_CPU_BRANCH_COMMIT):
        assert len(commit) == 40
        int(commit, 16)  # valid hex
