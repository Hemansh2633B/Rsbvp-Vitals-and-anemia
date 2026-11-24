# Anemia research model card — no model available

**Status:** No trained model and no inference claim. The repository contains no verified anemia dataset or permitted image records. No performance figures are available. Basic image quality/colour feature utilities, a standardized input-image contract and researcher-reviewed conjunctival-ROI annotation format (`docs/ANEMIA_IMAGE_CONTRACT.md`, validator in `research/anemia/contract.py`), a local metadata inventory script, grouped split helper and paired regression metric helper exist to support a future auditable workflow; these are not a complete training pipeline.

## What exists today (engineering infrastructure only)

- Image QA (`gui/anemia_core/image_features.py`): decode validity, minimum dimensions, expected colour image, non-finite rejection, mean-brightness illumination bounds, under/over-exposure fractions, clipped-channel fraction, Laplacian-variance sharpness, directional-blur anisotropy ratio with an explicit `possible_motion_blur` reason (documented heuristic, not a calibrated detector), aggregated `reasons` list and backwards-compatible `reason`.
- Mask validation (`validate_mask`): explicit 2-D shape/size/coverage checks (`mask_missing`, `mask_shape_mismatch`, `mask_too_small`, `mask_covers_full_frame`) with coverage reporting; `color_summary` rejects invalid masks and returns per-channel mean/std, 5/25/50/75/95 percentiles, 16-bin normalized histograms, ROI coverage and illumination indicators. No automatic localization exists; any future localization must be tested separately and labelled experimental.
- Input contract + annotation validator (`research/anemia/contract.py`): reproducible 8/16-bit decode with recorded SHA-256 and dimensions, explicit rejection codes, `rsbvp.conjunctival-roi.v1` polygon/mask annotation validation, mandatory researcher-review and provenance fields; rejects unreviewed or mismatched annotations instead of letting them through.
- Dataset audit (`research/anemia/audit_dataset.py`): file inventory, decode QA, SHA-256 hashes, exact- and near-hash (aHash, Hamming ≤ 5) duplicate grouping, label joins, patient grouping stats (`patients`, `patients_with_multiple_images`), QA-reject and missing-label summaries. Patient-level split integrity enforceable via `anemia_core.evaluation.assert_patient_disjoint`; `grouped_holdout` rejects missing identifiers.
- Nothing here predicts, estimates or suggests hemoglobin, iron deficiency, anemia, risk, diagnosis or treatment; nothing defines a screening threshold.

## Intended research use

Future investigation of association between standardized palpebral conjunctiva images and laboratory-measured hemoglobin, subject to dataset licensing, ethics/privacy conditions, suitable patient identifiers and prespecified evaluation.

## Data and methods

Dataset provenance, inclusion/exclusion criteria, demographic labels, patient grouping, image quality, preprocessing, features, model architecture, training and independent evaluation: **not established**. Do not infer anemia or iron deficiency from an image using this project.

## Limitations and prohibited use

No automatic conjunctiva/sclera localization is implemented; researcher-supplied masks are validated but their biological correctness is the researcher's responsibility. Colour values are not calibrated across cameras. Hb inference is prohibited everywhere in this project.

Not a diagnostic device, triage tool or substitute for laboratory Hb or qualified clinical assessment. Pallor is not specific to iron deficiency. Any future classification must use applicable population-specific clinical thresholds and patient-grouped splits where identifiers permit. Do not report train-set metrics as test performance. Acquisition conditions, camera ISP, illumination, skin phenotype, conjunctival visibility and selection bias may limit generalizability.

## Release gate

Complete provenance/license verification, privacy review, image and label audit, patient-level split, external or independent evaluation, calibration and subgroup analysis before publishing any model or performance claim.
