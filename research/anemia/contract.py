#!/usr/bin/env python3
"""Standardized input-image contract and annotation validator (foundations).

This module exists so any future, consented anemia-image study starts from a
reproducible, documented decoding and annotation contract instead of ad-hoc
OpenCV calls. It contains NO model, NO hemoglobin regression and NO clinical
claim. Implementation status: foundational tooling only — no verified labeled
conjunctival dataset is present, and none may be assumed.

Documented contract: docs/ANEMIA_IMAGE_CONTRACT.md
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

SCHEMA_ANNOTATION = "rsbvp.conjunctival-roi.v1"

# Machine-readable rejection codes (extend, never reuse, to keep logs stable).
ERR_UNREADABLE = "image_unreadable"
ERR_EXPECTED_COLOR = "expected_color_image"
ERR_UNSUPPORTED_DEPTH = "unsupported_bit_depth"
ERR_HASH_MISMATCH = "image_hash_mismatch"
ERR_BAD_SHA256 = "bad_sha256_format"
ERR_MISSING_FIELD = "missing_field"
ERR_BAD_SCHEMA = "bad_schema"
ERR_BAD_POLYGON = "bad_polygon"
ERR_MASK_INVALID = "mask_invalid"
ERR_UNREVIEWED = "annotation_not_researcher_reviewed"
ERR_BAD_HEMOGLOBIN = "bad_hemoglobin_value"
ERR_MISSING_PATIENT = "missing_patient_id"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised with a machine-readable ``code``; never wraps raw OpenCV errors."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image_contract(path, *, record_hash: bool = True):
    """Decode per the documented contract. Returns ``(rgb_uint8, metadata)``.

    Policy (see docs/ANEMIA_IMAGE_CONTRACT.md):
      * OpenCV decodes; BGR(A) -> RGB(A); alpha is dropped with a note.
      * 8-bit passes through; 16-bit is rounded to 8-bit via value/257.
      * Grayscale and non-finite content are rejected with explicit codes.
      * No resizing, no colour adjustment, no auto-white-balance: the decoded
        pixels are the contract pixels.
    """
    path = Path(path)
    if not path.is_file():
        raise ContractError(ERR_UNREADABLE, f"no such file: {path}")
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ContractError(ERR_UNREADABLE, f"OpenCV could not decode {path.name}")
    metadata = {
        "path": str(path),
        "decoder": "opencv.imread(IMREAD_UNCHANGED)",
        "dtype_original": str(raw.dtype),
        "shape_original": list(raw.shape),
        "channels_original": int(raw.shape[2]) if raw.ndim == 3 else 1,
        "color_space_assumed": "sRGB (browser/OpenCV 8-bit convention); unverified per-file",
        "alpha_dropped": bool(raw.ndim == 3 and raw.shape[2] == 4),
        "bit_depth_converted": raw.dtype == np.uint16,
    }
    if record_hash:
        metadata["sha256"] = sha256_file(path)
    if raw.ndim == 2:
        raise ContractError(ERR_EXPECTED_COLOR, "grayscale image; conjunctival colour QA requires a colour image")
    if raw.ndim != 3 or raw.shape[2] not in (3, 4):
        raise ContractError(ERR_UNREADABLE, f"unsupported channel layout shape={raw.shape}")
    img = raw[:, :, :3]  # alpha intentionally dropped; recorded above
    if raw.dtype == np.uint16:
        img = np.rint(img.astype(np.float64) / 257.0).astype(np.uint8)  # 65535 -> 255
    elif raw.dtype != np.uint8:
        raise ContractError(ERR_UNSUPPORTED_DEPTH, f"dtype {raw.dtype} not in (uint8, uint16)")
    if not np.isfinite(img).all():  # defensive: uint arrays are always finite
        raise ContractError(ERR_UNREADABLE, "non-finite pixel values")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    metadata.update({"width": int(rgb.shape[1]), "height": int(rgb.shape[0]),
                     "channels": 3, "dtype": "uint8", "color_space": "RGB",
                     "converted": bool(metadata["alpha_dropped"] or metadata["bit_depth_converted"])})
    return rgb, metadata


def _require(record: dict, key: str, problems: list[str]):
    value = record.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        problems.append(f"{ERR_MISSING_FIELD}:{key}")
    return value


def validate_annotation(record, *, image_path=None, image_root=None):
    """Validate one ``rsbvp.conjunctival-roi.v1`` annotation.

    Returns ``{"valid": bool, "errors": [machine-readable codes]}``; never
    raises. If ``image_path`` (or ``image_root`` + ``record['image_id']``) is
    given, the recorded SHA-256 is checked against the file on disk.
    """
    problems: list[str] = []
    if not isinstance(record, dict):
        return {"valid": False, "errors": [f"{ERR_BAD_SCHEMA}: not an object"]}
    if record.get("schema") != SCHEMA_ANNOTATION:
        problems.append(f"{ERR_BAD_SCHEMA}:expected {SCHEMA_ANNOTATION}")
    image_id = _require(record, "image_id", problems)
    sha = _require(record, "image_sha256", problems)
    if isinstance(sha, str) and not _SHA256_RE.match(sha.strip().lower()):
        problems.append(ERR_BAD_SHA256)

    patient = record.get("patient_id")
    if patient is None or not str(patient).strip():
        problems.append(ERR_MISSING_PATIENT)

    roi = record.get("roi")
    if not isinstance(roi, dict):
        problems.append(f"{ERR_MISSING_FIELD}:roi")
    else:
        rtype = roi.get("type")
        if rtype == "polygon":
            pts = roi.get("points")
            w, h = roi.get("image_width"), roi.get("image_height")
            if not isinstance(pts, list) or len(pts) < 3:
                problems.append(ERR_BAD_POLYGON)
            elif not isinstance(w, (int, float)) or not isinstance(h, (int, float)) or w <= 0 or h <= 0:
                problems.append(f"{ERR_MISSING_FIELD}:roi.image_width/height")
            else:
                for p in pts:
                    if (not isinstance(p, (list, tuple)) or len(p) != 2
                            or not all(isinstance(v, (int, float)) and np.isfinite(v) for v in p)
                            or not (0 <= p[0] <= w) or not (0 <= p[1] <= h)):
                        problems.append(ERR_BAD_POLYGON)
                        break
        elif rtype == "mask_png":
            mask_rel = roi.get("path")
            w, h = roi.get("image_width"), roi.get("image_height")
            if not mask_rel or not isinstance(mask_rel, str):
                problems.append(f"{ERR_MISSING_FIELD}:roi.path")
            elif image_root is not None:
                mask_file = Path(image_root) / mask_rel
                mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
                if mask is None:
                    problems.append(ERR_MASK_INVALID)
                elif isinstance(w, (int, float)) and isinstance(h, (int, float)) and mask.shape != (int(h), int(w)):
                    problems.append(f"{ERR_MASK_INVALID}:mask_shape_mismatch")
                elif int(np.count_nonzero(mask)) < 20:
                    problems.append(f"{ERR_MASK_INVALID}:mask_too_small")
        else:
            problems.append(f"{ERR_BAD_SCHEMA}:roi.type must be polygon|mask_png")

    annotator = record.get("annotator")
    if not isinstance(annotator, dict):
        problems.append(f"{ERR_MISSING_FIELD}:annotator")
    else:
        _require(annotator, "annotator_id", problems)
        if annotator.get("reviewed") is not True:
            problems.append(ERR_UNREVIEWED)
        _require(annotator, "reviewed_by", problems)
        _require(annotator, "review_utc", problems)

    prov = record.get("provenance")
    if not isinstance(prov, dict):
        problems.append(f"{ERR_MISSING_FIELD}:provenance")
    else:
        _require(prov, "source", problems)
        _require(prov, "consent_or_permission_ref", problems)
        _require(prov, "license_or_terms", problems)

    labels = record.get("labels")
    if labels is not None:
        if not isinstance(labels, dict):
            problems.append(f"{ERR_BAD_SCHEMA}:labels must be an object")
        else:
            hb = labels.get("hemoglobin_g_dl")
            if hb is not None:
                try:
                    hb = float(hb)
                except (TypeError, ValueError):
                    problems.append(ERR_BAD_HEMOGLOBIN)
                else:
                    if not np.isfinite(hb) or hb <= 0 or hb > 30:  # sanity bound, NOT a clinical range
                        problems.append(ERR_BAD_HEMOGLOBIN)

    # Optional hash check against the actual file.
    candidate = None
    if image_path is not None:
        candidate = Path(image_path)
    elif image_root is not None and image_id:
        for ext in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"):
            probe = Path(image_root) / f"{image_id}{ext}"
            if probe.is_file():
                candidate = probe
                break
    if candidate is not None and isinstance(sha, str) and _SHA256_RE.match(sha.strip().lower()):
        if candidate.is_file() and sha256_file(candidate) != sha.strip().lower():
            problems.append(ERR_HASH_MISMATCH)

    return {"valid": not problems, "errors": problems}


def validate_annotation_file(annotations_jsonl, *, image_root=None):
    """Validate a JSON-Lines annotation file; returns per-record results."""
    results = []
    with Path(annotations_jsonl).open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                results.append({"line": lineno, "valid": False, "errors": [f"{ERR_BAD_SCHEMA}:json_{exc.msg}"]})
                continue
            outcome = validate_annotation(record, image_root=image_root)
            outcome["line"] = lineno
            outcome["image_id"] = record.get("image_id") if isinstance(record, dict) else None
            results.append(outcome)
    return results
