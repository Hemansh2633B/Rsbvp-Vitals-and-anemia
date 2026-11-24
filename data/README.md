# Local research data (never commit datasets)

This directory contains schema examples only. Put licensed data outside the repository whenever possible. Configure the root with `RSBVP_DATA_ROOT=/absolute/path/to/research-data` or pass `--data-root /absolute/path` to supported research CLIs. Relative manifest paths resolve under that root; no tool downloads, uploads, or silently searches for data.

## Expected layout

```text
$RSBVP_DATA_ROOT/
  ubfc-rppg/                 # locally acquired archive, unchanged
  cohface/                   # locally acquired archive, unchanged
  mmpd/                      # MMPD full dataset (subject<n>/p<n>_*.mat), unchanged
  traces/                    # browser RGB exports or derived traces
  references/                # synchronized reference waveforms
```

Use `data/manifests/*.example.csv` as blank schema examples, copy them outside the repository, and fill only non-identifying provider recording/participant codes. Each row should identify the dataset/version, recording and participant pseudonyms, relative source/trace/reference paths, and an explicit reference format, timestamp convention, sampling frequency and clock offset where applicable. Do not put names, contact details, exact birth dates, or direct identifiers in manifests/reports.

## Intake requirements

Before processing, record the provider's official title/version, source URL or access method, citation, terms/license and date obtained in a local provenance note. Confirm research and redistribution permissions. Never commit archives, videos, facial images, HDF5 files, derived participant-level data, keys, or private metadata. Raw/processed research data patterns are ignored by Git. The manifest templates are not claims about the actual contents or layout of UBFC-rPPG, COHFACE or MMPD.

Dataset-specific adapters must be configured against the actual downloaded archive and official data documentation. Do not infer filenames, HDF5 dataset keys, reference sampling rates, or synchronization offsets from this template. Missing or malformed reference samples invalidate the affected analysis window; long gaps are not extrapolated. Keep pulse/PPG/BVP distinct from ECG. Respiration is a separate outcome and is not a heart-rate reference.

## Reference schema supported by Sprint 3 tools

A canonical reference CSV has a header and one row per observation. Required columns are `timestamp_s` (seconds on the source sensor clock) and one explicitly mapped numeric signal column such as `ppg`, `bvp`, or `ecg`. `timestamp_s` may be omitted only when the manifest provides a verified positive `reference_fs_hz`, in which case sample times are derived from sample index. `time_offset_s` maps reference-clock seconds onto the trace-clock seconds as `trace_time = reference_time + time_offset_s`. The offset must come from documented synchronization, not a guessed visual match. `reference_type` distinguishes `ppg`, `bvp`, or `ecg`; the current evaluator supports waveform-frequency estimates for PPG/BVP only. ECG rows are intentionally rejected with `ecg_rpeak_estimator_unavailable` until a validated R-peak method is implemented and verified. Respiration must be processed with a separate protocol.

## Citations and provenance

Cite the original dataset publication and provider documentation in every report or publication. This repository does not bundle dataset licenses or attest that a user has permission. The Google Drive link previously supplied was not accessible to the development environment, so no UBFC-rPPG archive or documentation has been verified here. COHFACE is also unavailable locally. Real-data evaluation is therefore explicitly NOT RUN.

MMPD is likewise not present here: the public GitHub repository (MIT-licensed code) ships only 16 short sample GIFs, label CSVs, and pre-trained checkpoints — the dataset itself (370 GB full / 48 GB mini, `.mat` files) requires the signed MMPD data-release agreement (faculty-signed email to the authors, see `docs/MMPD_VALIDATION.md`). The sample GIFs under `gif/` were used for the pipeline smoke check in `reports/mmpd/`; they are not validation data.
