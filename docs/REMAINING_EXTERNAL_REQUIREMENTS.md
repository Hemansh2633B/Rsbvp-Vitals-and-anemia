# Remaining external inputs needed to finish the research prototype

This list separates user-provided artifacts/decisions from engineering work that can proceed without them. Do not send credentials, private medical records, or identifiable participant data through chat.

## Required for evidence-based scientific evaluation

1. **Anemia dataset access and terms**
   - Confirm whether you have lawful access to Eyes-defy-anemia or another dataset.
   - Provide its official acquisition instructions, applicable license/terms, and the local path only after downloading it yourself. Do not upload the dataset into Git or chat.
   - Provide dataset documentation/data dictionary and, if supplied by the provider, the mapping of image IDs to laboratory Hb, patient IDs, demographics, original/augmented status, and acquisition protocol. Redact direct identifiers. We must verify whether data access permits this research and publication.
   - If patient identifiers are absent, say so; patient-independent test claims cannot be made.

2. **Synchronized rPPG reference recordings**
   - A lawful research dataset. UBFC-rPPG (Dataset 1 simple: 8; Dataset 2 realistic: 42) is the primary candidate — official page verified 2026-11-23, archive not present in this environment; `reports/research_validation/DATA_READINESS.md` documents provenance, terms (research-only, citation Bobbia et al. 2017, no redistribution) and the exact steps required. COHFACE (160 × 1-minute sequences, 40 subjects, 640×480 @ 20 fps, PPG+respiration; non-commercial EULA via Idiap/Zenodo 4081054) is a secondary candidate — also not present. Alternatively, your own properly overseen recordings, stored locally outside Git.
   - Corresponding timestamps and reference pulse/ECG/respiration channels, sensor metadata, participant/session IDs, motion labels and protocol. Share documentation/schema first; do not share identifiable recordings unless there is an approved, secure transfer process.
   - For ECG-HRV claims specifically, synchronized ECG; pulse-only references can support PRV/pulse-rate comparison, not ECG HRV.

3. **Physical browser-camera execution**
   - Mocked unit/component tests cover failure and recovery paths, but no physical camera/browser matrix has been run. A local webcam, HTTPS/localhost build, and a consented test participant are needed to execute `docs/MANUAL_CAMERA_TESTS.md` and to see real MediaPipe behavior on low-light faces and real reacquisition timing.

4. **MediaPipe model artifact for offline/browser landmark tracking**
   - A MediaPipe Face Landmarker task model file and its license/redistribution terms, or authorization to fetch the official model artifact in your deployment workflow. The repository should not silently download a model or commit a model binary without provenance.
   - A local webcam/browser with permission is needed for functional capture tests. A face image is not needed in chat.

## Optional hardware and product choices

5. **CMS50D/device validation**: a supported physical device and platform/serial details for integration testing; do not send device logs containing personal data.
6. **Deployment target**: Vercel project access via the connected integration if you want an actual deployment, plus a persistent backend host decision (Vercel alone cannot provide webcam/serial access or persistent capture). Never provide secrets in chat; use the platform's secure connection flow.
7. **Anemia task definition**: decide regression-only if demographics/threshold data are inadequate, or provide the source guideline/population context needed for any screening-label definition. No universal Hb cutoff will be assumed.

## Work that can continue without these inputs

The codebase already includes classical RGB algorithms, algorithm-comparison tooling for explicitly supplied traces, image auditing/quality/color utilities, grouped-split and paired-regression metric primitives, documentation, tests, upload limits, and static frontend build preparation. Sprint 7 delivered: explainable per-window quality verdicts with conservative unavailable states in both the browser DSP and the Python live pipeline; Python↔TypeScript parity tests on a shared synthetic fixture; per-window research exports with a documented schema (`docs/EXPORT_SCHEMA.md`); deterministic low-light/quality regression tests; an enhanced dataset-audit tool (exact and near-hash duplicates, patient grouping); and full docs/capability matrix (`docs/CURRENT_STATUS_AUDIT.md`). Sprint 8 additionally delivered: six explicitly separated quality concepts (`face_tracking`, `roi_extraction`, `temporal_acquisition`, `pulse_signal`, `algorithm_agreement`, `availability`) with a union ROI-coverage gate; motion-buffer purging; explicit CHROM/estimator-failure unavailable paths in both pathways; mocked MediaPipe failure/reacquisition regression tests; a standardized anemia input-image contract and researcher-reviewed conjunctival-ROI annotation format with a machine-readable validator (`research/anemia/contract.py`, `docs/ANEMIA_IMAGE_CONTRACT.md`); and the authoritative capability matrix `docs/IMPLEMENTATION_STATUS.md`. Additional UI, APIs, unit tests and reproducibility tooling can still be developed without clinical records, but model training, dataset audit conclusions, final acceptance claims, live MediaPipe landmark validation, and empirical performance reports remain blocked until appropriate artifacts and provenance are available.

## Safe handoff

Please provide only a non-sensitive answer with: (a) which dataset and terms you can provide, (b) whether patient/group identifiers exist, (c) which synchronized references/hardware are available, (d) whether you can provide a licensed model asset or authorize fetching it, and (e) deployment target. Store data locally and give paths/documentation, not personal records or credentials.
