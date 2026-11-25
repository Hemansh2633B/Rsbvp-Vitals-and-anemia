"""The deployment environment must be reused, never rebuilt from scratch.

These tests cover the complaints that made this module necessary: a redeploy
recreated the virtual environment and re-downloaded every package. The logic is
tested in a throwaway directory tree so no real network access happens.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deploy_env  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A miniature project tree with every absolute path pointing inside it."""
    venv = tmp_path / ".venv"
    frontend = tmp_path / "gui" / "frontend"
    node_modules = frontend / "node_modules"
    requirements = tmp_path / "requirements.txt"
    package_lock = frontend / "package-lock.json"
    dist = frontend / "dist"
    cache = tmp_path / ".cache" / "deploy"
    for path in (frontend, dist, cache / "wheels", cache / "pip", cache / "npm", node_modules):
        path.mkdir(parents=True, exist_ok=True)
    requirements.write_text("fastapi>=0.1\n", encoding="utf-8")
    package_lock.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(deploy_env, "ROOT", tmp_path)
    monkeypatch.setattr(deploy_env, "VENV", venv)
    monkeypatch.setattr(deploy_env, "REQUIREMENTS", requirements)
    monkeypatch.setattr(deploy_env, "FRONTEND", frontend)
    monkeypatch.setattr(deploy_env, "NODE_MODULES", node_modules)
    monkeypatch.setattr(deploy_env, "PACKAGE_LOCK", package_lock)
    monkeypatch.setattr(deploy_env, "DIST_INDEX", dist / "index.html")
    monkeypatch.setattr(deploy_env, "CACHE_DIR", cache)
    monkeypatch.setattr(deploy_env, "PIP_CACHE", cache / "pip")
    monkeypatch.setattr(deploy_env, "NPM_CACHE", cache / "npm")
    monkeypatch.setattr(deploy_env, "WHEELS", cache / "wheels")
    monkeypatch.setattr(deploy_env, "STAMPS", (venv / deploy_env.REQ_STAMP_NAME,
                                               node_modules / deploy_env.NPM_STAMP_NAME))
    return {"root": tmp_path, "venv": venv, "frontend": frontend,
            "node_modules": node_modules, "requirements": requirements,
            "package_lock": package_lock, "dist": dist, "cache": cache}


def fake_venv(path: Path, version=(3, 11)) -> Path:
    """Create a structurally valid .venv (no real interpreter needed)."""
    bindir = path / ("Scripts" if os.name == "nt" else "bin")
    bindir.mkdir(parents=True, exist_ok=True)
    exe = bindir / ("python.exe" if os.name == "nt" else "python")
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    (path / "pyvenv.cfg").write_text(f"version_info = {version[0]}.{version[1]}.0\n",
                                     encoding="utf-8")
    return exe


# ---------------------------------------------------------------------------
# reuse, not recreate
# ---------------------------------------------------------------------------
def test_existing_venv_is_reused_not_recreated(sandbox, monkeypatch):
    fake_venv(sandbox["venv"])
    monkeypatch.setattr(deploy_env, "python_version", lambda _exe: (3, 11))
    creations = []
    monkeypatch.setattr(deploy_env, "run",
                        lambda *a, **k: creations.append(a) or _Completed(0))

    python, created = deploy_env.ensure_venv()
    assert created is False, "an existing usable .venv must not be recreated"
    assert not creations, "no venv/python command may run when .venv is usable"
    assert Path(python).name.startswith("python")


def test_missing_venv_is_created_exactly_once(sandbox, monkeypatch):
    monkeypatch.setattr(deploy_env, "find_base_python", lambda offline: ["python3"])
    monkeypatch.setattr(deploy_env, "python_version", lambda _exe: (3, 11))
    monkeypatch.setattr(deploy_env, "run",
                        lambda *a, **k: (fake_venv(sandbox["venv"]), _Completed(0))[1])

    python, created = deploy_env.ensure_venv()
    assert created is True
    assert sandbox["venv"].is_dir()


def test_broken_venv_is_repaired_instead_of_used(sandbox, monkeypatch):
    fake_venv(sandbox["venv"])
    (sandbox["venv"] / "pyvenv.cfg").unlink()  # interrupted install
    monkeypatch.setattr(deploy_env, "find_base_python", lambda offline: ["python3"])
    monkeypatch.setattr(deploy_env, "python_version", lambda _exe: (3, 11))
    monkeypatch.setattr(deploy_env, "run",
                        lambda *a, **k: (fake_venv(sandbox["venv"]), _Completed(0))[1])

    python, created = deploy_env.ensure_venv()
    assert created is True
    assert sandbox["venv"].is_dir()
    assert (sandbox["venv"] / "pyvenv.cfg").is_file()


def test_venv_symlink_is_unlinked_not_deleted(sandbox, monkeypatch):
    target = sandbox["root"] / "external-venv"
    fake_venv(target)
    try:
        sandbox["venv"].symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported here")
    monkeypatch.setattr(deploy_env, "find_base_python", lambda offline: ["python3"])
    monkeypatch.setattr(deploy_env, "python_version", lambda _exe: (3, 11))
    monkeypatch.setattr(deploy_env, "run",
                        lambda *a, **k: (fake_venv(sandbox["venv"]), _Completed(0))[1])

    deploy_env.ensure_venv(force_recreate=True)
    assert target.is_dir(), "recreating .venv must never delete the symlink target"


# ---------------------------------------------------------------------------
# packages: install only when needed
# ---------------------------------------------------------------------------
def _completed(rc=0):
    return _Completed(rc)


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_packages_are_not_installed_when_nothing_changed(sandbox, monkeypatch, capsys):
    python = fake_venv(sandbox["venv"])
    digest = deploy_env.file_digest(sandbox["requirements"])
    (sandbox["venv"] / deploy_env.REQ_STAMP_NAME).write_text(digest + "\n", encoding="utf-8")
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (True, []))
    calls = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: calls.append(command) or _Completed())

    result = deploy_env.ensure_packages(python)
    assert result["action"] == "reused"
    assert calls == [], "pip must not run when requirements.txt is unchanged"


def test_packages_are_installed_when_requirements_change(sandbox, monkeypatch):
    python = fake_venv(sandbox["venv"])
    (sandbox["venv"] / deploy_env.REQ_STAMP_NAME).write_text("stale-digest\n", encoding="utf-8")
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (True, []))
    monkeypatch.setattr(deploy_env, "pip_available", lambda _py: True)
    commands = []
    monkeypatch.setattr(deploy_env, "run",
                        lambda command, **k: commands.append(command) or _Completed())

    result = deploy_env.ensure_packages(python)
    assert result["action"] == "installed"
    assert any("pip" in str(part) and "install" in str(part) for part in commands)
    stamp = sandbox["venv"] / deploy_env.REQ_STAMP_NAME
    assert stamp.read_text(encoding="utf-8").strip() == deploy_env.file_digest(
        sandbox["requirements"])


def test_packages_are_installed_when_an_import_is_missing(sandbox, monkeypatch):
    python = fake_venv(sandbox["venv"])
    digest = deploy_env.file_digest(sandbox["requirements"])
    (sandbox["venv"] / deploy_env.REQ_STAMP_NAME).write_text(digest + "\n", encoding="utf-8")
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (False, ["cv2"]))
    monkeypatch.setattr(deploy_env, "pip_available", lambda _py: True)
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: _Completed())

    assert deploy_env.ensure_packages(python)["action"] == "installed"


def test_complete_environment_without_stamp_is_adopted(sandbox, monkeypatch):
    """A .venv built by an older script must not trigger a re-download."""
    python = fake_venv(sandbox["venv"])
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (True, []))
    calls = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: calls.append(command) or _Completed())

    result = deploy_env.ensure_packages(python)
    assert result["action"] == "adopted"
    assert calls == []
    assert (sandbox["venv"] / deploy_env.REQ_STAMP_NAME).is_file()


def test_skip_install_refuses_a_half_installed_environment(sandbox, monkeypatch):
    python = fake_venv(sandbox["venv"])
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (False, ["numpy"]))
    with pytest.raises(deploy_env.DeployError) as excinfo:
        deploy_env.ensure_packages(python, skip=True)
    assert "numpy" in str(excinfo.value)


def test_offline_mode_without_cache_fails_clearly(sandbox, monkeypatch):
    python = fake_venv(sandbox["venv"])
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (False, ["numpy"]))
    monkeypatch.setattr(deploy_env, "pip_available", lambda _py: True)
    with pytest.raises(deploy_env.DeployError) as excinfo:
        deploy_env.ensure_packages(python, offline=True)
    assert "offline" in str(excinfo.value).lower()


def test_offline_mode_installs_from_local_wheels(sandbox, monkeypatch):
    python = fake_venv(sandbox["venv"])
    (sandbox["cache"] / "wheels" / "fastapi-0.1-py3-none-any.whl").write_bytes(b"x")
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (False, ["fastapi"]))
    monkeypatch.setattr(deploy_env, "pip_available", lambda _py: True)
    commands = []
    monkeypatch.setattr(deploy_env, "run",
                        lambda command, **k: commands.append(command) or _Completed())

    deploy_env.ensure_packages(python, offline=True)
    assert any("--no-index" in command for command in commands)


def test_pip_failure_keeps_the_environment(sandbox, monkeypatch):
    python = fake_venv(sandbox["venv"])
    monkeypatch.setattr(deploy_env, "required_modules_import", lambda _py: (False, ["numpy"]))
    monkeypatch.setattr(deploy_env, "pip_available", lambda _py: True)
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: _Completed(1))

    with pytest.raises(deploy_env.DeployError) as excinfo:
        deploy_env.ensure_packages(python)
    assert ".venv" in str(excinfo.value)
    assert sandbox["venv"].is_dir(), "a failed install must not destroy the venv"


# ---------------------------------------------------------------------------
# node_modules
# ---------------------------------------------------------------------------
def test_node_modules_are_reused_when_lockfile_is_unchanged(sandbox, monkeypatch):
    node_modules = sandbox["node_modules"]
    (node_modules / ".package-lock.json").write_text("{}", encoding="utf-8")
    (node_modules / "vite").mkdir()
    lock_digest = deploy_env.file_digest(sandbox["package_lock"])
    (node_modules / deploy_env.NPM_STAMP_NAME).write_text(lock_digest + "\n", encoding="utf-8")
    monkeypatch.setattr(deploy_env, "npm_available", lambda: True)
    calls = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: calls.append(command) or _Completed())

    assert deploy_env.ensure_node_modules()["action"] == "reused"
    assert calls == [], "npm ci deletes node_modules: it must not run on every deploy"


def test_existing_node_modules_are_adopted_without_reinstall(sandbox, monkeypatch):
    node_modules = sandbox["node_modules"]
    (node_modules / ".package-lock.json").write_text("{}", encoding="utf-8")
    (node_modules / "vite").mkdir()
    os.utime(node_modules / ".package-lock.json", None)  # newer than package-lock.json
    monkeypatch.setattr(deploy_env, "npm_available", lambda: True)
    calls = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: calls.append(command) or _Completed())

    assert deploy_env.ensure_node_modules()["action"] == "adopted"
    assert calls == []
    assert (node_modules / deploy_env.NPM_STAMP_NAME).is_file()


def test_stale_node_modules_are_reinstalled(sandbox, monkeypatch):
    node_modules = sandbox["node_modules"]
    (node_modules / ".package-lock.json").write_text("{}", encoding="utf-8")
    (node_modules / "vite").mkdir()
    # an older tree: npm's hidden lockfile predates package-lock.json
    os.utime(node_modules / ".package-lock.json", (1_000_000_000, 1_000_000_000))
    (node_modules / deploy_env.NPM_STAMP_NAME).write_text("old-lock\n", encoding="utf-8")
    monkeypatch.setattr(deploy_env, "npm_available", lambda: True)
    commands = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: commands.append(command) or _Completed())

    assert deploy_env.ensure_node_modules()["action"] == "installed"
    assert any("ci" in command for command in commands)


# ---------------------------------------------------------------------------
# frontend build
# ---------------------------------------------------------------------------
def test_build_is_skipped_when_dist_is_newer_than_sources(sandbox, monkeypatch):
    index = sandbox["dist"] / "index.html"
    os.utime(index, (2_000_000_000, 2_000_000_000))
    for path in (sandbox["frontend"] / "src",):
        path.mkdir(exist_ok=True)
        source = path / "App.jsx"
        source.write_text("x", encoding="utf-8")
        os.utime(source, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(deploy_env, "npm_available", lambda: True)
    calls = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: calls.append(command) or _Completed())

    assert deploy_env.build_frontend()["action"] == "reused"
    assert calls == []


def test_build_runs_when_index_html_is_missing(sandbox, monkeypatch):
    (sandbox["dist"] / "index.html").unlink()
    monkeypatch.setattr(deploy_env, "npm_available", lambda: True)

    def fake_run(command, **kwargs):
        (sandbox["dist"] / "index.html").write_text("<html></html>", encoding="utf-8")
        return _Completed()

    calls = []
    monkeypatch.setattr(deploy_env, "run", lambda command, **k: calls.append(command) or fake_run(command))
    assert deploy_env.build_frontend()["action"] == "built"
    assert calls


# ---------------------------------------------------------------------------
# housekeeping and CLI
# ---------------------------------------------------------------------------
def test_clean_removes_only_generated_files(sandbox, monkeypatch):
    stamp = sandbox["venv"] / deploy_env.REQ_STAMP_NAME
    sandbox["venv"].mkdir(exist_ok=True)
    stamp.write_text("x", encoding="utf-8")
    keep = sandbox["root"] / "user-data.txt"
    keep.write_text("mine", encoding="utf-8")
    monkeypatch.setattr(deploy_env, "ROOT", sandbox["root"])

    removed = deploy_env.clean_artifacts()
    assert not stamp.exists()
    assert keep.is_file(), "--clean must never delete user files"
    assert removed


def test_check_mode_changes_nothing(sandbox, monkeypatch, capsys):
    before = sorted(p.name for p in sandbox["root"].rglob("*"))
    assert deploy_env.main(["--check"]) == 0
    after = sorted(p.name for p in sandbox["root"].rglob("*"))
    assert before == after, "--check must be read-only"
    assert "RSBVP deployment environment" in capsys.readouterr().out


def test_check_mode_json_is_parseable(sandbox, monkeypatch, capsys):
    import json as _json

    assert deploy_env.main(["--check", "--print-json"]) == 0
    payload = _json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "venv" in payload and "node_modules" in payload and "frontend" in payload


def test_offline_environment_variable_is_honoured(sandbox, monkeypatch):
    seen = {}

    def fake_ensure_venv(force_recreate=False, offline=False):
        seen["offline"] = offline
        return Path("python"), False

    monkeypatch.setenv("RSBVP_OFFLINE", "1")
    monkeypatch.setattr(deploy_env, "ensure_venv", fake_ensure_venv)
    monkeypatch.setattr(deploy_env, "ensure_packages", lambda *a, **k: {"action": "reused"})
    deploy_env.main(["--python-only"])
    assert seen["offline"] is True
