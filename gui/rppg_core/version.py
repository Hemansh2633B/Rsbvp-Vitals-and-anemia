"""Software-version and provenance helpers (stdlib only).

Single source for the project software version. Commit resolution order:
``RSBVP_GIT_SHA`` environment variable (set this in release builds), otherwise
``git rev-parse --short=12 HEAD`` in the repository root, otherwise
``'unknown'``. Never raises.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SOFTWARE_VERSION = "1.0.0"  # matches CITATION.cff version
SOFTWARE_NAME = "RSBVP"

_REPO_ROOT = Path(__file__).resolve().parents[2]


def git_commit() -> str:
    env = (os.environ.get("RSBVP_GIT_SHA") or "").strip()
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def software_info() -> dict:
    """Minimal, dependency-free provenance for exports and reports."""
    return {"name": SOFTWARE_NAME, "version": SOFTWARE_VERSION, "commit": git_commit()}
