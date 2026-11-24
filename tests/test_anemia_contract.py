"""Sprint 8 anemia-foundation contract tests: standardized decoding + annotation
validation. No model, no hemoglobin estimation; software verification only."""
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui"))
from research.anemia import contract
from research.anemia.contract import ContractError


def _img(path, shape=(140, 180, 3), dtype=np.uint8, seed=1):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, shape, dtype=dtype)
    cv2.imwrite(str(path), arr)
    return arr


def _record(img_path, **overrides):
    rec = {
        "schema": contract.SCHEMA_ANNOTATION,
        "image_id": Path(img_path).stem,
        "image_sha256": contract.sha256_file(img_path),
        "patient_id": "patient_001",
        "roi": {"type": "polygon", "points": [[10, 10], [120, 10], [120, 120], [10, 120]],
                "image_width": 180, "image_height": 140},
        "annotator": {"annotator_id": "researcher_a", "reviewed": True,
                      "reviewed_by": "researcher_b", "review_utc": "2026-11-20T00:00:00Z"},
        "provenance": {"source": "internal-capture-2026",
                       "consent_or_permission_ref": "consent-form-ref-7",
                       "license_or_terms": "research-use-only"},
    }
    rec.update(overrides)
    return rec


def test_load_8bit_color_image_contract(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    rgb, meta = contract.load_image_contract(img_path)
    assert rgb.ndim == 3 and rgb.shape[2] == 3 and rgb.dtype == np.uint8
    assert meta["width"] == 180 and meta["height"] == 140
    assert meta["dtype_original"] == "uint8" and not meta["converted"]
    assert meta["sha256"] == contract.sha256_file(img_path)
    assert meta["color_space"] == "RGB"


def test_load_16bit_converts_by_rounding(tmp_path):
    img_path = tmp_path / "img_16.png"
    arr = np.full((130, 170, 3), 65535, dtype=np.uint16)
    cv2.imwrite(str(img_path), arr)
    rgb, meta = contract.load_image_contract(img_path)
    assert meta["bit_depth_converted"] is True and rgb.dtype == np.uint8
    assert int(rgb.max()) == 255


def test_load_drops_alpha_with_note(tmp_path):
    img_path = tmp_path / "img_rgba.png"
    cv2.imwrite(str(img_path), np.full((130, 170, 4), 128, dtype=np.uint8))
    rgb, meta = contract.load_image_contract(img_path)
    assert meta["alpha_dropped"] is True and rgb.shape[2] == 3


def test_load_rejects_grayscale_and_garbage(tmp_path):
    gray_path = tmp_path / "gray.png"
    cv2.imwrite(str(gray_path), np.full((130, 170), 100, dtype=np.uint8))
    with pytest.raises(ContractError) as exc:
        contract.load_image_contract(gray_path)
    assert exc.value.code == contract.ERR_EXPECTED_COLOR
    bad = tmp_path / "not_an_image.png"
    bad.write_bytes(b"this is not an image")
    with pytest.raises(ContractError) as exc:
        contract.load_image_contract(bad)
    assert exc.value.code == contract.ERR_UNREADABLE


def test_validate_annotation_accepts_complete_record(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    out = contract.validate_annotation(_record(img_path), image_path=img_path)
    assert out == {"valid": True, "errors": []}


def test_validate_annotation_reports_hash_mismatch_and_missing_patient(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    rec = _record(img_path, image_sha256="0" * 64, patient_id="")
    out = contract.validate_annotation(rec, image_path=img_path)
    assert not out["valid"]
    assert contract.ERR_HASH_MISMATCH in out["errors"]
    assert contract.ERR_MISSING_PATIENT in out["errors"]


def test_validate_annotation_requires_researcher_review(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    rec = _record(img_path)
    rec["annotator"] = {"annotator_id": "researcher_a", "reviewed": False}
    out = contract.validate_annotation(rec)
    assert contract.ERR_UNREVIEWED in out["errors"]
    assert any(e.startswith(contract.ERR_MISSING_FIELD) for e in out["errors"])


def test_validate_annotation_polygon_bounds_and_mask_check(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    rec = _record(img_path)
    rec["roi"] = {"type": "polygon", "points": [[-5, 10], [120, 10], [120, 120]],
                  "image_width": 180, "image_height": 140}
    out = contract.validate_annotation(rec)
    assert contract.ERR_BAD_POLYGON in out["errors"]
    mask_path = tmp_path / "mask_001.png"
    cv2.imwrite(str(mask_path), np.zeros((140, 180), dtype=np.uint8))  # 0 pixels: too small
    rec2 = _record(img_path)
    rec2["roi"] = {"type": "mask_png", "path": "mask_001.png", "image_width": 180, "image_height": 140}
    out2 = contract.validate_annotation(rec2, image_root=tmp_path)
    assert any(e.startswith(contract.ERR_MASK_INVALID) for e in out2["errors"])


def test_validate_annotation_jsonl_aggregates_line_errors(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    good = _record(img_path)
    bad = {"schema": "nope"}
    jsonl = tmp_path / "annotations.jsonl"
    jsonl.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\nnot-json\n")
    results = contract.validate_annotation_file(jsonl, image_root=tmp_path)
    assert len(results) == 3
    assert results[0]["valid"] is True
    assert results[1]["valid"] is False
    assert results[2]["valid"] is False and results[2]["errors"][0].startswith(contract.ERR_BAD_SCHEMA)


def test_hemoglobin_sanity_bound_is_not_a_clinical_range(tmp_path):
    img_path = tmp_path / "img_001.png"
    _img(img_path)
    rec = _record(img_path, labels={"hemoglobin_g_dl": -3.0})
    out = contract.validate_annotation(rec)
    assert contract.ERR_BAD_HEMOGLOBIN in out["errors"]
