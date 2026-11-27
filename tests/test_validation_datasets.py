"""Dataset readiness and adapter isolation.

Two things are asserted here:

1. **Nothing is bundled.** The audit must report every external dataset as blocked
   when no local root is supplied, and it must never attempt a download.
2. **Adapters stay behind the interface.** A dataset-specific adapter returns a
   verdict and a reason; it never reaches into the metrics code, and the metrics code
   never imports an adapter.
"""
from __future__ import annotations

import ast
from pathlib import Path

from research.validation.datasets import (
    ADAPTERS,
    DATASETS,
    ROOT_ENV_VARS,
    audit,
    readiness_summary,
)

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "research" / "validation" / "datasets.py"


# --- no dataset is present or fetched ---------------------------------------


def test_nothing_is_ready_without_a_supplied_root():
    statuses = audit(environ={})
    assert all(not status.ready for status in statuses)
    summary = readiness_summary(statuses)
    assert summary["any_ready"] is False
    assert len(summary["datasets_blocked"]) == len(DATASETS)


def test_every_blocked_dataset_has_a_blocker_and_an_intake_path():
    for status in audit(environ={}):
        assert status.blocker, status.key
        assert status.intake, status.key
        assert status.official_source, status.key
        assert status.licence, status.key


def test_missing_root_names_the_variable_to_set():
    statuses = audit(environ={"RSBVP_UBFC_ROOT": "/nonexistent/ubfc"})
    ubfc = next(s for s in statuses if s.key == "ubfc_rppg")
    assert "/nonexistent/ubfc" in ubfc.blocker
    assert not ubfc.ready


def test_every_registered_dataset_has_an_adapter_and_an_env_var():
    assert set(ADAPTERS) == set(DATASETS)
    assert set(ROOT_ENV_VARS) == set(DATASETS)


def test_adapters_are_declared_non_redistributable():
    """A dataset that could be committed would end up committed."""
    for spec in DATASETS.values():
        assert spec["redistributable"] is False


def test_the_module_never_downloads_anything():
    """A readiness audit that fetches a restricted dataset is a licence problem."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"requests", "urllib", "urllib3", "httpx", "socket", "subprocess",
                 "wget", "ftplib", "http"}
    assert not (imported & forbidden), imported & forbidden


# --- our own intake path -----------------------------------------------------


def rppg10_intake(tmp_path: Path, *, sessions=1, references=1) -> Path:
    root = tmp_path / "rppg10"
    root.mkdir()
    for index in range(sessions):
        (root / f"synthetic_session_readings_{index}.csv").write_text("x\n", encoding="utf-8")
    for index in range(references):
        (root / f"synthetic_reference_{index}.csv").write_text("x\n", encoding="utf-8")
    return root


def test_own_intake_is_ready_when_both_files_are_present(tmp_path):
    root = rppg10_intake(tmp_path)
    statuses = audit(environ={"RSBVP_RPPG10_ROOT": str(root)})
    rppg10 = next(s for s in statuses if s.key == "rppg10")
    assert rppg10.ready
    assert not rppg10.blocker
    assert rppg10.as_dict()["blocker"] is None
    assert rppg10.details["sessions"]


def test_own_intake_without_a_reference_is_blocked(tmp_path):
    """Readings alone cannot validate anything: there is nothing to compare against."""
    root = rppg10_intake(tmp_path, references=0)
    statuses = audit(environ={"RSBVP_RPPG10_ROOT": str(root)})
    rppg10 = next(s for s in statuses if s.key == "rppg10")
    assert not rppg10.ready
    assert "reference" in rppg10.blocker


def test_an_unrecognised_tree_is_refused_rather_than_guessed(tmp_path):
    """Reading the wrong column as a heart rate is worse than refusing the dataset."""
    root = tmp_path / "ubfc"
    root.mkdir()
    (root / "subject1").mkdir()
    statuses = audit(environ={"RSBVP_UBFC_ROOT": str(root)})
    ubfc = next(s for s in statuses if s.key == "ubfc_rppg")
    assert not ubfc.ready
    assert "adapter" in ubfc.blocker.lower()


def test_summary_is_json_ready(tmp_path):
    import json

    statuses = audit(environ={"RSBVP_RPPG10_ROOT": str(rppg10_intake(tmp_path))})
    payload = {"summary": readiness_summary(statuses),
               "datasets": [s.as_dict() for s in statuses]}
    json.dumps(payload)  # must not raise


# --- isolation ---------------------------------------------------------------


def test_metrics_code_does_not_import_dataset_adapters():
    """Dataset quirks must not be able to change a metric."""
    for name in ("metrics.py", "method_comparison.py", "alignment.py", "pipeline.py",
                 "metric_rules.py"):
        source = (MODULE.parent / name).read_text(encoding="utf-8")
        assert "datasets" not in source, f"{name} imports the dataset layer"
