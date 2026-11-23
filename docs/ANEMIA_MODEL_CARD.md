# Anemia research model card — no model available

**Status:** No trained model and no inference claim. The repository contains no verified anemia dataset or permitted image records. No performance figures are available. Basic image quality/colour feature utilities, a local metadata inventory script, grouped split helper and paired regression metric helper exist to support a future auditable workflow; these are not a complete training pipeline.

## Intended research use

Future investigation of association between standardized palpebral conjunctiva images and laboratory-measured hemoglobin, subject to dataset licensing, ethics/privacy conditions, suitable patient identifiers and prespecified evaluation.

## Data and methods

Dataset provenance, inclusion/exclusion criteria, demographic labels, patient grouping, image quality, preprocessing, features, model architecture, training and independent evaluation: **not established**. Do not infer anemia or iron deficiency from an image using this project.

## Limitations and prohibited use

Not a diagnostic device, triage tool or substitute for laboratory Hb or qualified clinical assessment. Pallor is not specific to iron deficiency. Any future classification must use applicable population-specific clinical thresholds and patient-grouped splits where identifiers permit. Do not report train-set metrics as test performance. Acquisition conditions, camera ISP, illumination, skin phenotype, conjunctival visibility and selection bias may limit generalizability.

## Release gate

Complete provenance/license verification, privacy review, image and label audit, patient-level split, external or independent evaluation, calibration and subgroup analysis before publishing any model or performance claim.
