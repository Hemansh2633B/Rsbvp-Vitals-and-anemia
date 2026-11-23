# Sprint 3 real-data evaluation status

**NOT RUN — DATASET NOT AVAILABLE**

- UBFC-rPPG: NOT RUN. No archive or official documentation was available in the repository or accessible workspace. The Google Drive URL supplied in chat could not be retrieved here. File layout, labels, reference units/rates, and licensing have not been verified.
- COHFACE: NOT RUN. No local archive or inspected official documentation.
- Anemia data: NOT RUN and out of scope for this sprint.

The browser/Python synthetic fixtures are software regression tests only. They are not included as dataset performance results. The reference waveform estimator is limited to PPG/BVP; ECG is explicitly rejected until a validated R-peak implementation is available. Timestamp jitter, gaps, modality, sampling rates, and coverage are assessed/reported for future authorized local data. No hardware camera test or synchronized physiological-reference evaluation has been performed.

The implementation supports local explicit manifests and reference CSV or explicitly configured HDF5 signal paths. Dataset-specific paths/keys must be filled only after inspection of the acquired archive and official docs. Browser quality-gate coverage is NOT AVAILABLE from RGB-only trace exports, so estimate availability is not used as a proxy. No participant recording was downloaded, uploaded, or committed.

**Sprint 6 update:** see `reports/research_validation/` for the dataset readiness report (official UBFC-rPPG page verified 2026-11-23; archive still absent), the deterministic synthetic degradation suite and the scientific validation report separating software verification from dataset evidence. Status remains `NOT RUN — DATASET NOT AVAILABLE`.
