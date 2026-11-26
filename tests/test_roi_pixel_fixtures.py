"""Validation of the synthetic ROI pixel fixtures.

The fixtures are recipes (face box, skin colour, illuminant gain, hair band), not
stored images, so both the Python check below and the TypeScript suite render the
same deterministic frame from a 16 KiB JSON file.

These tests verify the *fixture set itself*: that it covers the intended range, is
stable, and that a naive pixel filter would have failed on it. They do not run the
TypeScript extractor; `gui/frontend/src/rppg/roiPixelFixtures.test.ts` does that
against the identical file.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "roi_pixel_fixtures.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def render(payload: dict, case: dict) -> np.ndarray:
    """Recreate the frame from the recipe - identical to the TypeScript renderer."""
    width, height = payload["width"], payload["height"]
    box = payload["faceBox"]
    hair = payload["hair"]
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = case["background"]
    x0 = int(box["x"] * width)
    x1 = int((box["x"] + box["w"]) * width)
    y0 = int(box["y"] * height)
    y1 = int((box["y"] + box["h"]) * height)
    skin = [int(max(0, min(255, round(c * g)))) for c, g in zip(case["base_rgb"], case["gain"])]
    frame[y0:y1, x0:x1] = skin
    frame[max(0, y0 - hair["pixelsAboveFace"]):y0, x0:x1] = hair["rgb"]
    return frame


def test_fixture_file_is_labelled_synthetic(payload):
    assert payload["schema"] == "rsbvp.roi-pixels.v1"
    assert "synthetic" in payload["note"].lower()
    assert "no camera" in payload["note"].lower()
    assert payload["generated_by"] == "tests/fixtures/generate_roi_pixel_fixtures.py"
    assert payload["width"] > 0 and payload["height"] > 0


def test_fixture_covers_five_skin_tones_and_five_illuminants(payload):
    cases = payload["cases"]
    skins = {c["skin"] for c in cases.values()}
    lights = {c["illuminant"] for c in cases.values()}
    assert {"very_light", "light", "olive", "brown", "dark"} <= skins
    assert {"neutral_d65", "warm_tungsten_2700k", "cool_led_6500k", "greenish_fluorescent", "mild_blue_shade"} <= lights
    # full cross product of skin tones x illuminants
    cross = [k for k, c in cases.items() if c["skin"] in {"very_light", "light", "olive", "brown", "dark"}]
    # 5 tones x 6 illuminants, plus grey-wall, background-only and the
    # grey-background-with-a-real-face case.
    assert len(cross) == 31, cross
    assert len(cases) == 33, sorted(cases)


def test_rendering_is_deterministic(payload):
    for name, case in payload["cases"].items():
        first = render(payload, case)
        second = render(payload, case)
        assert np.array_equal(first, second), name


def test_the_old_fixed_heuristic_rejected_plausible_skin(payload):
    """Evidence for why the old gate was the wrong tool, not merely strict.

    The old rule required `r >= 0.88g`, `g >= 0.82b` and `r - b >= 8` for *every*
    pixel. Applying it to the fixture skins shows it rejects plausible skin in
    cool/deep shade - asymmetrically across tones, because the margin it demands
    depends on how much red the illuminant leaves. This is the reproducible basis
    for removing those three conditions; it is not a claim that the replacement is
    correct on real faces.
    """
    failures = []
    for name, case in payload["cases"].items():
        if case["skin"] in {"grey_wall", "background_only"}:
            continue
        r, g, b = [int(max(0, min(255, round(c * k)))) for c, k in zip(case["base_rgb"], case["gain"])]
        luminance = (r + g + b) / 3
        old_ok = not (luminance < 35 or luminance > 245 or r < g * 0.88 or g < b * 0.82 or r - b < 8)
        if not old_ok:
            failures.append((name, (r, g, b)))
    assert failures, "expected the old heuristic to reject at least one plausible-skin fixture"
    # And the failures must be the shade cases, not arbitrary ones.
    assert all("shade" in name for name, _ in failures), failures


def test_the_new_rule_accepts_plausible_skin_that_the_old_rule_rejected(payload):
    """The replacement must fix the cases the old gate broke - without going limp.

    These are the same values the TypeScript `classifyPixel` evaluates: luminance
    window, a chroma floor and a loose red-not-below-blue check.

    One fixture is expected to remain rejected: very light skin under deep blue
    shade renders almost chromatically neutral, and POS/CHROM both need colour
    variation. That is a stated limitation (see docs/ROI_GEOMETRY.md §4), and it is
    better to keep it visible here than to lower the chroma floor until the suite
    is green.
    """
    KNOWN_LIMITATION = {"very_light__deep_blue_shade"}
    rejected = []
    for name, case in payload["cases"].items():
        if case["skin"] in {"grey_wall", "background_only"}:
            continue
        r, g, b = [int(max(0, min(255, round(c * k)))) for c, k in zip(case["base_rgb"], case["gain"])]
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        ok = 35 <= luminance <= 245 and (max(r, g, b) - min(r, g, b)) >= 12 and r >= b - 6
        if not ok:
            rejected.append((name, (r, g, b), luminance))
    assert {name for name, *_ in rejected} == KNOWN_LIMITATION, rejected


def test_the_new_rule_still_rejects_a_grey_wall_and_a_dark_background(payload):
    for name in ("grey_wall__neutral_d65", "background_only__neutral_d65"):
        case = payload["cases"][name]
        r, g, b = case["base_rgb"]
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        assert not (35 <= luminance <= 245 and (max(r, g, b) - min(r, g, b)) >= 12), name


def test_background_only_fixture_is_genuinely_uniform(payload):
    case = payload["cases"]["background_only__neutral_d65"]
    frame = render(payload, case)
    # Face and background are the same colour, so only the dark hair band differs;
    # the head area itself carries no colour variation at all.
    face_box = payload["faceBox"]
    x0 = int(face_box["x"] * payload["width"])
    x1 = int((face_box["x"] + face_box["w"]) * payload["width"])
    y0 = int(face_box["y"] * payload["height"])
    y1 = int((face_box["y"] + face_box["h"]) * payload["height"])
    head = frame[y0:y1, x0:x1]
    assert np.all(head == np.array(case["background"], dtype=np.uint8))


def test_grey_background_with_a_skinned_face_is_still_sampleable(payload):
    """A grey wall behind a real face must not prevent sampling the face."""
    case = payload["cases"]["grey_background_skinned_face__neutral_d65"]
    frame = render(payload, case)
    face_box = payload["faceBox"]
    x0 = int(face_box["x"] * payload["width"])
    y0 = int(face_box["y"] * payload["height"])
    centre = frame[y0 + 20, x0 + 20]
    assert tuple(int(v) for v in centre) == tuple(case["base_rgb"])


def test_hair_band_sits_above_the_face_not_inside_it(payload):
    """The hair band is the pixel-level guard against a patch that grows upward."""
    landmarks = payload["landmarks"]
    box = payload["faceBox"]
    forehead_top_y = min(landmarks[i]["y"] for i in (108, 337))
    hair_bottom = box["y"]
    assert forehead_top_y > hair_bottom, "the forehead patch must start below the hairline"
    gap_px = (forehead_top_y - hair_bottom) * payload["height"]
    assert gap_px > 1.0, f"only {gap_px:.1f}px between hair band and forehead patch"


def test_landmarks_are_mapped_into_the_face_box(payload):
    landmarks = payload["landmarks"]
    assert len(landmarks) == 468
    box = payload["faceBox"]
    for point in landmarks[:20]:
        assert box["x"] - 1e-6 <= point["x"] <= box["x"] + box["w"] + 1e-6
        assert box["y"] - 1e-6 <= point["y"] <= box["y"] + box["h"] + 1e-6


def test_no_image_or_participant_data_is_embedded(payload):
    text = FIXTURES.read_text(encoding="utf-8").lower()
    for forbidden in ("data:image", "base64", "participant_name", "face_image", ".jpg", ".png"):
        assert forbidden not in text, f"fixture must not embed {forbidden}"
