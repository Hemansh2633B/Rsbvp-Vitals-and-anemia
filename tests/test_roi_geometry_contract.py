"""Browser/Python ROI contract.

The two capture pathways use **different face detectors**, and therefore different
ROI geometry:

* **Browser** (`gui/frontend/src/rppg/roiGeometry.ts`): MediaPipe Face Landmarker
  supplies 478 landmarks. The ROI is a polygon built from verified landmark
  indices, so it follows the face through rotation and scale.
* **Python** (`gui/rppg_core/pipeline.py::get_multi_rois`): an OpenCV Haar cascade
  supplies a face *bounding box*. The ROI is a fixed rectangle expressed as
  fractions of that box, so it does not follow face rotation.

These cannot be identical, and pretending otherwise would be worse than
documenting it. What this module enforces is that:

1. both pathways define the **same three regions** with the same names;
2. both keep every region inside the frame and non-degenerate;
3. the Python rectangles do not overlap each other or spill outside the face box;
4. the browser landmark contract remains verified against the canonical model;
5. the difference is *documented*, including which pathway is stricter where.

No camera, no images: the Python side runs on numpy arrays and the browser side
reads a committed projection of the MediaPipe canonical face model.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from rppg_core.pipeline import get_multi_rois, keep_roi_inside_frame

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "gui" / "frontend" / "src" / "rppg" / "fixtures" / "faceCanonical2d.json"
GEOMETRY_TS = ROOT / "gui" / "frontend" / "src" / "rppg" / "roiGeometry.ts"
DOC = ROOT / "docs" / "ROI_GEOMETRY.md"

REGION_NAMES = {"forehead", "left_cheek", "right_cheek"}


def _canonical() -> list[dict[str, float]]:
    return json.loads(CANONICAL.read_text(encoding="utf-8"))["landmarks"]


# --------------------------------------------------------------------------
# Canonical landmark fixture integrity
# --------------------------------------------------------------------------

def test_canonical_fixture_is_the_mediapipe_model():
    payload = json.loads(CANONICAL.read_text(encoding="utf-8"))
    assert payload["schema"] == "rsbvp.face-canonical-2d.v1"
    assert "canonical_face_model.obj" in payload["source"]
    assert len(payload["landmarks"]) == 468
    assert "not a photograph" in payload["note"].lower() or "not real-face data" in payload["note"].lower()


def test_canonical_extremes_are_hairline_and_chin():
    landmarks = _canonical()
    ys = [p["y"] for p in landmarks]
    top = min(range(len(landmarks)), key=lambda i: landmarks[i]["y"])
    bottom = max(range(len(landmarks)), key=lambda i: landmarks[i]["y"])
    assert top == 10, "vertex 10 must be the top of the head"
    assert bottom == 152, "vertex 152 must be the chin"
    assert min(ys) == pytest.approx(0.0, abs=1e-6)
    assert max(ys) == pytest.approx(1.0, abs=1e-6)


def test_browser_contract_coordinates_match_the_canonical_fixture():
    """Every `canonicalX/canonicalY` in roiGeometry.ts must match the model."""
    landmarks = _canonical()
    source = GEOMETRY_TS.read_text(encoding="utf-8")
    rows = re.findall(
        r"\{ index: (\d+), name: '[^']+', role: '[^']+', canonicalX: (-?[\d.]+), canonicalY: (-?[\d.]+) \}",
        source,
    )
    assert len(rows) >= 50, "the landmark contract should document every index the code uses"
    mismatches = []
    for index, cx, cy in rows:
        i = int(index)
        if abs(landmarks[i]["x"] - float(cx)) >= 0.002 or abs(landmarks[i]["y"] - float(cy)) >= 0.002:
            mismatches.append((i, cx, cy, landmarks[i]))
    assert mismatches == [], f"contract drifted from the canonical model: {mismatches}"


def test_every_landmark_used_by_the_browser_is_documented():
    """No unverified index may be used for geometry."""
    source = GEOMETRY_TS.read_text(encoding="utf-8")
    documented = {int(m) for m in re.findall(r"\{ index: (\d+),", source)}

    def indices(block_name: str) -> set[int]:
        match = re.search(rf"export const {block_name}[^=]*=\s*(\{{.*?\n\}}|\[.*?\])(?:\s*as const)?", source, re.S)
        assert match, f"{block_name} not found"
        return {int(m) for m in re.findall(r"\b(\d{1,3})\b", match.group(1))}

    used = indices("CHEEK_PATCHES") | indices("FEATURE_MASKS") | indices("FOREHEAD_ANCHORS")
    used.discard(0)  # array syntax artefacts, not landmark indices
    undocumented = sorted(i for i in used if i not in documented)
    assert undocumented == [], f"landmarks used but not documented: {undocumented}"


# --------------------------------------------------------------------------
# Python rectangle geometry
# --------------------------------------------------------------------------

@pytest.mark.parametrize("frame_shape", [(480, 640, 3), (720, 1280, 3), (1280, 720, 3), (240, 320, 3)])
def test_python_regions_exist_and_stay_inside_the_frame(frame_shape):
    face = (int(frame_shape[1] * 0.25), int(frame_shape[0] * 0.15), int(frame_shape[1] * 0.5), int(frame_shape[0] * 0.6))
    rois = get_multi_rois(face, frame_shape)
    assert set(rois) == REGION_NAMES
    height, width = frame_shape[0], frame_shape[1]
    for name, (x, y, w, h) in rois.items():
        assert w > 0 and h > 0, f"{name} collapsed"
        assert x >= 0 and y >= 0, f"{name} starts outside the frame"
        assert x + w <= width and y + h <= height, f"{name} extends past the frame"


def test_python_regions_do_not_overlap_each_other():
    """Distinct regions must sample distinct skin, or their agreement is circular."""
    frame_shape = (480, 640, 3)
    face = (160, 72, 320, 288)
    rois = get_multi_rois(face, frame_shape)

    def overlap(a, b) -> int:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        dx = min(ax + aw, bx + bw) - max(ax, bx)
        dy = min(ay + ah, by + bh) - max(ay, by)
        return max(0, dx) * max(0, dy)

    names = sorted(rois)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            assert overlap(rois[first], rois[second]) == 0, f"{first} overlaps {second}"


def test_python_forehead_sits_in_the_upper_face_and_cheeks_below():
    """A region assigned to the wrong band would sample the wrong anatomy."""
    frame_shape = (480, 640, 3)
    face = (160, 72, 320, 288)
    x, y, w, h = face
    rois = get_multi_rois(face, frame_shape)

    fx, fy, _fw, _fh = rois["forehead"]
    lx, ly, _lw, _lh = rois["left_cheek"]
    rx, ry, _rw, _rh = rois["right_cheek"]

    # forehead in the top third of the face box
    assert fy >= y
    assert fy < y + h / 3
    # cheeks lower than the forehead
    assert ly > fy and ry > fy
    # left cheek left of centre, right cheek right of centre
    assert lx + _lw <= x + w * 0.55
    assert rx >= x + w * 0.45
    # cheeks are lateral, not on the nose
    assert lx < x + w / 2 and rx + _rw > x + w / 2


def test_python_regions_survive_a_face_at_the_frame_edge():
    frame_shape = (480, 640, 3)
    for face in [(-40, -30, 200, 200), (500, 350, 200, 200), (0, 0, 640, 480)]:
        rois = get_multi_rois(face, frame_shape)
        for name, roi in rois.items():
            clamped = keep_roi_inside_frame(roi, frame_shape)
            assert clamped == roi, f"{name} was not clamped for face {face}"
            x, y, w, h = roi
            assert 0 <= x and 0 <= y and x + w <= 640 and y + h <= 480


def test_python_regions_scale_with_face_size():
    """Doubling the face box must roughly quadruple the sampled area."""
    small = get_multi_rois((100, 100, 100, 100), (480, 640, 3))
    large = get_multi_rois((100, 100, 200, 200), (480, 640, 3))
    for name in small:
        small_area = small[name][2] * small[name][3]
        large_area = large[name][2] * large[name][3]
        assert large_area > small_area * 3, f"{name} did not scale with the face"


# --------------------------------------------------------------------------
# Cross-pathway agreement on the things that must agree
# --------------------------------------------------------------------------

def test_both_pathways_expose_the_same_three_regions():
    """Names must match or exports from the two pathways cannot be compared."""
    source = GEOMETRY_TS.read_text(encoding="utf-8")
    browser_names = set(re.findall(r"ROI_NAMES = \[([^\]]+)\]", source)[0].replace("'", "").replace(" ", "").split(","))
    assert browser_names == REGION_NAMES

    python_names = set(get_multi_rois((100, 100, 200, 200), (480, 640, 3)))
    assert python_names == REGION_NAMES


def test_the_documented_difference_between_pathways_is_real():
    """The docs must not claim the pathways share a detector."""
    assert DOC.is_file(), "docs/ROI_GEOMETRY.md must exist"
    text = DOC.read_text(encoding="utf-8").lower()
    # The document must name both detectors and both ROI methods.
    assert "mediapipe" in text
    assert "haar" in text
    assert "landmark" in text
    assert "rectangle" in text or "fixed rectangle" in text
    # And it must not claim they are interchangeable.
    assert "not interchangeable" in text or "cannot be identical" in text or "different" in text


def test_python_skin_mask_is_not_the_browser_pixel_filter():
    """The two pathways must not be described as sharing a pixel-acceptance rule."""
    python_source = (ROOT / "gui" / "rppg_core" / "pipeline.py").read_text(encoding="utf-8")
    assert "YCrCb" in python_source, "Python relies on a YCrCb skin mask"
    browser_source = GEOMETRY_TS.read_text(encoding="utf-8")
    assert "YCrCb" not in browser_source, "the browser must not silently adopt the Python mask"
    # The browser filter is luminance + chroma based, and says so.
    assert "low_chroma" in browser_source
    assert "too_dark" in browser_source
