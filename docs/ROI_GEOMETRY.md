# ROI geometry and pixel extraction

This document records the face-region geometry used for camera-based pulse
estimation: which landmarks define each region, why those indices, how pixels are
accepted or rejected, and what the two capture pathways do differently.

It exists because the previous implementation had a forehead region that covered
100 % of the face width and 33 % of its height, and because the two pathways are
**not interchangeable**.

**Evidence status.** Everything here is verified against the MediaPipe canonical
face model and synthetic frames. **No physical-camera session was performed** for
this work (see §6), so every statement below is software- or synthetic-tested.

---

## 1. The two pathways are genuinely different

| | Browser (`roiGeometry.ts`) | Python (`rppg_core/pipeline.py`) |
|---|---|---|
| Face detector | MediaPipe Face Landmarker (478 landmarks) | OpenCV Haar cascade (a bounding box) |
| ROI shape | Polygon from verified landmark indices | Fixed rectangle as a fraction of the face box |
| Follows head rotation | Yes, because landmarks move with the face | No, a box-aligned rectangle cannot rotate |
| Adapts to face shape | Yes (depth derived from measured anchor-glabella distance) | No (fixed fractions of the box) |
| Pixel acceptance | Luminance floor/ceiling + chroma floor + channel-order sanity | YCrCb skin mask |
| Failure modes | Landmark jitter, occlusion of an anchor | Box drift, background inside the box |

**They cannot be identical, and they are not claimed to be.** A parity test
(`tests/test_roi_geometry_contract.py`) enforces only what must agree: the three
region *names*, non-degeneracy, frame containment, non-overlap between regions, and
the correct anatomical band for each. It also asserts that the documentation keeps
naming both detectors, so this difference cannot quietly disappear from the docs.

The Python rectangle path keeps its YCrCb mask deliberately: with a bounding box and
no landmarks, a colour mask is the only defence against sampling background. The
browser path does not adopt that mask, because with landmark polygons it already
knows where the face is, and a skin-colour classifier would reject legitimate faces
under coloured lighting.

---

## 2. Landmark contract

All indices are from the MediaPipe canonical face model
(`mediapipe/modules/face_geometry/data/canonical_face_model.obj`, 468 vertices).
A 2D projection of that model is committed as
`gui/frontend/src/rppg/fixtures/faceCanonical2d.json` — model geometry, not a
photograph — and every `canonicalX/canonicalY` in `LANDMARK_CONTRACT` is asserted
against it. Coordinates are normalised: `y = 0` is the vertex of the head
(landmark 10), `y = 1` is the chin (landmark 152).

`y` therefore grows **downward on the face**, exactly like an image.

### Regions

| Region | Landmarks | Rule |
|---|---|---|
| **forehead** | anchors `108`, `337`; depth reference `9` | Upper edge = the two symmetric forehead anchors. Lower edge = anchors extruded **65 %** of the way to the glabella (9). |
| **left cheek** | `117, 118, 205, 147` | Verified quad; exact mirror partners `346, 347, 425, 376` form the right cheek. |
| **right cheek** | `346, 347, 425, 376` | Mirror of the left, to 0.000 error in the canonical model. |

### Why the depth is a fraction rather than a fixed index

The anchors sit at `y = 0.094` and the glabella at `y = 0.233` — an `0.139` gap. At
65 % the lower edge lands at `y = 0.184`, which is **2.3 % of face height above the
innermost brow landmark (107)**. Expressing the depth as a fraction of the measured
anchor-to-glabella distance means the patch scales with face size instead of
assuming a fixed proportion of the bounding box: a small far face gets a
proportionally small patch rather than a patch that is 33 % of its height.

### Excluded features

| Mask | Landmarks | Applied to |
|---|---|---|
| left eye | `33, 160, 158, 133, 153, 144` | left cheek |
| right eye | `362, 385, 387, 263, 373, 380` | right cheek |
| mouth | `61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 308` | both cheeks |
| left brow | `70, 63, 105, 66, 107, 55, 65, 52, 53` | forehead |
| right brow | `300, 293, 334, 296, 336, 285, 295, 282, 283` | forehead |
| nostrils | `2, 97, 326, 327` | both cheeks |

A safe margin of `0.012` of face height is applied inward on every edge after the
polygon is built, so the sampled pixels never touch the hairline or the brow edge.

---

## 3. What was wrong before, with the measurements

| | Before | After |
|---|---|---|
| Forehead width | 100.0 % of face bbox | **20.9 %** |
| Forehead height | 33.4 % of face bbox | **6.3 %** |
| Forehead area | 0.2123 bbox units² | **0.0132** (16× smaller) |
| Forehead vertices on/outside the face outline | 8 of 16 | **0** |
| Forehead vs brow masks | overlapping | **0 % overlap** |
| Left cheek polygon | **self-intersecting** | simple, convex |
| Right cheek polygon | **self-intersecting** | simple, convex |
| Cheek clearance from face outline | 7.8 % min | **7.5 % min** (same, now verified) |

The old forehead polygon was
`[10,338,297,332,284,251,389,356,9,127,162,21,54,103,67,109]`. It started at vertex
10 (the hairline/vertex of the head) and swept down to the brow, and its side
vertices 127/356 are the widest points of the entire face model. That is the
oversized overlay that was observed on real phones.

The old cheek polygons were 12-point rings that cross themselves. Under the
even-odd fill rule a self-intersecting outline flips inside/outside more than once,
so which pixels get sampled depends on the crossing pattern rather than on anatomy.

---

## 4. Pixel acceptance

The previous filter required **every** pixel to satisfy
`r >= 0.88·g`, `g >= 0.82·b` and `r − b >= 8`, plus a luminance window. Those three
constants encode one specific white-balance assumption: "red a bit above green,
green slightly above blue". When a condition fails for every pixel, the region
returns no mean at all — a tracked face with 0 % valid samples.

The replacement keeps the physically justified parts and drops the assumption:

| Check | Kept? | Why |
|---|---|---|
| Luminance floor 35 | **kept** | An underexposed patch carries no usable modulation. |
| Luminance ceiling 245 | **kept** | Clipped highlights destroy the amplitude information. |
| Red ≥ green by 12 % | **removed** | A camera/illuminant property, not a skin property. |
| Green ≥ blue by 22 % | **removed** | Same. |
| Red − blue ≥ 8 | replaced | Red must merely not fall below blue by more than 6. |
| Chroma ≥ 12 (max−min) | **added** | POS and CHROM both project chrominance; a near-grey patch cannot yield a pulse. |

The chroma floor is a **signal-capability** check, not a skin-tone classifier: it is
satisfied across the full range of human skin tones and rejects a grey wall or a
white shirt. There is no per-person calibration, no Fitzpatrick assumption and no
model of "skin colour". A dark-skin sample such as `(60, 45, 38)` passes; a neutral
grey `(128, 128, 128)` and a blue background `(60, 100, 150)` do not.

Deliberately **not** done: removing the luminance checks (would admit shadows and
background), or making a colour classifier mandatory for all users.

---

## 5. Diagnostics

Every region reports, for the most recent frame: polygon area in pixels, candidate
pixel count, pixels removed by each feature mask, rejections **per condition**,
accepted count, accepted fraction, mean RGB, median RGB and geometric validity.
The counts add up exactly, and a composition test asserts it:

```
candidatePixels == acceptedPixels + excludedByMask + Σ(rejections)
```

Rejection reasons are human-readable rather than opaque codes:

| Reason | Message |
|---|---|
| `invalid_landmarks` | "Landmark N (name) is missing or non-finite…" |
| `polygon_too_small` | "The patch collapses after the 1.2 % safe margin…" |
| `polygon_outside_frame` | "The patch falls entirely outside the video frame" |
| `too_few_candidate_pixels` | "Only N candidate pixels… at least 40 are needed" |
| `no_accepted_pixels` | "All N candidate pixels were rejected (…, 240 near-grey pixel …)" |
| `low_usable_coverage` | "Only 4.1 % of candidate pixels were usable (…)" |
| `invalid_frame` | "Frame data (N bytes) does not match 640x480" |

These appear in the browser UI under *ROI extraction diagnostics* (one line per
region, with the full accounting behind a "Show full pixel accounting" toggle) and
travel with each trace sample for export. **No pixel data, and no frames, are ever
exported or logged** — only counts and means.

---

## 6. Overlay correctness

The overlay previously used `x * videoWidth`, `y * videoHeight` drawn into a canvas
sized to the element's box. That is wrong whenever the video is letterboxed:

* a 1280×720 stream in a 640×480 box is drawn 360 px tall with 60 px bars top and
  bottom, but the overlay assumed it filled 480 px — **every ROI was drawn 60 px
  too low**;
* a portrait 720×1280 stream is pillarboxed, and the overlay ignored the side bars;
* the overlay canvas had no `width`/`height` attributes, so its backing store was
  300×150 and then stretched by CSS, blurring the outlines;
* front cameras are mirrored, so a correct-in-image-space polygon landed on the
  wrong cheek.

`computeOverlayTransform` now derives the `object-fit: contain` mapping (uniform
scale plus centring letterbox), the backing store is sized in device pixels, and
mirroring is applied about the *video's* centre, not the element's. Mirroring is
decided from the track's `facingMode`, so a rear camera is not flipped. Tests cover
portrait and landscape video in portrait and landscape containers, and assert that
the drawn points are exactly the sampled polygon's points.

---

## 7. Secure-context requirements

`getUserMedia` is only exposed in a secure context. `http://localhost` counts;
**an arbitrary private-network address such as `http://192.168.1.7:5173` does not**,
even on the same LAN. In that case `navigator.mediaDevices` is simply `undefined`.

The UI now distinguishes and names the failure: insecure private-network origin,
insecure other origin, missing `mediaDevices`, missing `getUserMedia`, and ready. It
also reports the decoded frame size, orientation, aspect ratio, requested track
settings, facing mode, and whether the sampling canvas matches the decoded frame.

For Android testing, serve the build over HTTPS. Steps are in
`docs/MANUAL_CAMERA_TESTS.md`.

---

## 8. What is not claimed

* **No physical-camera session was run.** Device behaviour, real lighting, real
  skin tones under real illuminants, and real head motion are all unmeasured. The
  fixtures are synthetic pixels and model geometry.
* **Geometry correctness is not signal quality.** A perfectly placed patch on a
  real forehead can still yield no pulse: poor perfusion, motion, compression by a
  hand or a pillow, or an auto-exposure that strips the modulation. Geometry
  failures and signal failures are reported separately for exactly this reason.
* **The chroma floor can reject a real face** under extreme desaturation. This is
  not hypothetical: in the fixture matrix, `very_light__deep_blue_shade`
  (rgb 190/187/186) is rejected with `low_chroma`, and the test suite asserts that
  it *is* rejected rather than lowering the floor until everything passes. If a
  real operator in deep blue shade sees `low_chroma` on every region, this is the
  known cause: move to even light. It is a disclosed limitation, not a resolved one.
* **No physiological accuracy claim** follows from any of this.
