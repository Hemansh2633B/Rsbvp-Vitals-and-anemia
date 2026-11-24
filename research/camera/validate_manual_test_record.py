#!/usr/bin/env python3
"""Validate a manual browser-camera test record (`rsbvp.camera-test-record.v1`).

This is *infrastructure* for future supervised physical-camera sessions. It
validates structure only — it cannot and does not attest that a test was
executed, by whom, or with what result. Records must never embed faces,
videos, images, or other human-participant data; direct identifiers beyond
the operator's initials are rejected.

Usage: python research/camera/validate_manual_test_record.py RECORD.json
Exits 0 on a structurally valid record, 1 otherwise. Never mutates the file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = "rsbvp.camera-test-record.v1"

# Keys that would mean a recording/image/participant payload leaked into the
# record are rejected outright rather than warned about.
FORBIDDEN_KEY_SUBSTRINGS = ("video_path", "image_path", "face_image", "frames_embedded",
                            "recording_file", "participant_name", "patient")
RESULT_ENUM = {"pass", "fail", "partial"}
LIGHTING_ENUM = {"indoor-bright", "indoor-normal", "indoor-low", "mixed", "outdoor"}
ROI_STATE_ENUM = {"full", "partial", "lost"}
REFERENCE_ENUM = {"none", "CMS50D", "CMS50E", "other"}


def _require(obj, path, problems):
    value = obj
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            problems.append(f"missing_field:{path}")
            return None
        value = value[part]
    if isinstance(value, str) and not value.strip():
        problems.append(f"missing_field:{path} (empty)")
        return None
    return value


def _scan_forbidden(obj, problems, prefix="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = str(key).lower()
            if any(bad in lowered for bad in FORBIDDEN_KEY_SUBSTRINGS):
                problems.append(f"forbidden_key:{prefix}.{key}")
            _scan_forbidden(value, problems, f"{prefix}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _scan_forbidden(value, problems, f"{prefix}[{i}]")


def validate_record(record) -> list[str]:
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["not_an_object"]
    if record.get("schema") != SCHEMA:
        problems.append(f"bad_schema:expected {SCHEMA}")

    _scan_forbidden(record, problems)

    initials = _require(record, "session.operator_initials", problems)
    if initials is not None and (not isinstance(initials, str) or len(initials.strip()) > 8):
        problems.append("bad_field:session.operator_initials (max 8 non-identifying initials)")
    consent = _require(record, "session.consent_confirmed", problems)
    if consent is not True:
        problems.append("missing_field:session.consent_confirmed must be true (self-test or overseen protocol)")
    _require(record, "session.date_utc", problems)

    for key in ("browser", "browser_version", "os", "camera_model", "camera_resolution", "lighting"):
        _require(record, f"environment.{key}", problems)
    fps = _require(record, "environment.approx_fps", problems)
    if fps is not None and not (isinstance(fps, (int, float)) and 1 <= fps <= 240):
        problems.append("bad_field:environment.approx_fps")
    lighting = record.get("environment", {}).get("lighting") if isinstance(record.get("environment"), dict) else None
    if lighting is not None and lighting not in LIGHTING_ENUM:
        problems.append(f"bad_field:environment.lighting (one of {sorted(LIGHTING_ENUM)})")

    duration = _require(record, "capture.duration_s", problems)
    if duration is not None and not (isinstance(duration, (int, float)) and duration > 0):
        problems.append("bad_field:capture.duration_s")
    drop = _require(record, "capture.dropped_interval_fraction", problems)
    if drop is not None and not (isinstance(drop, (int, float)) and 0.0 <= drop <= 1.0):
        problems.append("bad_field:capture.dropped_interval_fraction")
    for roi in ("forehead", "left_cheek", "right_cheek"):
        state = record.get("capture", {}).get("roi_availability", {}).get(roi) if isinstance(record.get("capture"), dict) else None
        if state not in ROI_STATE_ENUM:
            problems.append(f"bad_field:capture.roi_availability.{roi} (one of {sorted(ROI_STATE_ENUM)})")

    _require(record, "quality_gate.status", problems)
    rejection = record.get("quality_gate", {}).get("rejection_reasons", None) if isinstance(record.get("quality_gate"), dict) else None
    if rejection is not None and not isinstance(rejection, list):
        problems.append("bad_field:quality_gate.rejection_reasons (list of machine-readable tokens)")
    latency = record.get("quality_gate", {}).get("processing_latency_ms") if isinstance(record.get("quality_gate"), dict) else None
    if latency is not None and not (isinstance(latency, (int, float)) and latency >= 0):
        problems.append("bad_field:quality_gate.processing_latency_ms")

    ref = record.get("reference", {}).get("equipment") if isinstance(record.get("reference"), dict) else None
    if ref not in REFERENCE_ENUM:
        problems.append(f"bad_field:reference.equipment (one of {sorted(REFERENCE_ENUM)})")

    if record.get("result") not in RESULT_ENUM:
        problems.append(f"bad_field:result (one of {sorted(RESULT_ENUM)})")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    args = parser.parse_args(argv)
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: unreadable JSON: {exc}")
        return 1
    problems = validate_record(record)
    if problems:
        print("INVALID:")
        for problem in problems:
            print(f" - {problem}")
        return 1
    print("VALID: record is structurally sound (structure only; execution is not attested)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
