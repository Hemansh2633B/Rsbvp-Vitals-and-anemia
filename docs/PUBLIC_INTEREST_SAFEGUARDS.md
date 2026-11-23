# Public-interest safeguards and limits — the RSBVP contract with its users

RSBVP is a **public-interest research initiative** investigating privacy-preserving camera-based physiological signal research. It is not a commercial product, not a screening program and not a medical device. These safeguards bind every release, every demo and every report. If a future change conflicts with this document, the change is wrong — open an issue instead.

## 1. What rPPG actually estimates

Remote photoplethysmography infers **pulse-induced color modulation in skin** from video frames, and reports a **pulse-rate estimate (BPM)** and an experimental waveform per window. In this project that is all it is claimed to be:

- An estimated **pulse rate** (typically 42–210 BPM in the 0.7–3.5 Hz passband), displayable experimentally as single snapshots after quality gates pass.
- An experimental waveform (green/POS/CHROM transforms) and **pulse-rate variability (PRV)** derived from successive pulse intervals.

## 2. What rPPG cannot establish — hard statements

- **Not blood pressure.** Camera optics sense light absorption at the skin surface; they have no access to arterial pressure. A camera-derived pulse rate is not a blood pressure measurement, cannot detect hypertension or hypotension, and cannot substitute for a validated cuff or invasive measurement.
- **Not PRV as HRV.** Variability of camera-derived pulse intervals (PRV) is a different measurement from ECG-derived heart-rate variability (HRV). PRV confounds with pulse propagation-time changes, motion and arrhythmia; it must not be reported, compared or used as "HRV", and no claim of agreement with ECG-derived HRV is made or implied.
- **Not cardiac output, stroke volume, blood volume or SpO₂.** No hemodynamic quantity beyond pulse rate is estimated.
- **Not a diagnosis.** No condition, disease, arrhythmia or clinical state is detected, excluded or ranked.
- **Not anemia. Not hemoglobin. Not iron deficiency.** Conjunctival appearance cannot establish hemoglobin concentration or iron deficiency: conjunctival color is affected by illumination, camera response, exposure, vascular patterning, pigmentation, camera handling and lighting geometry. Pallor is not a laboratory measurement, and conjunctiva analysis cannot yield a hemoglobin value.
- **The anemia component of RSBVP is not a validated predictor** of anything. No verified, laboratory-labelled, participant-independent dataset has been used; no model is trained, configured or shipped. The UI states this; `docs/ANEMIA_MODEL_CARD.md` remains the controlling document. A validated predictor would require, at minimum: a legally obtained, laboratory-labelled dataset (Hb from venous/capillary sampling), participant-independent patient-level splits, pre-registered evaluation, subgroup reporting and external replication — none of which exists in this repository.

## 3. What RSBVP will not become (this sprint and unless separately authorized)

- No anemia prediction model, no risk scores, no screening recommendations, no diagnostic or treatment advice, no public-health screening rollout.
- No new human-participant data collection (no classmates, patients, colleagues, or online strangers) without full ethics/consent infrastructure, which this project does not have.
- No monetization, subscriptions, advertising, sales funnels or growth architecture.

## 4. Privacy and data protection

- Live capture is processed in-browser; frames are not uploaded or stored; only numeric traces leave memory on explicit user export.
- Dataset use (when authorized) is research-only, outside Git, pseudonymous, with citation; no redistribution.
- Uploaded files are handled by the configured backend; see `docs/PRIVACY.md`. Reports never contain direct identifiers or raw media.
- Model checkpoints and weights never live in this repository (`RSBVP_MODEL_ROOT`).

## 5. Transparency obligations (what we publish, always)

1. **Validation status.** `reports/validation/validation.md` and `reports/research_validation/` state, in bold, when dataset evaluation has NOT RUN. Passing CI is never presented as physiological evidence.
2. **Provenance.** Every number carries its fixture/dataset, configuration, seed, tool versions and commit (see `reports/research_validation/README.md` §"Evaluation configuration").
3. **Limitations are part of the interface**, not a footnote: the app UI carries a "What this cannot tell you" section mirroring §2 of this document (`gui/frontend/src/App.tsx`).
4. **Negative results and failures** are kept in the open (e.g. the 17.5 BPM frame-drop bias and the spectral-concentration false-accept, both documented in `reports/research_validation/validation_report.md` §6).
5. **Open collaboration.** MIT license (application code) with preserving attribution; third-party research tools keep their own licenses; RAIL-1.1 flow-down applies to anything derived from the rPPG-Toolbox (`docs/OPEN_SOURCE_LICENSE_REGISTER.md` §F); pyVHR stays GPL-3.0-isolated.

## 6. Who this is for, and how to read it

RSBVP is for researchers, students and reviewers studying whether accessible camera-based pulse measurement can be made reliable, and how open science serves community health awareness responsibly. It is not for patients, clinicians, triage, screening or self-diagnosis. If you are judging this project, judge it on calibration curves and honesty labels — never on a promising demo clip.

## 7. Reporting concerns

Suspected claims beyond this contract (UI text, README, screenshots, videos, issues) are bugs of the highest severity. Report via the repository issue tracker with the offending text and location. Do not patch over scientific-accuracy issues with disclaimers after the fact; remove or correct the claim.
