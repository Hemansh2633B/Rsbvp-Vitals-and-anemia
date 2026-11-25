"""Composite anemia-image QA aggregation layer (software QA only).

Aggregates the existing primitives -- ``anemia_core.image_features.assess_image``,
``anemia_core.image_features.validate_mask`` and
``research.anemia.contract.validate_annotation`` -- into a single explainable
verdict, modeled on ``gui/rppg_core/quality.py::assess_window``.

This module estimates nothing, diagnoses nothing and screens nothing. It
answers one question only: does an image/contract/mask triple pass the
documented software QA gates, and if not, why not (machine-readable reasons).

No hemoglobin estimation, no prediction, no diagnosis, no risk and no
screening anywhere here -- see docs/ANEMIA_MODEL_CARD.md and
docs/ANEMIA_READINESS.md. All thresholds live in the primitives; this layer
only aggregates their machine-readable outputs.
"""
from __future__ import annotations

from dataclasses import dataclass

# Machine-readable rejection codes (extend, never reuse, to keep logs stable).
ERR_IMAGE_HASH_MISMATCH = "image_hash_mismatch"
ERR_IMAGE_TOO_SMALL = "image_too_small"
ERR_NON_FINITE_PIXELS = "non_finite_pixels"
ERR_LOW_ILLUMINATION = "low_illumination"
ERR_EXPECTED_COLOR_IMAGE = "expected_color_image"
ERR_IMAGE_UNREADABLE = "image_unreadable"
ERR_MASK_SHAPE_MISMATCH = "mask_shape_mismatch"
ERR_MASK_TOO_SMALL = "mask_too_small"
ERR_MASK_COVERS_FULL_FRAME = "mask_covers_full_frame"
ERR_ANNOTATION_NOT_REVIEWED = "annotation_not_researcher_reviewed"

STATUS_USABLE = "usable"
STATUS_REJECTED = "rejected"
STATUS_NOT_EVALUATED = "not_evaluated"

# Codes the contract validator prefixes (e.g. "mask_invalid:mask_too_small").
_CONTRACT_PREFIXED = (ERR_MASK_SHAPE_MISMATCH, ERR_MASK_TOO_SMALL)


@dataclass(frozen=True)
class QA_Verdict:
    """Composite verdict for one conjunctival/ROI image triple.

    status: "usable" | "rejected" | "not_evaluated"
    reason: first machine-readable rejection code, or None when usable
    reasons: every machine-readable rejection code that fired (deduped)
    scores: honest numeric summaries; missing values are None, never zero
    components: per-component verdicts (contract, image, mask)
    """

    status: str
    reason: str | None
    reasons: tuple[str, ...]
    scores: dict
    components: dict


def _has_code(errors, code):
    """True if ``errors`` (contract error list) carries ``code``, plain or prefixed."""
    for err in errors or []:
        if err == code:
            return True
        tail = err.rsplit(":", 1)[-1] if ":" in err else err
        if tail == code:
            return True
    return False


def _get(result, key):
    if not isinstance(result, dict):
        return None
    value = result.get(key)
    return None if value is None else value


def _bool_flag(result, key):
    """Truth of a result key; None when absent (honesty: never invent)."""
    if not isinstance(result, dict):
        return None
    value = result.get(key)
    if value is None:
        return None
    return bool(value)


def _contract_component(contract_result):
    errors = contract_result.get("errors") if isinstance(contract_result, dict) else None
    reasons = []
    if contract_result is None:
        status = STATUS_NOT_EVALUATED
    elif _has_code(errors, ERR_IMAGE_HASH_MISMATCH):
        # No image anchor (recorded SHA-256 does not match the file on disk)
        # => reject, paralleling "no estimator anchor => reject candidate_bpm".
        reasons.append(ERR_IMAGE_HASH_MISMATCH)
    if _has_code(errors, ERR_ANNOTATION_NOT_REVIEWED):
        reasons.append(ERR_ANNOTATION_NOT_REVIEWED)
    if _has_code(errors, ERR_IMAGE_UNREADABLE):
        reasons.append(ERR_IMAGE_UNREADABLE)
    if _has_code(errors, ERR_EXPECTED_COLOR_IMAGE):
        reasons.append(ERR_EXPECTED_COLOR_IMAGE)
    if _has_code(errors, ERR_MASK_SHAPE_MISMATCH):
        reasons.append(ERR_MASK_SHAPE_MISMATCH)
    if _has_code(errors, ERR_MASK_TOO_SMALL):
        reasons.append(ERR_MASK_TOO_SMALL)
    status = STATUS_NOT_EVALUATED if contract_result is None else (
        STATUS_REJECTED if reasons else "pass")
    return {"status": status, "reason": reasons[0] if reasons else None,
            "reasons": tuple(reasons)}


def _image_component(image_qa_result):
    if image_qa_result is None:
        return {"status": STATUS_NOT_EVALUATED, "reason": None, "reasons": ()}
    reasons = [r for r in (image_qa_result.get("reasons") or []) if r]
    status = STATUS_REJECTED if reasons else "pass"
    return {"status": status, "reason": reasons[0] if reasons else None,
            "reasons": tuple(reasons)}


def _mask_component(mask_result):
    if mask_result is None:
        return {"status": STATUS_NOT_EVALUATED, "reason": None, "reasons": ()}
    reason = mask_result.get("reason")
    reasons = [reason] if reason else []
    status = STATUS_REJECTED if reasons else "pass"
    return {"status": status, "reason": reasons[0] if reasons else None,
            "reasons": tuple(reasons)}


def _honest_scores(contract_result, image_qa_result, mask_result):
    """Numeric summaries; missing values are None, never zero, never invented."""
    return {
        "contract_valid": _bool_flag(contract_result, "valid"),
        "image_usable": _bool_flag(image_qa_result, "usable"),
        "mask_valid": _bool_flag(mask_result, "valid"),
        "mask_coverage_fraction": _get(mask_result, "coverage_fraction"),
        "mask_n_pixels": _get(mask_result, "n_pixels"),
        "mean_brightness": _get(image_qa_result, "mean_brightness"),
        "image_width": _get(image_qa_result, "width"),
        "image_height": _get(image_qa_result, "height"),
    }


def build_composite_qa(contract_result, image_qa_result, mask_result):
    """Aggregate contract, image-QA and mask results into one QA_Verdict.

    Aggregation rules (parallel the candidate_bpm validation contract):
      * no image anchor (image_sha256 mismatch vs file on disk)
        => reject ``image_hash_mismatch``
      * image below minimum dimensions => reject ``image_too_small``
      * non-finite pixels => reject ``non_finite_pixels``
      * low illumination => reject ``low_illumination``
      * grayscale / unreadable => reject ``expected_color_image`` /
        ``image_unreadable``
      * mask shape mismatch vs image => reject ``mask_shape_mismatch``
      * mask too small (< 20 px) => reject ``mask_too_small``
      * mask covers the full frame => reject ``mask_covers_full_frame``
      * annotation not researcher-reviewed => reject
        ``annotation_not_researcher_reviewed``
      * clean image + passing contract + valid mask => "usable", no reasons
      * multiple simultaneous failures => aggregate ALL machine-readable
        reasons (no short-circuit, no single reason swallowing the rest)
    """
    contract_component = _contract_component(contract_result)
    image_component = _image_component(image_qa_result)
    mask_component = _mask_component(mask_result)
    components = {
        "contract": contract_component,
        "image": image_component,
        "mask": mask_component,
    }

    reasons = []
    for component in components.values():
        for code in component["reasons"]:
            if code not in reasons:
                reasons.append(code)

    all_missing = (contract_result is None and image_qa_result is None
                   and mask_result is None)
    if all_missing:
        status = STATUS_NOT_EVALUATED
    elif reasons:
        status = STATUS_REJECTED
    else:
        status = STATUS_USABLE

    return QA_Verdict(status=status,
                      reason=reasons[0] if reasons else None,
                      reasons=tuple(reasons),
                      scores=_honest_scores(contract_result, image_qa_result,
                                            mask_result),
                      components=components)
