# Sprint 3 implementation audit (2026-11-23)

## Scope and repository state

The checked-out feature branch is `arena/91745e3e-rsbvp-vitals-and-anemia` at `9a5d0c3`, with no local changes at audit start. `origin/main` currently points to `edcdaf3`; it does not include the Sprint 2 feature-branch commits. Per the workspace rule, work remains on the current branch rather than switching branches. This audit is against the current feature branch. No UBFC-rPPG/COHFACE archive or official dataset documentation is present locally; the supplied Drive link is not reachable in this environment. Therefore no dataset-specific file layout is asserted and no real data has been processed.

## Code review findings

- `gui/frontend/src/rppg/BrowserPulse.tsx` samples video frames with `performance.now()` and avoids identical `video.currentTime` frames; exports RGB/time data. It handles permission/model/worker errors, stop, face loss and a device `ended` event. Timestamp is browser monotonic time, not a synchronized reference clock. Reference alignment cannot be inferred from browser export alone.
- `gui/frontend/src/rppg/liveDsp.ts` estimates a median frame interval, regularizes per ROI, interpolates short gaps and rejects gaps above its limit. It computes Green/POS/CHROM and quality measures in TypeScript. It uses FFT-domain peak selection rather than the Python IIR pipeline; Python uses filtering and can use different windowing/peak refinement. Existing parity test covers only a deterministic frequency fixture, not full method/waveform equivalence. No parity claim is warranted.
- `gui/frontend/src/rppg/roi.ts` derives landmark polygons and filters pixel RGB values; missing/empty ROI is represented as unavailable. This is a heuristic, not validated skin segmentation.
- `gui/rppg_core/pipeline.py` is the legacy/offline capture and DSP implementation and retains CMS50D-related functionality. Its IIR/filter/peak and historical correction paths are not identical to the browser implementation.
- `gui/rppg_core/research.py` contains an independent CHROM utility, timestamp/fs helpers, gap-aware RGB resampling and a conservative estimator agreement gate. Its resampling currently rejects an input-wide long gap rather than returning window-local invalidity.
- `research/rppg/compare_algorithms.py` compares timestamped RGB and optionally row-wise `reference_hr_bpm`; 12 s windows/6 s step are fixed defaults in this version. It reports overlapping-window metrics and per-recording aggregates, but it does not read synchronized reference waveforms or participant-grouped uncertainty. Reference provenance is researcher-asserted, not verified.
- Existing tests cover synthetic RGB, timestamp interpolation, basic quality gates, ROI handling, browser lifecycle, and Python/TypeScript frequency output. CI runs Python tests/compileall and frontend tests/build/lint with no dataset access.

## Correctness gaps carried into Sprint 3

1. The Drive link does not provide locally inspectable source artifacts, license terms, or schema. Dataset-specific parsing must remain gated on actual documentation/archive inspection.
2. Existing comparison cannot derive independent reference HR for each window from reference waveforms, preserve multi-rate clocks/offsets, or evaluate participant-level metrics.
3. Overlapping windows are not independent. The current report must not present them as independent participants.
4. Browser monotonic timestamps are not synchronized to an external sensor. An offset/clock mapping must be documented and supplied; no silent alignment is valid.
5. Missing-data behavior should reject affected windows explicitly; no interpolation over long gaps or fabricated reference values.
6. Existing tests establish software behavior only; no camera hardware or physiological validation has been performed.

## Planned scope and limits

Implement a local-only dataset root, manifest validation, explicit timestamped-reference waveform utilities and NOT RUN reports. Dataset adapters will use explicit manifest column/path mappings and validate supplied files; actual UBFC/COHFACE archive-specific mappings remain pending inspection of the actual archives and official documentation. No human data, recordings, or dataset samples are added to Git. No accuracy or clinical claim is made.
