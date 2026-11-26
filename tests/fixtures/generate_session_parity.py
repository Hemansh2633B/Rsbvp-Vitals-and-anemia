#!/usr/bin/env python3
"""Generate the browser/Python session-aggregation parity fixture.

The fixture is computed from the *Python* implementation and then consumed by
the TypeScript suite (which asserts the same expected values). That ordering is
deliberate: it means a change to either language breaks a test rather than
letting the two silently drift.

Run only when a rule changes intentionally:
    python tests/fixtures/generate_session_parity.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gui"))
sys.path.insert(0, str(ROOT / "tests"))

from test_session_parity import CASES, _run_case  # noqa: E402

OUT = Path(__file__).resolve().parent / "session_aggregation_parity.json"

payload = {
    "schema": "rsbvp.session-parity.v1",
    "note": (
        "Synthetic readings with no dataset and no hardware. Expected values are produced by "
        "gui/rppg_core/session.py and asserted by both test suites; they verify agreement between "
        "the two implementations, not physiological accuracy."
    ),
    "generated_by": "tests/fixtures/generate_session_parity.py",
    "cases": {
        case["name"]: {"lifecycle": case["lifecycle"], "expected": _run_case(case)}
        for case in CASES
    },
}
OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
