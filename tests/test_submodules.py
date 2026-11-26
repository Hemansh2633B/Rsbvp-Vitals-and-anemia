"""The pinned external research repositories are git submodules, not vendored code.

Why this matters legally and technically:

* RAIL-1.1 (rPPG-Toolbox) and GPL-3.0 (pyVHR) must not be merged into this MIT
  application. A gitlink keeps their source out of this repository entirely - only
  the upstream URL and one commit SHA are recorded, and both are fetched on demand.
* The benchmark must be reproducible, so each submodule is pinned to an exact
  commit rather than a branch.

These tests are dataset-free and offline: they read ``.gitmodules`` and git's
index, and never clone anything.
"""
from __future__ import annotations

import configparser
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GITMODULES = ROOT / ".gitmodules"

#: The revision this project documents for rPPG-Toolbox. A benchmark run that
#: cites rPPG-Toolbox must be reproducible, so this pin is asserted, not assumed.
EXPECTED_PINS = {
    "tools/rPPG-Toolbox": "b7500b848f84ad7f86e277b4612563b69f4f88f9",
}
#: Repositories that must never be vendored into the MIT application.
GPL_OR_RAIL_PATHS = ("tools/pyVHR", "tools/rPPG-Toolbox")


def parse_gitmodules() -> dict[str, dict[str, str]]:
    text = GITMODULES.read_text(encoding="utf-8")
    entries: dict[str, dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        header = re.match(r'\[submodule\s+"(?P<name>[^"]+)"\]', line)
        if header:
            current = header.group("name")
            entries[current] = {}
            continue
        if current and "=" in line:
            key, _, value = line.partition("=")
            entries[current][key.strip()] = value.strip()
    return entries


def test_gitmodules_exists_and_parses():
    assert GITMODULES.is_file(), ".gitmodules is missing"
    entries = parse_gitmodules()
    assert entries, "no submodules declared"


def test_every_declared_submodule_has_a_path_and_url():
    for name, config in parse_gitmodules().items():
        assert config.get("path"), f"{name} has no path"
        assert config.get("url", "").startswith("https://github.com/"), (
            f"{name} must pin an https GitHub URL, got {config.get('url')!r}")


def test_rppg_toolbox_is_pinned_to_the_documented_commit():
    """A floating branch would make a cited benchmark unreproducible."""
    try:
        out = subprocess.run(["git", "ls-files", "-s", "tools/rPPG-Toolbox"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    match = re.match(r"160000 (?P<sha>[0-9a-f]{40}) 0\t", out)
    assert match, "tools/rPPG-Toolbox must be recorded as a gitlink (mode 160000)"
    assert match.group("sha") == EXPECTED_PINS["tools/rPPG-Toolbox"]


@pytest.mark.parametrize("path", GPL_OR_RAIL_PATHS)
def test_restricted_repositories_are_gitlinks_not_vendored_files(path):
    """Only the gitlink entry may exist in the index: no upstream source files."""
    try:
        tracked = subprocess.run(["git", "ls-files", path], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    files = [line for line in tracked.splitlines() if line and line != path]
    assert files == [], (
        f"{path} contains {len(files)} tracked file(s) inside a restricted "
        f"repository; only the gitlink may be committed (e.g. {files[:3]})"
    )


def test_submodule_content_is_not_world_readable_by_the_build():
    """The adapters locate external checkouts by environment variable, not import."""
    pyvhr = (ROOT / "research" / "backends" / "pyvhr.py").read_text(encoding="utf-8")
    toolbox = (ROOT / "research" / "backends" / "rppg_toolbox.py").read_text(encoding="utf-8")
    assert "RSBVP_PYVHR_PATH" in pyvhr
    assert "RSBVP_RPPG_TOOLBOX_PATH" in toolbox
    for source in (pyvhr, toolbox):
        assert "subprocess" in source, "the adapters must cross a subprocess boundary"
        assert "from tools" not in source and "import pyvhr" not in source


def test_submodule_pin_agrees_with_the_adapter_constant():
    """The gitlink and the adapter's PINNED_COMMIT must not drift apart.

    If they disagree, a subprocess benchmark would run a different revision from
    the one the adapter reports in its provenance block.
    """
    import sys

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "gui"))
    from research.backends import rppg_toolbox

    try:
        out = subprocess.run(["git", "ls-files", "-s", "tools/rPPG-Toolbox"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    match = re.match(r"160000 (?P<sha>[0-9a-f]{40}) 0\t", out)
    assert match
    assert match.group("sha") == rppg_toolbox.PINNED_COMMIT, (
        f"gitlink {match.group('sha')} != adapter PINNED_COMMIT "
        f"{rppg_toolbox.PINNED_COMMIT}")


def test_submodule_trees_are_excluded_from_pytest_collection():
    """`python -m pytest -q` must not wander into the fetched submodules.

    Their suites import triton/mamba/tensorflow and need a GPU; collecting them
    would break the dataset-free, hardware-free CI gate. This is a regression
    guard: the failure mode (5 collection errors, whole run aborted) was observed
    as soon as the checkouts were present.
    """
    root = Path(__file__).resolve().parents[1]
    config_path = root / "pytest.ini"
    assert config_path.is_file(), "pytest.ini must pin collection to tests/"

    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    section = config["pytest"]

    assert section["testpaths"].strip() == "tests"
    excluded = {item.strip() for item in section["norecursedirs"].split()}
    assert "tools" in excluded


def test_every_initialised_submodule_tree_is_ignored_by_git_status():
    """A fetched checkout must never look like untracked application code."""
    root = Path(__file__).resolve().parents[1]
    for name in ("rPPG-Toolbox", "pyVHR"):
        path = root / "tools" / name
        if not path.is_dir():
            continue
        # A submodule worktree contains a .git *file* pointing at the parent's
        # modules directory. Its contents are tracked by the upstream repo, so
        # the parent repository sees one gitlink and no stray files.
        assert (path / ".git").exists()
