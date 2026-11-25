"""Guard rails for the deployment scripts (parsing only: no servers, no network).

These tests encode the failures that actually broke the first version of the
scripts, so they cannot silently come back:

* non-ASCII bytes or wrong line endings (the "garbage output" on Windows);
* CRLF on a .sh file (the "bad interpreter: bash^M" error on macOS/Linux);
* a deployment script that runs the test suite instead of deploying;
* a script that downloads data or needs a webcam/GPU to deploy.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "deploy.sh": ROOT / "deploy.sh",
    "deploy.cmd": ROOT / "deploy.cmd",
    "deploy.ps1": ROOT / "deploy.ps1",
}
SERVER = ROOT / "deploy_server.py"
ENV_MODULE = ROOT / "deploy_env.py"
REQUIREMENTS = ROOT / "requirements.txt"
GITATTRIBUTES = ROOT / ".gitattributes"


def test_all_platform_deploy_scripts_exist():
    for path in (*SCRIPTS.values(), SERVER, ENV_MODULE, REQUIREMENTS, GITATTRIBUTES):
        assert path.is_file(), f"{path.name} is missing"
    assert SCRIPTS["deploy.sh"].stat().st_mode & 0o111, "deploy.sh must be executable"


@pytest.mark.parametrize("name", list(SCRIPTS))
def test_scripts_are_plain_ascii(name):
    """Non-ASCII text is what made cmd.exe print mojibake instead of messages."""
    data = SCRIPTS[name].read_bytes()
    offenders = [(i, b) for i, b in enumerate(data) if b > 127]
    assert not offenders, f"{name} contains non-ASCII bytes at offsets {offenders[:5]}"


@pytest.mark.parametrize("name", ["deploy.cmd", "deploy.ps1"])
def test_windows_scripts_use_crlf_and_no_bare_lf(name):
    data = SCRIPTS[name].read_bytes()
    crlf = data.count(b"\r\n")
    bare = data.count(b"\n") - crlf
    assert crlf > 20, f"{name} should be CRLF"
    assert bare == 0, f"{name} has {bare} bare LF line(s); cmd.exe mis-parses those"


def test_env_module_is_plain_ascii_and_lf():
    data = ENV_MODULE.read_bytes()
    assert not [b for b in data if b > 127], "deploy_env.py must stay ASCII"
    assert b"\r\n" not in data
    result = subprocess.run([sys.executable, "-m", "py_compile", str(ENV_MODULE)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shell_script_uses_lf_only():
    data = SCRIPTS["deploy.sh"].read_bytes()
    assert b"\r\n" not in data, "deploy.sh must use LF; CRLF breaks the #! line"
    assert data.startswith(b"#!")


def test_gitattributes_protects_line_endings():
    text = GITATTRIBUTES.read_text(encoding="utf-8")
    assert "*.sh   text eol=lf" in text
    assert "*.cmd  text eol=crlf" in text
    assert "*.ps1  text eol=crlf" in text


def test_shell_script_is_syntactically_valid():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    result = subprocess.run([bash, "-n", str(SCRIPTS["deploy.sh"])], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_help_advertises_every_option_and_unknown_option_fails():
    help_run = subprocess.run(["bash", str(SCRIPTS["deploy.sh"]), "--help"],
                              capture_output=True, text=True, cwd=ROOT)
    assert help_run.returncode == 0
    for option in ("--host", "--port", "--open", "--stop", "--foreground", "--skip-install"):
        assert option in help_run.stdout

    bad_run = subprocess.run(["bash", str(SCRIPTS["deploy.sh"]), "--nope"],
                             capture_output=True, text=True, cwd=ROOT)
    assert bad_run.returncode == 2
    assert "Unknown option" in bad_run.stdout


def test_scripts_deploy_instead_of_testing():
    """Deployment scripts must not run the test suite (that is CI's job)."""
    for name, path in SCRIPTS.items():
        text = path.read_text(encoding="utf-8")
        assert "pytest" not in text, f"{name} must not run pytest"
        assert "npm test" not in text, f"{name} must not run the frontend test suite"
        assert "deploy_server.py" in text, f"{name} must start the deployed service"
        assert "deploy_env.py" in text, f"{name} must prepare the environment via deploy_env.py"


def test_scripts_never_install_directly():
    """Installation decisions live in deploy_env.py, so no OS script may bypass it.

    A bare `pip install` or `npm ci` in a shell script is exactly what caused the
    "it re-downloads everything on every deploy" complaint.
    """
    for name, path in SCRIPTS.items():
        text = path.read_text(encoding="utf-8")
        for forbidden in ("pip install", "npm ci", "npm install", "npm run build"):
            assert forbidden not in text, (
                f"{name} must not run {forbidden!r} directly - delegate to deploy_env.py")


def test_scripts_expose_the_cache_controls():
    """Every script must offer the same cache controls, in its own syntax."""
    controls = {
        "deploy.sh": ["--status", "--offline", "--recreate", "--rebuild", "--skip-install"],
        # PowerShell uses -Switch parameters, not --flags
        # (PowerShell declares them as $Status/$Offline/...)
        "deploy.ps1": ["$Status", "$Offline", "$Recreate", "$Rebuild", "$SkipInstall"],
        "deploy.cmd": ["--status", "--offline", "--recreate", "--rebuild", "--skip-install"],
    }
    for name, flags in controls.items():
        text = SCRIPTS[name].read_text(encoding="utf-8")
        for flag in flags:
            assert flag in text, f"{name} should expose {flag}"


def test_scripts_do_not_download_data_or_need_hardware():
    for name, path in SCRIPTS.items():
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in ("curl ", "wget ", "invoke-webrequest", "start-bitstransfer", "rm -rf /", "rmdir /s /q"):
            assert forbidden not in text, f"{name} must not contain {forbidden!r}"


def test_runtime_requirements_cover_the_server():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    for package in ("fastapi", "uvicorn", "python-multipart", "opencv-python-headless<5"):
        assert package in text, f"{package} missing from requirements.txt"


def test_gitignore_covers_the_deployment_cache():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".cache/deploy/" in text
    assert ".run/" in text


def test_server_entry_point_exposes_documented_flags():
    text = SERVER.read_text(encoding="utf-8")
    for flag in ("--dist", "--host", "--port", "--open", "--stop", "--check", "--foreground"):
        assert flag in text, f"{flag} missing from deploy_server.py"
    # the deployment must fail loudly rather than serve an API with no UI
    assert "index.html" in text and "RSBVP_FRONTEND_DIST" in text


def test_frontend_static_serving_is_wired_into_the_backend():
    """The deploy scripts rely on RSBVP_FRONTEND_DIST making the app serve the SPA."""
    text = (ROOT / "gui" / "backend" / "main.py").read_text(encoding="utf-8")
    assert "RSBVP_FRONTEND_DIST" in text
    assert "StaticFiles" in text and 'app.mount("/"' in text
    # a missing build must produce a clear error, not an empty page
    assert "503" in text
    # dev-server CORS must not be hardcoded to a single port any more
    assert "allow_origin_regex" in text
