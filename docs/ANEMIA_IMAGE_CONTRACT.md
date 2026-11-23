# Anemia image contract and annotation format (foundations)

**Status: NOT AVAILABLE — NO VERIFIED LABELED DATASET.** This document defines
the input contract and annotation format any future, consented conjunctival
image study would use. It is not, and does not contain, a model, a predictor,
or a screening pathway. No specimen in this repository is claimed to be
lawfully usable, and none is present.

Code: `research/anemia/contract.py` (decoding + validation),
`gui/anemia_core/image_features.py` (QA + colour summaries),
`research/anemia/audit_dataset.py` (inventory/dedup/provenance hashing).
Tests: `tests/test_anemia_contract.py`, `tests/test_anemia_audit.py`,
`tests/test_anemia_features.py`.

## 1. Standardized input image contract

Decoding (`load_image_contract`) is deliberately boring and reproducible:

1. Files are decoded with OpenCV `IMREAD_UNCHANGED` — no resizing, no colour
   adjustment, no auto-white-balance, no crop. The decoded pixels *are* the
   contract pixels.
2. 8-bit images pass through. 16-bit integer images are converted by
   rounding `value / 257` (65535 → 255). Anything else is rejected with
   `unsupported_bit_depth`.
3. Alpha channels are dropped with the drop recorded in metadata; grayscale
   is rejected (`expected_color_image`) because colour QA is meaningless on
   grayscale. Undecodable files are `image_unreadable`.
4. Metadata recorded per image: `width`, `height`, `channels`, `dtype`,
   `dtype_original`, `shape_original`, `channels_original`,
   `color_space_assumed` (sRGB/OpenCV convention — **unverified per file**),
   `alpha_dropped`, `bit_depth_converted`, decoder name, and the file's
   SHA-256.
5. QA gates (`image_features.assess_image`): minimum dimensions, illumination
   bounds, under/over-exposure fractions, clipped-channel fraction, Laplacian
   sharpness, directional-blur anisotropy heuristic. Every rejection carries
   machine-readable reasons; nothing is silently dropped.
6. Pixel colour spaces are summarized in RGB/HSV/CIELAB with percentiles and
   histograms (`color_summary`) for curation only. **Colour features are not
   hemoglobin measurements and are never used to estimate one here.**

## 2. Explicit conjunctival ROI annotation format (`rsbvp.conjunctival-roi.v1`)

Annotations are JSON Lines, one object per image:

```json
{
  "schema": "rsbvp.conjunctival-roi.v1",
  "image_id": "subject_0001_left_001",
  "image_sha256": "<64 lower-case hex, sha256 of the exact file bytes>",
  "patient_id": "<pseudonymous patient grouping key>",
  "roi": {"type": "polygon",
          "points": [[x0, y0], [x1, y1], [x2, y2]],
          "image_width": 1280, "image_height": 960},
  "annotator": {"annotator_id": "researcher-a", "reviewed": true,
                "reviewed_by": "researcher-b",
                "review_utc": "2026-11-21T09:30:00Z"},
  "provenance": {"source": "<dataset or capture protocol id>",
                 "consent_or_permission_ref": "<ethics/data-use reference>",
                 "license_or_terms": "<license id or DUA reference>"},
  "labels": {"hemoglobin_g_dl": 11.2,
             "hemoglobin_method": "lab_analyzer",
             "measured_utc": "2026-11-18T08:00:00Z"}
}
```

- `roi.type` is `polygon` (≥ 3 in-bounds points against the recorded image
  dimensions) or `mask_png` (relative path to a binary mask of the recorded
  dimensions, ≥ 20 non-zero pixels).
- `labels` is optional. If `hemoglobin_g_dl` is present it must be finite and
  within the sanity bound (0, 30] g/dL. That bound is a data-entry guard,
  **not** a clinical reference range.
- Every annotation must be **researcher-reviewed** (`annotator.reviewed` is
  `true` and `reviewed_by` is a different, named reviewer). Auto-generated
  segmentations are not acceptable inputs for any future study without review.

Validate a file with the library (it never raises; it reports):

```python
from research.anemia.contract import validate_annotation_file
results = validate_annotation_file("annotations.jsonl", image_root="/path/to/images")
```

Rejection codes (stable, machine-readable): `bad_schema`, `missing_field:<name>`,
`bad_sha256_format`, `image_hash_mismatch`, `missing_patient_id`,
`bad_polygon`, `mask_invalid[:reason]`, `annotation_not_researcher_reviewed`,
`bad_hemoglobin_value`.

## 3. Provenance, hashing, patient grouping

- `audit_dataset.py` computes SHA-256 per file (exact duplicates), an 8×8
  average hash with Hamming ≤ 5 near-duplicate union-find groups, label joins
  and patient-level counts. Outputs are research metadata — restrict access.
- All records for one patient stay in one split (`anemia_core.evaluation.
  grouped_holdout` refuses missing identifiers; `assert_patient_disjoint`
  fails loudly on leakage). Image-level splitting is not acceptable.
- Original and any augmented variants must stay together in splitting.
- Nothing here weakens the rule that dataset-level claims require the dataset.

## 4. Explicit exclusions

- No hemoglobin estimation, risk score, triage label, treatment statement, or
  screening threshold is defined here or anywhere in this repository.
- No synthetic conjunctiva/face is used or may be used to claim performance.
- Colour features are not Hb. Camera ISP and illumination dominate them.
- Any future model requires: verified provenance and permission,
  lab-measured Hb labels, privacy review and oversight, patient-independent
  splits, and independent evaluation — before any external release, clinical
  claim or deployment. Status until then: **NOT AVAILABLE — NO VERIFIED
  LABELED DATASET**.
