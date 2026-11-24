"""Reproducibility block for benchmark runs (additive to summary.json).

Records the software version/commit, platform and key dependency versions,
and the exact benchmark configuration. Additive field on
``rsbvp.benchmark-summary.v1``; consumers must tolerate unknown keys.
Nothing here authenticates dataset provenance — that remains the user's
responsibility (see docs/REMAINING_EXTERNAL_REQUIREMENTS.md).
"""
from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

SOFTWARE_VERSION = "1.0.0"  # matches CITATION.cff; keep identical to gui/rppg_core/version.py
RUN_INFO_SCHEMA = "rsbvp.benchmark-run.v1"


def git_commit() -> str:
    import os
    import subprocess
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


def _dep_version(module_name: str) -> str | None:
    try:
        import importlib
        return importlib.import_module(module_name).__version__
    except Exception:
        return None


def environment_info() -> dict:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "numpy": _dep_version("numpy"),
        "scipy": _dep_version("scipy"),
        "opencv": _dep_version("cv2"),
        "platform": platform.platform(),
    }


def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_report(*, configuration: dict, manifest_path=None) -> dict:
    manifest_sha = sha256_file(manifest_path) if manifest_path else None
    return {
        "schema_version": RUN_INFO_SCHEMA,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "software": {"name": "RSBVP", "version": SOFTWARE_VERSION, "commit": git_commit()},
        "environment": environment_info(),
        "configuration": dict(configuration),
        "manifest_sha256": manifest_sha,
    }
