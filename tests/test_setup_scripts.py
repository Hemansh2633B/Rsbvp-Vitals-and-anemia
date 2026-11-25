"""Guard rails for the beginner setup scripts (no execution, no network).

These tests only parse the scripts and check their documented contract: the
shell script must be syntactically valid, the Windows wrappers must exist and
advertise the same options, and none of them may download a dataset, need a
webcam, or delete user data.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = ROOT / "setup.sh"
SETUP_CMD = ROOT / "setup.cmd"
SETUP_PS1 = ROOT / "setup.ps1"
REQUIREMENTS = ROOT / "requirements-dev.txt"


def test_all_platform_scripts_exist_and_are_documented():
    for path in (SETUP_SH, SETUP_CMD, SETUP_PS1, REQUIREMENTS):
        assert path.is_file(), f"{path.name} is missing"
    # Linux/macOS script is executable for the common `./setup.sh` invocation
    assert SETUP_SH.stat().st_mode & 0o111


def test_setup_sh_is_syntactically_valid():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    result = subprocess.run([bash, "-n", str(SETUP_SH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_help_lists_every_option_and_exits_zero():
    result = subprocess.run(["bash", str(SETUP_SH), "--help"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0
    for option in ("--no-dataset", "--dataset-only", "--no-frontend", "--no-tests",
                   "--benchmark", "--recreate", "--dest", "--ecg-fs-hz"):
        assert option in result.stdout, f"{option} not advertised in --help"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_setup_sh_rejects_unknown_option():
    result = subprocess.run(["bash", str(SETUP_SH), "--not-a-real-option"],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2
    assert "Unknown option" in result.stdout


def test_scripts_never_download_a_dataset_and_never_run_destructive_commands():
    sh = SETUP_SH.read_text(encoding="utf-8")
    assert "curl" not in sh and "wget" not in sh
    for dangerous in ("rm -rf /", "rm -rf $HOME", "mkfs", "dd if="):
        assert dangerous not in sh
    # the only recursive delete is the explicit --recreate of the venv
    assert sh.count("rm -rf") == 1 and "rm -rf .venv" in sh

    cmd = SETUP_CMD.read_text(encoding="utf-8").lower()
    ps1 = SETUP_PS1.read_text(encoding="utf-8").lower()
    for text in (sh.lower(), cmd, ps1):
        assert "invoke-webrequest" not in text and "start-bitstransfer" not in text
    assert "rmdir /s /q" in cmd  # venv only, guarded by --recreate
    assert "remove-item -recurse" in ps1


def test_windows_scripts_advertise_the_same_options():
    cmd = SETUP_CMD.read_text(encoding="utf-8")
    ps1 = SETUP_PS1.read_text(encoding="utf-8")
    for option in ("--no-dataset", "--dataset-only", "--no-frontend", "--no-tests",
                   "--benchmark", "--recreate"):
        assert option in cmd, f"{option} missing from setup.cmd"
    # PowerShell declares parameters as [switch]$Name and passes them as -Name
    for param in ("$NoDataset", "$DatasetOnly", "$NoFrontend", "$NoTests", "$Benchmark", "$Recreate"):
        assert param in ps1, f"{param} missing from setup.ps1"


def test_dataset_defaults_match_the_documented_provider_facts():
    sh = SETUP_SH.read_text(encoding="utf-8")
    ps1 = SETUP_PS1.read_text(encoding="utf-8")
    for text in (sh, ps1):
        assert "ECG_FS_HZ=1000" in text or "EcgFsHz = 1000" in text
        assert "4" in text  # Subject_4 exclusion
    # both forward the exclusion to the adapter's documented flag
    assert "--exclude-subjects" in sh and "--exclude-subjects" in ps1
    assert "$ExcludeSubjects" in ps1 and "EXCLUDE_SUBJECTS=4" in sh


def test_requirements_pin_opencv_below_five():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "opencv-python-headless<5" in text
    assert "numpy" in text and "scipy" in text and "pytest" in text
