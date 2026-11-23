# Research validation reports (Sprint 6) — evidence before deployment

**Overall status: dataset-level validation NOT RUN — UBFC-rPPG archive not present.**
Everything below separates *what was verified in this workspace* from *what was not*. Nothing in this directory is a medical or clinical claim.

| File | Contents |
|---|---|
| `DATA_READINESS.md` | UBFC-rPPG provenance (official page verified 2026-11-23), access status, unverified items, required steps before any dataset run |
| `data_readiness.json` / `data_readiness.md` | Machine/human-readable probe output; status `not_available` (0 recordings detected locally) |
| `validation_report.md` | Scientific evaluation summary: methods compared, metrics machinery, synthetic results, NOT RUN matrix, validated-vs-unknown lists |
| `synthetic/reliability_synthetic.json` / `.md` | Deterministic synthetic degradation suite (low light, noise, motion, frame drops, low fs, ROI dropout) — software verification only |
| `synthetic/` (see also `../research_backends/synthetic/`) | Deterministic 70 BPM synthetic benchmark summary (native vs reference backends) |
| `plots/reliability_availability.png` | Availability per degradation condition (synthetic) |

## Dataset provenance and availability

- Official page verified: `https://sites.google.com/view/ybenezeth/ubfcrppg` (2026-11-23) — acquisition conditions, subsets (8 simple / 42 realistic-of-46) and citation requirement are recorded in `DATA_READINESS.md`.
- Archive access: **not obtained; not present; not reachable from this workspace.** No participant data exist here.
- License/terms: no explicit license on the official page; research use with citation requested (Bobbia et al., *Pattern Recognition Letters*, 2017); treated as research-only, no redistribution. Full register entry: `docs/OPEN_SOURCE_LICENSE_REGISTER.md` §D.
- Evaluation targets when authorized data exist: UBFC-rPPG realistic subset (42) primary; simple subset (8) sanity check; COHFACE later (different conditions; never mixed into UBFC metrics).

## Evaluation configuration (applies to every reported number)

| Setting | Value |
|---|---|
| Platform | synthetic fixtures + in-process backends; external tools (toolbox, pyVHR) not run (no archive, no GPU) |
| Window | 12 s hann-windowed; gap > 0.25 s rejects the window; short gaps linearly interpolated (≤ 0.25 s) |
| Step | 6 s |
| Passband / estimator | 0.7–3.5 Hz; hann-periodogram-v1, max power in passband |
| Reference | never passed to backends; joined afterwards; ECG excluded by design |
| Participant handling | recording-level; participant bootstrap only with an authorized recording→participant mapping |
| Hardware | x86-64 Linux, CPU only; software versions below |
| Seeds | 20261123 (synthetic), benchmark fixture 11 |

Software (this workspace, 2026-11-23): Python 3.11.2 (scratch venv; CI targets 3.12) · numpy 2.4.6 · scipy 1.17.1 · pandas 3.1.1 · matplotlib 3.11.2 · OpenCV headless (exact version in CI logs) · git HEAD `7873734` + Sprint 6 working tree.

Checkpoint hashes: **not applicable — no neural checkpoint was used or present.** `RSBVP_MODEL_ROOT` unset.

## Participant-level split definitions

Dataset absent → no split was executed. Protocol locked for when data arrive:
- Realistic subset (42 recordings): sole evaluation set; **no tuning** on it; simple subset (8) used only as a sanity check; no training of any kind in this project phase.
- Neural baselines (if ever run): toolbox-published PURE→UBFC-rPPG cross-dataset protocol only; UBFC-rPPG never used for training.
- Unit of analysis: recording. Participant-level claims only with the provider's recording→participant mapping.
- No participant leakage: nothing to leak into — no fitting step exists.

## Failure analysis

See `docs/RELIABILITY.md` (investigation) and `validation_report.md` (synthetic evidence): low-light POS bias (backend POS degrades at 0.15× gain in the synthetic suite), spectral-concentration gate does not catch systematic HR bias, frame drops > 0.25 s now reject windows (fixed), ROI dropout yields 1/3 unavailable windows by design, motion transients did not bias HR in this fixture, browser/MediaPipe failure states remain hardware-untested.

## Limitations (binding)

1. Zero real-world evidence exists for any physiological or clinical claim; do not cite this directory as validation of measurement accuracy.
2. Synthetic results exercise software paths only; the degradation model (e.g. unscaled read noise) is a modelling choice, not a sensor model verified against hardware.
3. The quality gates are conservative software checks, not physiological validators.
4. External research backends (rPPG-Toolbox, pyVHR) remain unexecuted here; their documented licenses and pins stand as written.
5. `reports/validation/validation.md` remains `NOT RUN — DATASET NOT AVAILABLE`.

## Reproducing this directory

```bash
# readiness state (writes data_readiness.json/md)
python research/rppg/ubfcrppg_probe.py --archive-dir <absent-or-present> --output-dir reports/research_validation

# synthetic benchmark (native vs reference)
python research/backends/benchmark.py reports/research_backends/synthetic/inputs/synthetic_70bpm.csv \
    --backends rsbvp_native,rsbvp_reference \
    --reference-windows reports/research_backends/synthetic/inputs/reference_windows.csv \
    --reference-source "deterministic synthetic fixture (software verification only)" \
    --output-dir reports/research_backends/synthetic

# synthetic degradation suite
python research/backends/reliability.py --output-dir reports/research_validation/synthetic
```
