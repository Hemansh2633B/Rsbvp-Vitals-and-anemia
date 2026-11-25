"""Sprint 10 regression tests for the composite anemia-image QA layer.

Software behavior only -- no physiological validation is implied. Modeled on
tests/test_quality.py and tests/test_anemia_*.py. Every fixture is synthetic;
no hardware, no dataset and no model is involved.
"""
import cv2
import numpy as np
import pytest

from anemia_core.image_features import assess_image, validate_mask
from anemia_core.quality import (
    ERR_ANNOTATION_NOT_REVIEWED,
    ERR_EXPECTED_COLOR_IMAGE,
    ERR_IMAGE_HASH_MISMATCH,
    ERR_IMAGE_UNREADABLE,
    ERR_IMAGE_TOO_SMALL,
    ERR_LOW_ILLUMINATION,
    ERR_MASK_COVERS_FULL_FRAME,
    ERR_MASK_SHAPE_MISMATCH,
    ERR_MASK_TOO_SMALL,
    ERR_NON_FINITE_PIXELS,
    QA_Verdict,
    build_composite_qa,
)
from research.anemia import contract

IMAGE_SHAPE = (200, 240, 3)  # height, width, channels


def _clean_image():
    # Well-exposed, finite, colour, above the minimum dimensions.
    yy, xx = np.indices(IMAGE_SHAPE[:2])
    return ((xx * 7 + yy * 11) % 180 + 35).astype(np.uint8)[:, :, None].repeat(3, axis=2)


def _clean_mask():
    mask = np.zeros(IMAGE_SHAPE[:2], bool)
    mask[50:150, 60:180] = True
    return mask


def _clean_record(image_id="img_clean", image_sha256="", reviewed=True):
    return {
        "schema": contract.SCHEMA_ANNOTATION,
        "image_id": image_id,
        "image_sha256": image_sha256,
        "patient_id": "patient_001",
        "roi": {"type": "polygon",
                "points": [[10, 10], [120, 10], [120, 120], [10, 120]],
                "image_width": IMAGE_SHAPE[1], "image_height": IMAGE_SHAPE[0]},
        "annotator": {"annotator_id": "researcher_a",
                      "reviewed": reviewed,
                      "reviewed_by": "researcher_b",
                      "review_utc": "2026-11-20T00:00:00Z"},
        "provenance": {"source": "synthetic",
                       "consent_or_permission_ref": "consent-ref-7",
                       "license_or_terms": "research-use-only"},
    }


def _contract_result(record, image_path=None):
    kwargs = {}
    if image_path is not None:
        kwargs["image_path"] = image_path
    return contract.validate_annotation(record, **kwargs)


def _passing_contract():
    return {"valid": True, "errors": []}


# ---------------------------------------------------------------- happy path

def test_clean_triple_is_usable_with_no_reasons():
    image = _clean_image()
    mask = _clean_mask()
    verdict = build_composite_qa(_passing_contract(), assess_image(image),
                                 validate_mask(mask, IMAGE_SHAPE))
    assert isinstance(verdict, QA_Verdict)
    assert verdict.status == "usable"
    assert verdict.reason is None
    assert verdict.reasons == ()
    assert verdict.scores["contract_valid"] is True
    assert verdict.scores["image_usable"] is True
    assert verdict.scores["mask_valid"] is True
    assert set(verdict.scores) >= {"contract_valid", "image_usable", "mask_valid",
                                   "mask_coverage_fraction", "mask_n_pixels",
                                   "mean_brightness", "image_width", "image_height"}
    assert all(comp["status"] == "pass" for comp in verdict.components.values())
    assert set(verdict.components) == {"contract", "image", "mask"}


# ---------------------------------------------------------------- single rejections

def test_image_below_min_dims_is_rejected():
    image = np.zeros((60, 80, 3), dtype=np.uint8)
    mask = np.zeros((60, 80), bool); mask[10:30, 10:40] = True
    verdict = build_composite_qa(_passing_contract(), assess_image(image),
                                 validate_mask(mask, image.shape))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_IMAGE_TOO_SMALL
    assert verdict.reasons == (ERR_IMAGE_TOO_SMALL,)


def test_non_finite_pixels_are_rejected():
    image = np.full(IMAGE_SHAPE, np.nan)
    verdict = build_composite_qa(_passing_contract(), assess_image(image),
                                 validate_mask(_clean_mask(), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_NON_FINITE_PIXELS
    assert verdict.reasons == (ERR_NON_FINITE_PIXELS,)


def test_low_illumination_is_rejected():
    image = np.full(IMAGE_SHAPE, 5, dtype=np.uint8)
    verdict = build_composite_qa(_passing_contract(), assess_image(image),
                                 validate_mask(_clean_mask(), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_LOW_ILLUMINATION
    assert ERR_LOW_ILLUMINATION in verdict.reasons


def test_grayscale_and_unreadable_images_are_rejected():
    gray = np.zeros(IMAGE_SHAPE[:2], dtype=np.uint8)
    verdict = build_composite_qa(_passing_contract(), assess_image(gray),
                                 validate_mask(_clean_mask(), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_EXPECTED_COLOR_IMAGE
    assert verdict.reasons == (ERR_EXPECTED_COLOR_IMAGE,)

    verdict = build_composite_qa(_passing_contract(), assess_image(None),
                                 validate_mask(_clean_mask(), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_IMAGE_UNREADABLE
    assert verdict.reasons == (ERR_IMAGE_UNREADABLE,)


def test_mask_shape_mismatch_is_rejected():
    verdict = build_composite_qa(_passing_contract(),
                                 assess_image(_clean_image()),
                                 validate_mask(np.zeros((100, 100), bool), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_MASK_SHAPE_MISMATCH
    assert verdict.reasons == (ERR_MASK_SHAPE_MISMATCH,)


def test_mask_too_small_is_rejected():
    verdict = build_composite_qa(_passing_contract(),
                                 assess_image(_clean_image()),
                                 validate_mask(np.zeros(IMAGE_SHAPE[:2], bool), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_MASK_TOO_SMALL
    assert verdict.reasons == (ERR_MASK_TOO_SMALL,)


def test_mask_covers_full_frame_is_rejected():
    verdict = build_composite_qa(_passing_contract(),
                                 assess_image(_clean_image()),
                                 validate_mask(np.ones(IMAGE_SHAPE[:2], bool), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_MASK_COVERS_FULL_FRAME
    assert verdict.reasons == (ERR_MASK_COVERS_FULL_FRAME,)


# ---------------------------------------------------------------- contract-level rejections

def test_image_hash_mismatch_is_rejected(tmp_path):
    # No image anchor: recorded image_sha256 does not match the file on disk.
    image_path = tmp_path / "img_hash.png"
    cv2.imwrite(str(image_path), _clean_image())
    record = _clean_record(image_id="img_hash", image_sha256="0" * 64)
    contract_result = _contract_result(record, image_path=image_path)
    assert ERR_IMAGE_HASH_MISMATCH in contract_result["errors"]

    verdict = build_composite_qa(contract_result,
                                 assess_image(_clean_image()),
                                 validate_mask(_clean_mask(), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_IMAGE_HASH_MISMATCH
    assert verdict.reasons == (ERR_IMAGE_HASH_MISMATCH,)


def test_annotation_not_researcher_reviewed_is_rejected(tmp_path):
    image_path = tmp_path / "img_review.png"
    cv2.imwrite(str(image_path), _clean_image())
    record = _clean_record(image_id="img_review", image_sha256=contract.sha256_file(image_path),
                           reviewed=False)
    contract_result = _contract_result(record, image_path=image_path)
    assert ERR_ANNOTATION_NOT_REVIEWED in contract_result["errors"]

    verdict = build_composite_qa(contract_result,
                                 assess_image(_clean_image()),
                                 validate_mask(_clean_mask(), IMAGE_SHAPE))
    assert verdict.status == "rejected"
    assert verdict.reason == ERR_ANNOTATION_NOT_REVIEWED
    assert verdict.reasons == (ERR_ANNOTATION_NOT_REVIEWED,)


# ---------------------------------------------------------------- aggregation

def test_multiple_simultaneous_failures_aggregate_all_reasons():
    image = np.zeros((60, 80, 3), dtype=np.uint8)
    record = _clean_record(image_id="img_multi", image_sha256="0" * 64, reviewed=False)
    contract_result = _contract_result(record, image_path=None)
    mask_result = validate_mask(np.zeros(IMAGE_SHAPE[:2], bool), IMAGE_SHAPE)

    verdict = build_composite_qa(contract_result, assess_image(image), mask_result)
    assert verdict.status == "rejected"
    expected = {ERR_IMAGE_TOO_SMALL, ERR_MASK_TOO_SMALL,
                ERR_ANNOTATION_NOT_REVIEWED}
    assert set(verdict.reasons) == expected
    assert len(verdict.reasons) == len(expected)  # no duplicates
    assert verdict.reason in expected  # first reason is one of the failures
