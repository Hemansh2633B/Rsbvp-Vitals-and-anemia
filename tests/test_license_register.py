"""License-register validation: completeness, pins, identifiers and isolation."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "OPEN_SOURCE_LICENSE_REGISTER.md"

REQUIRED_TOOLS = [
    "rPPG-Toolbox", "pyVHR", "MediaPipe", "PhysFormer",
    "OpenCV", "NumPy", "SciPy", "pandas", "Matplotlib", "FastAPI",
    "UBFC-rPPG", "COHFACE",
]
REQUIRED_PINS = [
    "b7500b848f84ad7f86e277b4612563b69f4f88f9",  # rPPG-Toolbox
    "a6270f04a97f05a13d145dd0a5e8c8df48d8bd62",  # pyVHR master (v2.0)
    "e39ae5fa30c84c77300d43da5e3b8037fc852a9e",  # pyVHR_CPU branch (v1.2)
    "094c6942e8e7ebedf41dd407415d16bc9db34e1d",  # PhysFormer
]
REQUIRED_IDENTIFIERS = ["RAIL-1.1", "GPL-3.0", "Apache-2.0", "MIT", "BSD-3-Clause", "PSF-2.0"]
REQUIRED_COLUMNS = [
    "Tool", "Source", "License", "Integration method",
    "Attribution requirement", "Redistribution restrictions", "Outstanding legal review",
]


def read_register():
    assert REGISTER.is_file(), "docs/OPEN_SOURCE_LICENSE_REGISTER.md is missing"
    return REGISTER.read_text(encoding="utf-8")


def test_register_lists_required_tools():
    text = read_register()
    for tool in REQUIRED_TOOLS:
        assert tool in text, f"register does not mention {tool}"


def test_register_pins_exact_commits():
    text = read_register()
    for pin in REQUIRED_PINS:
        assert pin in text, f"register does not record pinned commit {pin}"


def test_register_uses_spdx_style_identifiers():
    text = read_register()
    for identifier in REQUIRED_IDENTIFIERS:
        assert identifier in text, f"register does not contain identifier {identifier}"


def test_register_has_required_column_headers():
    text = read_register()
    for column in REQUIRED_COLUMNS:
        assert column in text, f"register is missing a column/section mentioning {column!r}"


def test_register_records_model_checkpoint_policy():
    text = read_register()
    for checkpoint in ("PURE_TSCAN.pth", "UBFC-rPPG_TSCAN.pth",
                       "PURE_PhysFormer_DiffNormalized.pth",
                       "PURE_DeepPhys.pth", "PURE_PhysNet_DiffNormalized.pth",
                       "PURE_EfficientPhys.pth"):
        assert checkpoint in text, f"register does not document checkpoint {checkpoint}"
    assert "RSBVP_MODEL_ROOT" in text
    assert "google" in text.lower() and "rejected" in text.lower()  # PhysFormer VIPL weights rejected


def test_register_has_no_third_party_code_copied_into_backends():
    """No RAIL-1.1 or GPL-3.0 license text may live in the shipped adapter code."""
    backends_dir = ROOT / "research" / "backends"
    for path in backends_dir.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "Responsible Artificial Intelligence Source Code License" not in content, path
        assert "GNU GENERAL PUBLIC LICENSE" not in content, path
        assert "RAIL 1.1" not in content or "RAIL-1.1" in content  # identifier mentions only
    for path in backends_dir.rglob("*.md"):
        assert "GNU GENERAL PUBLIC LICENSE\nVersion 3" not in path.read_text(encoding="utf-8"), path


def test_gitignore_blocks_model_checkpoints():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.pth" in text


def test_rppg_toolbox_adapter_never_claims_mit():
    text = (ROOT / "research" / "backends" / "rppg_toolbox.py").read_text(encoding="utf-8")
    assert "RAIL-1.1" in text
    assert "license_id=\"MIT\"" not in text


def test_pyvhr_adapter_declares_gpl():
    text = (ROOT / "research" / "backends" / "pyvhr.py").read_text(encoding="utf-8")
    assert "GPL-3.0" in text
