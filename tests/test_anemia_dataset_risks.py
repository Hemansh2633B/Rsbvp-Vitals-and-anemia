"""Dataset-audit risks that block a supervised anemia experiment.

The project has no verified anemia model and no authorized imaging dataset. What
it can do is refuse to look ready when it is not: missing laboratory Hb, missing
participant identifiers, duplicated images, the same participant on both sides of
a future split, unusable ROI masks and drifted image-to-label joins.

Evidence category: TESTED-SOFTWARE on synthetic records. Nothing here touches,
validates or implies a clinical measurement.
"""
from __future__ import annotations

import numpy as np
import pytest

from research.anemia.audit_dataset import HB_SANITY_G_DL, _hb_status, audit_rows
from research.anemia import contract


def row(image_id="a", sha="h1", patient="p1", hb="12.4", near="", **extra):
    base = {"image_id": image_id, "sha256": sha, "patient_id": patient,
            "hemoglobin": hb, "near_duplicate_group": near, "unmatched_label_ids": []}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# hemoglobin values
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,status", [
    ("12.4", "present"),
    ("", "missing"),
    ("   ", "missing"),
    (None, "missing"),
    ("n/a", "invalid"),
    ("-3", "invalid"),
    ("99", "invalid"),
    ("nan", "invalid"),
])
def test_hemoglobin_cell_classification(raw, status):
    assert _hb_status(raw)[0] == status


def test_hemoglobin_sanity_bound_is_documented_as_non_clinical():
    low, high = HB_SANITY_G_DL
    assert low < high
    assert low >= 0, "a negative value is a defect, not a measurement"
    assert high <= 30, "this is a sanity window, not a clinical range"


def test_missing_hemoglobin_blocks_supervised_training():
    risks = audit_rows([row("a"), row("b", sha="h2", hb="")])
    assert risks["hemoglobin_missing_count"] == 1
    assert "hemoglobin_not_available_for_every_image" in risks["supervised_training_blockers"]
    assert risks["supervised_training_ready"] is False


def test_missing_patient_id_blocks_participant_separated_splits():
    risks = audit_rows([row("a"), row("b", sha="h2", patient="")])
    assert risks["patient_id_missing_count"] == 1
    assert "patient_id_missing" in risks["supervised_training_blockers"]
    # leakage: without an id this image cannot be kept out of the test split
    assert risks["supervised_training_ready"] is False


def test_a_clean_synthetic_dataset_reports_ready():
    risks = audit_rows([row("a"), row("b", sha="h2")])
    assert risks["supervised_training_blockers"] == []
    assert risks["supervised_training_ready"] is True


# ---------------------------------------------------------------------------
# duplicates
# ---------------------------------------------------------------------------
def test_exact_duplicate_images_are_reported_with_their_ids():
    risks = audit_rows([row("a", sha="same"), row("b", sha="same")])
    assert risks["exact_duplicate_groups"] == 1
    assert ["a", "b"] in risks["exact_duplicate_image_ids"]
    assert "exact_duplicate_images" in risks["supervised_training_blockers"]


def test_near_duplicates_are_reported_as_a_review_signal():
    risks = audit_rows([row("a", near="1"), row("b", sha="h2", near="1")])
    assert risks["near_duplicate_groups"] == 1
    assert risks["near_duplicate_image_ids"][0] == ["a", "b"]


# ---------------------------------------------------------------------------
# participant leakage
# ---------------------------------------------------------------------------
def test_participants_with_multiple_images_are_counted_for_split_awareness():
    risks = audit_rows([row("a"), row("b", sha="h2"), row("c", sha="h3", patient="p2")])
    assert risks["patients"] == 2
    assert risks["patients_with_multiple_images"] == 1


def test_conflicting_hemoglobin_for_one_participant_is_a_blocker():
    risks = audit_rows([row("a", hb="12.4"), row("b", sha="h2", hb="9.1")])
    assert risks["participants_with_conflicting_hemoglobin"] == ["p1"]
    assert "inconsistent_hemoglobin_per_participant" in risks["supervised_training_blockers"]


def test_repeated_identical_hemoglobin_is_not_a_conflict():
    risks = audit_rows([row("a", hb="12.4"), row("b", sha="h2", hb="12.40")])
    assert risks["participants_with_conflicting_hemoglobin"] == []


# ---------------------------------------------------------------------------
# label join drift
# ---------------------------------------------------------------------------
def test_unmatched_label_ids_are_reported():
    risks = audit_rows([row("a", unmatched_label_ids=["ghost"])])
    assert risks["unmatched_label_count"] == 1
    assert risks["unmatched_label_ids"] == ["ghost"]


# ---------------------------------------------------------------------------
# unsupported / invalid image and ROI inputs (contract layer)
# ---------------------------------------------------------------------------
def _write_png(path, shape=(64, 64, 3)):
    import cv2

    rng = np.random.default_rng(0)
    image = (rng.random(shape) * 255).astype("uint8")
    assert cv2.imwrite(str(path), image)
    return path


def test_unsupported_image_format_is_rejected(tmp_path):
    bad = tmp_path / "eye.txt"
    bad.write_text("not an image", encoding="utf-8")
    with pytest.raises(contract.ContractError) as excinfo:
        contract.load_image_contract(bad)
    assert excinfo.value.code == contract.ERR_UNREADABLE


def test_grayscale_conjunctiva_image_is_rejected(tmp_path):
    import cv2

    path = tmp_path / "gray.png"
    cv2.imwrite(str(path), np.zeros((64, 64), dtype="uint8"))
    with pytest.raises(contract.ContractError) as excinfo:
        contract.load_image_contract(path)
    assert excinfo.value.code == contract.ERR_EXPECTED_COLOR


def test_missing_roi_mask_is_rejected(tmp_path):
    image = _write_png(tmp_path / "eye.png")
    record = {
        "schema": contract.SCHEMA_ANNOTATION,
        "image_id": "eye",
        "sha256": contract.sha256_file(image),
        "patient_id": "p1",
        "roi": {"type": "mask_png", "path": str(tmp_path / "missing_mask.png")},
        "annotator": {"id": "r1", "researcher_reviewed": True},
        "provenance": {"source": "synthetic-test"},
    }
    result = contract.validate_annotation(record)
    assert result["valid"] is False
    assert any(err.startswith(contract.ERR_MASK_INVALID) or
               err.startswith(contract.ERR_MISSING_FIELD) for err in result["errors"])


def test_missing_patient_id_is_rejected_by_the_contract(tmp_path):
    image = _write_png(tmp_path / "eye.png")
    record = {
        "schema": contract.SCHEMA_ANNOTATION,
        "image_id": "eye",
        "sha256": contract.sha256_file(image),
        "roi": {"type": "polygon", "points": [[1, 1], [20, 1], [20, 20]], "image_width": 64, "image_height": 64},
        "annotator": {"id": "r1", "researcher_reviewed": True},
        "provenance": {"source": "synthetic-test"},
    }
    result = contract.validate_annotation(record)
    assert contract.ERR_MISSING_PATIENT in result["errors"]
