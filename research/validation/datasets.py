"""Dataset readiness: what is lawfully available, and what is blocked.

This module **registers** datasets; it does not download them. Downloading a
restricted dataset from an unofficial mirror would violate its licence, and
fabricating one would be worse than having none. A dataset is "ready" only when a
local root has been supplied by someone entitled to have it, and the intake is
verified by a dataset-specific adapter.

Each adapter is deliberately small and lives behind this interface so that
dataset-specific quirks (a MATLAB ``.mat`` ground truth here, a ``.csv`` column
ordering there) cannot leak into the common metrics implementation. The metrics code
never sees a raw dataset file: it sees validated reference intervals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: Canonical access requirements. Written from each provider's own statements; see
#: ``docs/DATA_READINESS.md`` for the fetch dates and the exact wording relied on.
DATASETS: dict[str, dict] = {
    "rppg10": {
        "label": "rPPG-10 (RSBVP's own collection protocol)",
        "access": "project_internal",
        "licence": "Controlled by this project; recordings are not redistributed.",
        "redistributable": False,
        "official_source": "This repository's own acquisition protocol (docs/MANUAL_CAMERA_TESTS.md).",
        "blocker": (
            "No consented recordings with an independent reference exist in the repository. "
            "The protocol and intake path exist; the data does not."),
        "intake": "Follow docs/MANUAL_CAMERA_TESTS.md, capture with a simultaneous reference, "
                  "export the session CSV/JSON and a reference CSV, then run the adapter.",
    },
    "ubfc_rppg": {
        "label": "UBFC-rPPG",
        "access": "request_from_provider",
        "licence": "Research use; redistribution restricted. Obtain from the provider.",
        "redistributable": False,
        "official_source": "https://sites.google.com/view/ybenezeth/ubfcrppg (project page)",
        "blocker": (
            "Requires accepting the provider's terms and obtaining the archive from the provider's "
            "own distribution. The workspace has no authorisation instrument on file, so the "
            "archive is deliberately absent."),
        "intake": "Obtain the archive from the official distribution, keep it outside the "
                  "repository, point RSBVP_UBFC_ROOT at it, and run the adapter (which verifies "
                  "structure and checksums before use).",
    },
    "cohface": {
        "label": "COHFACE",
        "access": "request_from_provider",
        "licence": "Research use on request from the authors.",
        "redistributable": False,
        "official_source": "https://www.epfl.ch/labs/mmspg/downloads/cohface/",
        "blocker": (
            "Requires a signed request to the authors. Not present, and not obtainable "
            "automatically."),
        "intake": "Request access from the authors, keep the archive outside the repository, "
                  "point RSBVP_COHFACE_ROOT at the extracted tree, run the adapter.",
    },
    "mmpd": {
        "label": "MMPD",
        "access": "request_from_provider",
        "licence": "Research use; redistribution restricted.",
        "redistributable": False,
        "official_source": "Project page for MMPD (see docs/ for the recorded reference).",
        "blocker": (
            "Sprint 10 investigated acquisition; the dataset remains unavailable in this workspace "
            "and no redistribution is permitted."),
        "intake": "Obtain through the provider's process, keep outside the repository, point "
                  "RSBVP_MMPD_ROOT at it, run research/mmpd/mmpd_probe.py to verify the layout.",
    },
}


@dataclass
class DatasetStatus:
    key: str
    label: str
    access: str
    licence: str
    official_source: str
    present: bool
    ready: bool
    blocker: str
    intake: str
    root: str | None = None
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "access": self.access,
            "licence": self.licence, "official_source": self.official_source,
            "present": self.present, "ready": self.ready,
            "blocker": self.blocker or None,
            "intake": self.intake, "root": self.root, "details": self.details,
        }


#: An adapter receives a root directory and returns (ready, details_or_blocker).
Adapter = Callable[[Path], tuple[bool, dict]]


def _rppg10_adapter(root: Path) -> tuple[bool, dict]:
    """Our own exports: a session CSV plus a reference CSV in an intake directory."""
    session_files = sorted(root.glob("*session*readings*.csv"))
    reference_files = sorted(root.glob("*reference*.csv"))
    if not session_files:
        return False, {"blocker": f"no *session*readings*.csv under {root}"}
    if not reference_files:
        return False, {"blocker": f"no *reference*.csv under {root}"}
    return True, {"sessions": [p.name for p in session_files],
                  "references": [p.name for p in reference_files]}


def _generic_adapter(expected: str) -> Adapter:
    def adapter(root: Path) -> tuple[bool, dict]:
        if not root.is_dir():
            return False, {"blocker": f"{root} is not a directory"}
        entries = [p.name for p in root.iterdir()][:20]
        if not entries:
            return False, {"blocker": f"{root} is empty"}
        return False, {
            "blocker": (f"the tree does not match the {expected} layout this adapter expects. "
                        "A dataset-specific adapter must be written and reviewed before use; "
                        "guessing at a layout risks reading the wrong column as a reference."),
            "top_level": entries,
        }
    return adapter


ADAPTERS: dict[str, Adapter] = {
    "rppg10": _rppg10_adapter,
    "ubfc_rppg": _generic_adapter("UBFC-rPPG (video + .mat ground truth)"),
    "cohface": _generic_adapter("COHFACE (per-subject AVI + txt)"),
    "mmpd": _generic_adapter("MMPD"),
}

ROOT_ENV_VARS = {
    "rppg10": "RSBVP_RPPG10_ROOT",
    "ubfc_rppg": "RSBVP_UBFC_ROOT",
    "cohface": "RSBVP_COHFACE_ROOT",
    "mmpd": "RSBVP_MMPD_ROOT",
}


def audit(root_override: dict[str, Path] | None = None,
          environ: dict[str, str] | None = None) -> list[DatasetStatus]:
    """Check every registered dataset without downloading anything.

    A dataset is ``ready`` only when a root is present *and* its adapter verifies the
    layout. Everything else is reported as blocked with a precise reason and the
    intake procedure, so the gap is actionable rather than a mystery.
    """
    import os
    env = environ if environ is not None else dict(os.environ)
    overrides = root_override or {}
    statuses: list[DatasetStatus] = []
    for key, spec in DATASETS.items():
        root_text = overrides.get(key) or env.get(ROOT_ENV_VARS[key])
        root = Path(root_text) if root_text else None
        present = bool(root and root.exists())
        ready = False
        details: dict = {}
        blocker = spec["blocker"]
        if present and root is not None:
            try:
                ready, details = ADAPTERS[key](root)
            except Exception as exc:  # noqa: BLE001 - an adapter must not break the audit
                ready, details = False, {"blocker": f"adapter raised: {exc}"}
            if not ready:
                blocker = details.get("blocker", blocker)
        elif root is not None:
            blocker = f"{root} does not exist (from {ROOT_ENV_VARS[key]})"
        statuses.append(DatasetStatus(
            key=key, label=spec["label"], access=spec["access"], licence=spec["licence"],
            official_source=spec["official_source"], present=present, ready=ready,
            # A ready dataset has no blocker. Keeping the standing text here would let a
            # caller that reads the attribute (rather than as_dict) report a dataset as
            # simultaneously ready and blocked.
            blocker="" if ready else blocker,
            intake=spec["intake"], root=str(root) if root else None,
            details=details))
    return statuses


def readiness_summary(statuses: list[DatasetStatus]) -> dict:
    ready = [s.key for s in statuses if s.ready]
    return {
        "datasets_registered": len(statuses),
        "datasets_ready": ready,
        "datasets_blocked": [s.key for s in statuses if not s.ready],
        "any_ready": bool(ready),
        "note": (
            "No dataset is bundled and none was downloaded. Real-world validation requires a "
            "lawfully obtained dataset supplied by the operator; this platform never fabricates "
            "one and never fetches a restricted dataset from an unofficial mirror."),
    }
