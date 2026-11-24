"""Benchmark reproducibility block: environment, configuration, provenance.

Software verification only; these tests never require a network, GPU, or dataset.
"""
import json
import hashlib

import pytest

from research.backends import benchmark as bench_cli
from research.backends import run_info

FIXTURE_ARGS = ["--backends", "rsbvp_reference", "--output-dir"]


def test_run_report_structure(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("recording_id,csv_path\nr1,r1.csv\n", encoding="utf-8")
    report = run_info.run_report(configuration={"window_seconds": 12.0}, manifest_path=manifest)
    assert report["schema_version"] == "rsbvp.benchmark-run.v1"
    for key in ("generated_utc", "software", "environment", "configuration", "manifest_sha256"):
        assert key in report
    assert report["software"]["version"] == "1.0.0"
    assert report["software"]["commit"]
    assert report["environment"]["python"]
    assert report["environment"]["numpy"] is not None
    assert report["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert report["configuration"]["window_seconds"] == 12.0


def test_git_commit_env_override(monkeypatch):
    monkeypatch.setenv("RSBVP_GIT_SHA", "deadbeef1234")
    assert run_info.git_commit() == "deadbeef1234"


def test_benchmark_summary_carries_run_block(tmp_path, capsys):
    rc = bench_cli.main([str(__import__("pathlib").Path("tests/fixtures/rppg_rgb_fixture.csv")),
                         *FIXTURE_ARGS, str(tmp_path / "out")])
    assert rc == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    run = summary["run"]
    assert run["schema_version"] == "rsbvp.benchmark-run.v1"
    assert run["configuration"]["passband_hz"] == [0.7, 3.5]
    assert run["configuration"]["backends_requested"] == ["rsbvp_reference"]
    assert run["manifest_sha256"] is None  # single-trace input
    assert run["software"]["version"] == "1.0.0"


def test_benchmark_summary_md_lists_run_environment(tmp_path):
    rc = bench_cli.main([str(__import__("pathlib").Path("tests/fixtures/rppg_rgb_fixture.csv")),
                         *FIXTURE_ARGS, str(tmp_path / "out")])
    assert rc == 0
    md = (tmp_path / "out" / "summary.md").read_text()
    assert "## Run environment" in md
    assert "Manifest SHA-256: not applicable" in md
