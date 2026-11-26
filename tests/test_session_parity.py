"""Browser/Python parity for session aggregation.

The two implementations (gui/frontend/src/rppg/sessionAggregate.ts and
gui/rppg_core/session.py) must agree on every observable decision, because both
pathways present the same session result. This module checks the Python side
against a fixture that the TypeScript test suite has already verified, so a
divergence fails in one place rather than surfacing as two different UIs.

The fixture is shared, synthetic and checked in: no dataset, no GPU, no network.

Workflow
--------
``SessionParityCases.json``-style fixture is *generated here* and compared with
the committed JSON (which the TypeScript test also reads). If either language
changes a rule, one of the two suites fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rppg_core import session as S

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "session_aggregation_parity.json"
NOW = 1_767_000_000_000.0


def _reading(spec: dict) -> S.Reading:
    start = float(spec.get("window_start_s", 0.0))
    end = float(spec.get("window_end_s", start + 10.0))
    return S.Reading(
        metric=spec.get("metric", "heart_rate"),
        value=spec.get("value"),
        algorithm=spec.get("algorithm", S.CONSENSUS),
        roi=spec.get("roi", "all"),
        quality_score=spec.get("quality_score", 0.6),
        quality_verdict=spec.get("quality_verdict", "valid"),
        fs_hz=spec.get("fs_hz", 30.0),
        n_samples=spec.get("n_samples", 300),
        window_start_s=start,
        window_end_s=end,
        rejection_reason=spec.get("rejection_reason"),
        analyzed_at_ms=NOW + start * 1000.0,
        session_elapsed_s=spec.get("session_elapsed_s", start),
        window_index=int(start // 10),
    )


def _run_case(case: dict) -> dict:
    collector = S.SessionCollector()
    for spec in case["readings"]:
        reading = _reading(spec)
        collector.add(reading, now_ms=reading.analyzed_at_ms)
    summary = S.summarize_session(collector.readings, lifecycle=case.get("lifecycle", "stopped"))
    hr = next(a for a in summary["metrics"] if a.metric == "heart_rate")
    return {
        "completion": summary["completion"],
        "result_available": summary["result_available"],
        "verdict": hr.verdict,
        "n_accepted": hr.n_accepted,
        "n_rejected": hr.n_rejected,
        "n_independent": hr.n_independent_accepted,
        "mean": None if hr.mean is None else round(hr.mean, 6),
        "median": None if hr.median is None else round(hr.median, 6),
        "sd": None if hr.sd is None else round(hr.sd, 6),
        "acceptance_pct": None if summary["acceptance_pct"] is None else round(summary["acceptance_pct"], 6),
        "density_ratio": None if summary["density_ratio"] is None else round(summary["density_ratio"], 6),
        "uneven_density": summary["uneven_density"],
    }


CASES = [
    # A sliding-window session: many readings, few independent windows.
    {
        "name": "sliding_window_overlap",
        "lifecycle": "running",
        "readings": [
            {"value": 70 + (i % 5), "window_start_s": 0.5 * i, "window_end_s": 0.5 * i + 10}
            for i in range(40)
        ],
    },
    # Non-overlapping windows, enough for a result.
    {
        "name": "non_overlapping_available",
        "lifecycle": "running",
        "readings": [{"value": v, "window_start_s": 10.0 * i, "window_end_s": 10.0 * i + 10}
                     for i, v in enumerate([70, 72, 74, 76, 78])],
    },
    # Same data, capture stopped: a completed session, never "you can stop".
    {
        "name": "non_overlapping_completed",
        "lifecycle": "stopped",
        "readings": [{"value": v, "window_start_s": 10.0 * i, "window_end_s": 10.0 * i + 10}
                     for i, v in enumerate([70, 72, 74, 76, 78])],
    },
    # Mixed verdicts: rejections are counted, never averaged.
    {
        "name": "mixed_verdicts",
        "lifecycle": "running",
        "readings": [
            {"value": 70, "window_start_s": 0, "window_end_s": 10},
            {"value": 72, "window_start_s": 10, "window_end_s": 20},
            {"value": 74, "window_start_s": 20, "window_end_s": 30},
            {"value": 76, "window_start_s": 30, "window_end_s": 40},
            {"value": 78, "window_start_s": 40, "window_end_s": 50},
            {"value": 190, "window_start_s": 50, "window_end_s": 60,
             "quality_verdict": "low_signal_quality", "rejection_reason": "low SNR"},
            {"value": None, "window_start_s": 60, "window_end_s": 70,
             "quality_verdict": "roi_lost", "rejection_reason": "All skin ROIs are lost"},
        ],
    },
    # Nothing accepted: the aggregate must be insufficient everywhere.
    {
        "name": "all_rejected",
        "lifecycle": "running",
        "readings": [
            {"value": None, "window_start_s": 10.0 * i, "window_end_s": 10.0 * i + 10,
             "quality_verdict": "roi_lost", "rejection_reason": "All skin ROIs are lost"}
            for i in range(3)
        ],
    },
    # Same data, capture interrupted: the same shortfall, different meaning.
    {
        "name": "interrupted_short",
        "lifecycle": "interrupted",
        "readings": [{"value": v, "window_start_s": 10.0 * i, "window_end_s": 10.0 * i + 10}
                     for i, v in enumerate([70, 72])],
    },
    # Enough accepted readings, but all over one window: the Sprint 13 bug case.
    {
        "name": "single_window_overlap",
        "lifecycle": "stopped",
        "readings": [{"value": 72, "window_start_s": 100.0, "window_end_s": 110.0}
                     for _ in range(8)],
    },
    # Same, but still capturing: collecting, never "you can stop".
    {
        "name": "single_window_overlap_running",
        "lifecycle": "running",
        "readings": [{"value": 72, "window_start_s": 100.0, "window_end_s": 110.0}
                     for _ in range(8)],
    },
    # Empty session, idle: no session exists yet.
    {"name": "empty", "lifecycle": "stopped", "readings": []},
    # Empty session, capturing: initialising is its own state, not "idle".
    {"name": "empty_running", "lifecycle": "running", "readings": []},
    # Uneven analysis density with a drifting value.
    {
        "name": "uneven_density",
        "lifecycle": "running",
        "readings": (
            [{"value": 70, "window_start_s": 0.5 * k, "window_end_s": 0.5 * k + 10} for k in range(60)]
            + [{"value": 80, "window_start_s": 30 + 4 * k, "window_end_s": 40 + 4 * k} for k in range(15)]
        ),
    },
]


@pytest.fixture(scope="module")
def committed() -> dict:
    if not FIXTURE.is_file():  # pragma: no cover - generated by the helper below
        pytest.skip(f"missing parity fixture {FIXTURE}")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_python_matches_committed_parity_fixture(case: dict, committed: dict):
    expected = committed["cases"][case["name"]]["expected"]
    actual = _run_case(case)
    assert actual == expected, f"{case['name']}: python={actual} fixture={expected}"


def test_fixture_is_synthetic_and_labelled(committed: dict):
    assert committed["schema"] == "rsbvp.session-parity.v1"
    assert "synthetic" in committed["note"].lower()
    assert committed["generated_by"] == "tests/fixtures/generate_session_parity.py"


def test_fixture_covers_every_completion_state(committed: dict):
    states = {c["expected"]["completion"] for c in committed["cases"].values()}
    # Every state the UI can display must be exercised by a fixture, otherwise a
    # state exists that nothing checks.
    assert {"idle", "initialising", "collecting", "insufficient",
            "available", "interrupted", "completed"} <= states
