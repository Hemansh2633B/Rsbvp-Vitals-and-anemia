#!/usr/bin/env python3
"""Generate deterministic pixel-level ROI fixtures.

Each fixture is a small synthetic image plus the canonical face landmarks mapped
into it, so the browser ROI extractor can be exercised on a controlled input
without a camera and without any real face.

These are **software fixtures**: they prove the extractor's arithmetic and its
rejection accounting. They say nothing about real skin, real illuminants or real
cameras.

Run only when the fixture set changes intentionally:
    python tests/fixtures/generate_roi_pixel_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "roi_pixel_fixtures.json"
CANONICAL = ROOT / "gui" / "frontend" / "src" / "rppg" / "fixtures" / "faceCanonical2d.json"

WIDTH, HEIGHT = 160, 120
FACE_BOX = {"x": 0.28, "y": 0.15, "w": 0.44, "h": 0.68}
BACKGROUND = (30, 34, 44)
HAIR = (38, 30, 28)
HAIR_PX = 8

# Illuminant gain applied per channel, (r, g, b). Chosen to bracket plausible
# white-balance behaviour, not to represent a calibrated colour pipeline.
ILLUMINANTS = {
    "neutral_d65": (1.00, 1.00, 1.00),
    "warm_tungsten_2700k": (1.12, 1.00, 0.76),
    "cool_led_6500k": (0.94, 1.00, 1.10),
    "greenish_fluorescent": (0.97, 1.04, 0.94),
    "mild_blue_shade": (0.92, 0.99, 1.05),
    # Deep shade under a blue sky is the condition that broke the old fixed gate:
    # more blue, less red, and (with a real sensor's black level) a small red-blue
    # difference. Real capture, not a hypothetical.
    "deep_blue_shade": (0.85, 0.99, 1.09),
}
# sRGB skin approximations across Fitzpatrick II..VI. These are plausible
# renderings for exercising arithmetic, NOT measured values.
# Skin reflectance, sRGB approximations spanning Fitzpatrick II..VI.
SKINS = {
    "very_light": (224, 189, 171),
    "light": (198, 160, 138),
    "olive": (168, 130, 108),
    "brown": (128, 95, 76),
    "dark": (85, 62, 50),
}


def clamp(value: float) -> int:
    return int(max(0, min(255, round(value))))


def render(base: tuple[int, int, int], gain: tuple[float, float, float], background: tuple[int, int, int] | None = None) -> list[int]:
    """A frame: background everywhere, skin inside the face box, hair above it.

    The hair band matters: it sits immediately above the forehead patch, so if the
    patch ever grows to include the hairline the extracted mean shifts measurably
    and the test fails. That is the geometric guard, expressed in pixels.
    """
    background = BACKGROUND if background is None else background
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:, :] = background
    x0 = int(FACE_BOX["x"] * WIDTH)
    x1 = int((FACE_BOX["x"] + FACE_BOX["w"]) * WIDTH)
    y0 = int(FACE_BOX["y"] * HEIGHT)
    y1 = int((FACE_BOX["y"] + FACE_BOX["h"]) * HEIGHT)
    skin = [clamp(c * g) for c, g in zip(base, gain)]
    frame[y0:y1, x0:x1] = skin
    # Hair: dark, above the forehead.
    frame[max(0, y0 - HAIR_PX):y0, x0:x1] = HAIR
    return frame.ravel().tolist()


def main() -> None:
    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))["landmarks"]
    landmarks = [
        {"x": round(FACE_BOX["x"] + p["x"] * FACE_BOX["w"], 5),
         "y": round(FACE_BOX["y"] + p["y"] * FACE_BOX["h"], 5)}
        for p in canonical
    ]
    cases = {}
    for skin_name, base in SKINS.items():
        for light_name, gain in ILLUMINANTS.items():
            key = f"{skin_name}__{light_name}"
            cases[key] = {
                "skin": skin_name,
                "illuminant": light_name,
                "base_rgb": list(base),
                "gain": list(gain),
                # Neutral background: this is a *face* fixture, so the background
                # must not be the thing that makes a region fail.
                "background": list(BACKGROUND),
            }
    # Two deliberate failures, so the fixtures also cover rejection paths.
    cases["grey_wall__neutral_d65"] = {
        "skin": "grey_wall", "illuminant": "neutral_d65", "base_rgb": [128, 128, 128],
        "gain": [1, 1, 1], "background": list(BACKGROUND),
    }
    cases["background_only__neutral_d65"] = {
        "skin": "background_only", "illuminant": "neutral_d65", "base_rgb": list(BACKGROUND),
        "gain": [1, 1, 1], "background": list(BACKGROUND),
    }
    # A fixture whose *background* is grey but whose face is skin: the case that
    # must still pass, proving the extractor samples the face and not the wall.
    cases["grey_background_skinned_face__neutral_d65"] = {
        "skin": "light", "illuminant": "neutral_d65", "base_rgb": list(SKINS["light"]),
        "gain": [1, 1, 1], "background": [128, 128, 128],
    }

    payload = {
        "schema": "rsbvp.roi-pixels.v1",
        "note": (
            "Synthetic frames for the browser ROI extractor. Generated, not captured: no camera, "
            "no real face, no personal data. They verify arithmetic and rejection accounting only."
        ),
        "generated_by": "tests/fixtures/generate_roi_pixel_fixtures.py",
        "width": WIDTH,
        "height": HEIGHT,
        # The face box and hair band are part of the recipe: both suites render
        # the frame from these values, so the fixture stays a few KiB instead of
        # embedding megabytes of pixels.
        "faceBox": FACE_BOX,
        "hair": {"rgb": list(HAIR), "pixelsAboveFace": HAIR_PX},
        "landmarks": landmarks,
        "cases": cases,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({len(cases)} cases, {OUT.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
