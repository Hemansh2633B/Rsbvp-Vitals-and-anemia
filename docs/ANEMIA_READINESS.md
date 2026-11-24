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
