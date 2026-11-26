# Sprint 15 — ROI extraction, skin-sample recovery and mobile camera geometry

**Baseline:** `main` @ `40ee124` (PR #15 merged) ·
**Branch:** `arena/ae4b6f9b-rsbvp-vitals-and-anemia`

---

## 0. What evidence this report rests on

**The screenshot and the CSV segment summary were not present in the working
environment.** No image file, no export, and no CSV were available to inspect, so
this report does **not** reproduce the specific device session. The symptoms were
taken as given: forehead ROI too large, forehead valid skin samples 0 %, repeated
rejection under different lighting on multiple phones.

Following the instruction not to report an accuracy error from a segment with zero
live and zero reference samples: **no accuracy figure is computed, cited or implied
anywhere in this report or in any test.** A 17.96 s segment with no samples cannot
produce an error, only an availability statistic, and even that is not available to
me.

What I *could* do is measure the code's behaviour directly, which turned out to be
more informative than the screenshot would have been. Every number below is
reproducible from the repository.

---

## 1. Root causes, with measurements

### Cause 1 — the forehead polygon covered half the head

The region was `[10,338,297,332,284,251,389,356,9,127,162,21,54,103,67,109]`.
Measured against the MediaPipe canonical face model:

| Property | Measured |
|---|---|
| Horizontal span | **100.0 %** of the face bounding box |
| Vertical span | **33.4 %** of the face bounding box |
| Area | **0.2123** bbox units² |
| Vertices on or outside the face outline | **8 of 16** |
| Clearance from the face outline | **0.0 %** at 14 of 16 vertices |

Two of its vertices (127, 356) are the **widest points of the entire 468-vertex face
model**. It started at vertex 10 — the vertex of the *head*, i.e. the hairline — and
swept down to the brow ridge. That is exactly the oversized overlay observed on
device. It also means the patch sampled hairline, temple and (under rotation) frame
background, which is a plausible contributor to unusable pixel statistics.

### Cause 2 — the cheek polygons were self-intersecting

Both cheek outlines were 12-point rings that cross themselves. Verified
geometrically: `selfIntersect = true` for both. Under the even-odd fill rule a
self-crossing outline flips inside/outside repeatedly, so which pixels are sampled
depends on the crossing pattern rather than on anatomy. Area computation is also
meaningless for such a shape.

### Cause 3 — the pixel gate encoded one white-balance assumption

The old filter required **every** pixel to satisfy
`r ≥ 0.88·g`, `g ≥ 0.82·b`, `r − b ≥ 8`, plus luminance 35–245.

I tested this against 30 synthetic skin/illuminant combinations. It does **not**
reject skin universally — my first hypothesis was wrong, and the fixture suite
records that. It rejects *specifically*:

| Case | Rendered RGB | Old verdict |
|---|---|---|
| very light skin, deep blue shade | 190 / 187 / 186 | **FAIL** — `r − b = 4 < 8` |
| dark skin, deep blue shade | 60 / 52 / 53 | **FAIL** — `r − b = 7 < 8` |
| light skin, cool LED | 211 / 189 / 188 | pass |
| dark skin, neutral | 85 / 62 / 50 | pass |

So the gate was **skin-tone- and illuminant-dependent**: it failed wherever the
illuminant left little red-over-blue margin, which is cool and shaded light, and it
failed there for *every* pixel of the patch — producing exactly 0 % valid samples
with the face perfectly tracked. That is the reported symptom's mechanism, with the
reproduction committed.

### Cause 4 — overlay geometry was wrong on phone aspect ratios

The overlay drew with `x * videoWidth, y * videoHeight` into a canvas sized to the
element box, ignoring `object-fit: contain`:

* a 1280×720 stream in a 640×480 box is drawn 360 px tall with 60 px bars — the
  overlay placed every ROI **60 px too low**;
* a portrait 720×1280 stream is pillarboxed and the side bars were ignored;
* the overlay canvas had no `width`/`height` attributes, so its backing store was
  300×150 stretched by CSS;
* front-camera mirroring was ignored, placing a correct polygon on the wrong cheek.

This is why the overlay looked "excessively large": a stretched 300×150 backing
store draws thick, blurred outlines that do not sit on the face.

### Cause 5 — cheek estimates were attributed to non-existent regions

`BrowserPulse.tsx` parsed estimate keys with `key.split('_')[0]`:

```
"left_cheek_green"  ->  roi "left",       algorithm "cheek_green"
"right_cheek_chrom" ->  roi "right",      algorithm "cheek_chrom"
"forehead_green"    ->  roi "forehead",   algorithm "green"     (survived)
```

Every cheek reading was recorded against a region that does not exist and an
algorithm that does not exist. Those readings were then excluded from every
per-ROI diagnostic and mislabelled in the export. Because forehead keys happened to
parse correctly, the defect was invisible in the one region anyone was looking at.

---

## 2. What changed

| Area | Change |
|---|---|
| Forehead geometry | Two symmetric anchors (**108, 337**) extruded **65 %** of the measured anchor→glabella distance. Area 0.0132 vs 0.2123 — **16× smaller**; width 20.9 % vs 100 %; height 6.3 % vs 33.4 % |
| Cheek geometry | Verified quads `[117,118,205,147]` and its exact mirror `[346,347,425,376]`; both simple, convex, ≥ 7.5 % clear of the face outline, 0 % overlap with eye/mouth/nostril masks |
| Landmark contract | **59 entries**, each with its anatomical role and its canonical coordinate; asserted against the committed model projection by both suites |
| Pixel filter | Kept luminance 35–245 and a **chroma floor**; removed the three white-balance conditions; red must merely not fall below blue by > 6 |
| Safe margin | 1.2 % of face height, applied inward, with a test that it shrinks but does not consume the patch |
| Diagnostics | Per region: polygon area (px²), candidates, mask exclusions, rejections *per condition*, accepted, accepted %, mean RGB, median RGB, geometric validity, plus a human-readable summary |
| Overlay | `computeOverlayTransform` implements `object-fit: contain`, device-pixel backing store, mirroring about the video's centre from `facingMode` |
| Key parsing | `parseEstimateKey` anchors on known method suffixes and validates the region prefix; unknown keys are surfaced, not guessed |
| Secure context | Explicit distinction between insecure private-network origin, insecure other origin, missing `mediaDevices`, missing `getUserMedia` |
| Track geometry | Reports decoded size, orientation, aspect ratio, requested settings, facing mode, and whether the sampling canvas matches the frame |

### Pixel filter: what was deliberately kept

* **Luminance bounds stayed.** Removing them would admit shadows and background.
* **A chroma floor was added**, not a skin classifier. It is a *signal-capability*
  check: POS and CHROM project chrominance, so an achromatic patch cannot yield a
  pulse. It is satisfied across the full range of human skin tones and rejects a
  grey wall or a white shirt.
* **No per-person calibration, no Fitzpatrick assumption, no model of skin colour.**
* **The Python YCrCb mask was not adopted** by the browser path, and the browser
  filter was not imposed on Python.

---

## 3. Tests

| Suite | Result |
|---|---|
| `pytest -q` | **509 passed** |
| `npm test` | **15 files, 259 passed** |
| `npx tsc -b` | clean |
| `npm run build` | ok |
| `npm run lint` | 0 errors, 1 pre-existing warning |

New coverage (about 100 new cases):

| File | Cases | What it pins |
|---|---|---|
| `roiGeometry.test.ts` | 44 | Landmark contract vs canonical model; forehead compactness; patch between hairline and brow; scale invariance; convexity and simplicity; mask clearance; safe margin; degenerate/rejected input; pixel classification across illuminants; diagnostics conservation; `low_usable_coverage` vs `no_accepted_pixels`; portrait/landscape; **the 0 %-coverage regression** |
| `roiPixelFixtures.test.ts` | 10 | The real extractor against 33 synthetic frames (5 skin tones × 6 illuminants + failure cases); mean matches the rendered skin, not the background; per-pixel conservation on every fixture |
| `overlay.test.ts` | 24 | `object-fit: contain` mapping for 4:3/16:9/9:16 in portrait and landscape boxes; device pixel ratio; mirroring about the video centre; drawn points equal the sampled polygon; lost-face state |
| `estimateKeys.test.ts` | 9 | All nine ROI × method keys; the old truncated values as an explicit anti-regression; unknown-key rejection; label formatting |
| `cameraEnvironment.test.ts` | 16 | Secure vs insecure origins; private-network HTTP refusal with actionable text; track geometry; canvas/frame mismatch; constraints |
| `BrowserPulse.test.tsx` | +5 | Diagnostics surface in the UI; a failed region explains itself; the accounting table expands; **no bare "left"/"right" region label**; environment and frame geometry reported |
| `test_roi_geometry_contract.py` | 15 | Canonical fixture integrity; contract coordinates match the model; every used index documented; Python rectangles non-degenerate, non-overlapping, correctly banded, edge-safe; the documented browser/Python difference is real |
| `test_roi_pixel_fixtures.py` | 11 | Fixture determinism and coverage; **the old gate rejected plausible skin in shade**; the new rule accepts those and still rejects grey/dark; known limitation asserted |

**Every one of these is synthetic.** The pixel fixtures are rendered from recipes
(skin colour, illuminant gain, face box) — no camera, no real face, no personal
data, and the fixture file is 17 KiB of JSON with the data-URI check asserted.

---

## 4. What is still not known

1. **No physical-camera session was run.** Nothing here demonstrates behaviour on a
   real Android device, real skin, real auto-exposure or real motion. The reported
   device symptoms are addressed at the level of *mechanism and code*, not verified
   on the device that produced them.
2. **The screenshot and CSV were unavailable**, so the specific session could not be
   reproduced from its own data.
3. **One plausible case still fails, by design.** Very light skin under deep blue
   shade renders nearly achromatic (190/187/186) and is rejected with `low_chroma`.
   The test suite asserts that it fails rather than loosening the floor. Real
   behaviour under such light is unknown; a real operator seeing `low_chroma`
   everywhere should move to even light.
4. **Geometry correctness is not signal quality.** A correctly placed patch on a
   real forehead can still yield no pulse — poor perfusion, motion, compression,
   aggressive auto-exposure. The two failure classes are now reported separately
   precisely so this cannot be conflated.
5. **The chroma floor value (12) is a heuristic**, chosen to sit below any plausible
   skin rendering and above a neutral surface. It is not calibrated on real
   recordings.
6. **The Python pathway was not rewritten.** It still uses a Haar box with fixed
   rectangles and a YCrCb mask. The difference is documented and tested as a
   difference, not papered over.
7. **No accuracy claim** follows from any of this, and none is made.

---

## 5. Definition of done, assessed honestly

| Requirement | Status |
|---|---|
| Correctly bounded forehead ROI | **Done** — 16× smaller, 0 % brow overlap, 9.3 % face-outline clearance, verified against the model |
| Correctly bounded cheek ROIs | **Done** — simple, convex, mirrored, mask-clear |
| Meaningful accepted-pixel diagnostics | **Done** — per-condition accounting, conservation-tested, in the UI |
| Correct algorithm/ROI provenance | **Done** — explicit suffix parsing; anti-regression test for the exact old values |
| Correct portrait/landscape overlay alignment | **Done** — tested for four video/container combinations |
| Reproducible explanation for every rejected ROI | **Done** — seven named reasons with actionable text |
| Tests that catch the original failure | **Done** — the 0 %-coverage regression appears in three places |
| Clear distinction between fixtures and physical testing | **Done** — stated in every fixture header, in the docs, and here |

**Not merged.** This is for review.
