# Anemia (Conjunctival ROI) Readiness — Status & Requirements

**No anemia prediction model exists in this repository, and none may be added
without a verified, lawfully obtained, labeled dataset and institutional oversight.**
This document states what *is* in place, what is explicitly absent, and what
would be required before any model work becomes permissible. It is a readiness
audit, not a capability.

## 1. What exists (software foundations only)

| Component | State |
|---|---|
| `docs/ANEMIA_IMAGE_CONTRACT.md` (`rsbvp.conjunctival-roi.v1`) | Contract for conjunctival/palpebral ROI image capture: provenance, QA gates, ROI annotation integrity requirements. |
| Frontend/GUI pipeline hooks | Face/ROI handling is researcher-facing plumbing; no hemoglobin regression, no classifier. |
| Image QA & annotation-integrity requirements | Documented (naming, QA checklist, ambiguity exclusion) but **no labeled images exist to validate them against**. |

## 2. What is explicitly absent

- No labeled conjunctival image dataset (hemoglobin-referenced) exists in this
  workspace, on this machine, or in Git history. `data/` contains a README and
  manifest templates only.
- No Hb estimation, anemia screening, or diagnostic capability of any kind.
- No validation of any correlation between conjunctival ROI colour and
  hemoglobin — the literature reports associations, but we have **no local
  evidence** and therefore make no such claim.
- No institutional ethics review or clinical protocol for anemia data collection.

## 3. Requirements before any model work could begin

1. **Lawful dataset**: de-identified images with verified hemoglobin reference
   (lab Hb, same-visit), explicit consent for research use, documented
   provenance, license permitting model development and publication.
2. **QA pipeline evidence**: ROI annotation inter-reader agreement report;
   rejection rules for unusable frames (blur, illumination mismatch,
   partial conjunctiva exposure); dedup by subject.
3. **Patient-level separation**: train/validation/test splits strictly by
   subject ID; zero leakage; manifest-level SHA-256 provenance; the manifest
   must be immutable once the split is frozen.
4. **Evaluation plan**: pre-registered metrics (MAE/RMSE for Hb regression;
   sensitivity/specificity at clinically meaningful thresholds) with
   confidence intervals; comparison to non-invasive baselines is optional but
   Hb must never be estimated clinically from this pipeline.
5. **Governance**: ethics approval or documented exemption; data-use agreement;
   no dataset committed to Git; no public release of identifiable images.

## 4. Current verdict

`NOT AVAILABLE — NO VERIFIED LABELED DATASET`. The anemia track is a contract
and a checklist. Any UI or API surface implying a hemoglobin reading, screening
result, or risk score would be a fabrication and is out of scope for every
phase of this project.

## Sprint 12 — dataset risk audit (software only)

`research/anemia/audit_dataset.py::audit_rows` now answers, from a local dataset
directory alone, whether a supervised run would even be legitimate. It reports
(counts, never repairs):

| Risk reported | Why it blocks a run |
|---|---|
| `hemoglobin_present / missing / invalid` | A subject without a usable Hb value cannot be labelled |
| `hemoglobin_not_available_for_every_image` | Partial labels silently turn into a biased subset |
| `patient_id_missing` | Without participant ids, any split leaks between train and test |
| `exact_duplicate_groups`, `near_duplicate_groups` | Augmented/duplicate images across a split inflate results |
| `participants_with_conflicting_hemoglobin` | Two different Hb values for one person means the label join is wrong |
| `unmatched_label_count` | Labels and images drifted apart |
| `supervised_training_ready` | The single boolean: **false** unless every blocker above is clear |

The Hb sanity window (1.0–25.0 g/dL) only catches impossible values such as a unit
mix-up or a sentinel like `-1`. It is **not** a diagnostic range and must not be
used to define anemia: any threshold depends on age, sex, pregnancy and altitude,
so a future implementation must take population-specific criteria as an explicit
input rather than a compiled-in 11 g/dL.

Covered by `tests/test_anemia_dataset_risks.py` (22 tests, synthetic metadata
only — no images, no identifiable data, no dataset in Git).

**No model, no training, no Hb output, no anemia probability exists, and this
audit does not change that.**
