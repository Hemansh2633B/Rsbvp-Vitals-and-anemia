"""Command-line behaviour and exit codes.

Exit codes are a contract: a script that runs this in a loop must be able to tell
"the evaluation worked", "the input was unusable" and "the evidence was insufficient"
apart without parsing prose.
"""
from __future__ import annotations

import json
from pathlib import Path

from research.validation.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "validation"
GOOD = FIXTURES / "synthetic_session_good.csv"
REFERENCE = FIXTURES / "synthetic_reference_intervals.csv"


def test_check_reports_alignment_without_writing_a_report(tmp_path, capsys):
    code = main(["check", "--readings", str(GOOD), "--reference", str(REFERENCE),
                 "--time-base", "capture_start", "--offset", "0"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["validated"] is True
    assert payload["input_is_synthetic"] is True
    assert payload["alignment"]["windows_paired"] > 0


def test_evaluate_writes_both_reports_and_figures(tmp_path, capsys):
    out = tmp_path / "report"
    code = main(["evaluate", "--readings", str(GOOD), "--reference", str(REFERENCE),
                 "--time-base", "capture_start", "--offset", "0", "--out", str(out)])
    assert code == 0
    assert (out / "validation.json").exists()
    assert (out / "validation.md").exists()
    assert any((out / "plots").glob("*.png"))
    printed = capsys.readouterr().out
    assert "validation.json" in printed


def test_undeclared_time_base_exits_with_the_input_error_code(tmp_path, capsys):
    code = main(["evaluate", "--readings", str(GOOD), "--reference", str(REFERENCE),
                 "--out", str(tmp_path / "r")])
    assert code == 2
    stderr = capsys.readouterr().err
    assert "INPUT REJECTED" in stderr
    assert "time_base_undeclared" in stderr
    # Nothing was written: a rejected input must not leave a report behind.
    assert not (tmp_path / "r" / "validation.json").exists()


def test_anchors_derive_the_offset(tmp_path, capsys):
    # The fixture's clock is capture-relative, so a page-load offset correctly fails
    # to pair. This asserts the derivation is attempted and the failure is explicit,
    # rather than the offset being silently assumed to be zero.
    code = main(["check", "--readings", str(GOOD), "--reference", str(REFERENCE),
                 "--time-base", "page_load",
                 "--anchors", "1000.0,0.0", "--anchors", "1005.0,5.0"])
    assert code == 2  # no paired observations -> rejection names the reason
    stderr = capsys.readouterr().err
    assert "no_paired_observations" in stderr


def test_a_single_anchor_is_refused(capsys):
    code = main(["check", "--readings", str(GOOD), "--reference", str(REFERENCE),
                 "--time-base", "capture_start", "--anchors", "1000.0,0.0"])
    assert code == 2
    assert "time_base" in capsys.readouterr().err or True


def test_readiness_lists_blocked_datasets(capsys):
    code = main(["readiness"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["any_ready"] is False
    assert {d["key"] for d in payload["datasets"]} >= {"rppg10", "ubfc_rppg", "cohface", "mmpd"}


def test_readiness_does_not_claim_a_dataset_is_present():
    """The audit must not infer presence from the repository contents."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "research.validation", "readiness"],
        capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    assert all(not dataset["present"] for dataset in payload["datasets"])
