# Local research data (never commit datasets)

This directory contains schema examples only. Put licensed data outside the repository whenever possible. Configure the root with `RSBVP_DATA_ROOT=/absolute/path/to/research-data` or pass `--data-root /absolute/path` to supported research CLIs. Relative manifest paths resolve under that root; no tool downloads, uploads, or silently searches for data.

## Expected layout

```text
$RSBP_DATA_ROOT/
  ubfc-rppg/                 # locally acquired archive, unchanged
  cohface/                   # locally acquired archive, unchanged
  traces/                    # browser RGB exports or derived traces
  references/                # synchronized reference waveforms
```

Use `data/manifests/*.example.csv` as blank schema examples, copy them outside the repository, and fill only non-identifying provider recording/participant codes. Each row should identify the dataset/version, recording and participant pseudonyms, relative source/trace/reference paths, and an explicit reference format, timestamp convention, sampling frequency and clock offset where applicable. Do not put names, contact details, exact birth dates, or direct identifiers in manifests/reports.

## Intake requirements

Before processing, record the provider's official title/version, source URL or access method, citation, terms/license and date obtained in a local provenance note. Confirm research and redistribution permissions. Never commit archives, videos, facial images, HDF5 files, derived participant-level data, keys, or private metadata. Raw/processed research data patterns are ignored by Git. The manifest templates are not claims about the actual contents or layout of UBFC-rPPG or COHFACE.

Dataset-specific adapters must be configured against the actual downloaded archive and official data documentation. Do not infer filenames, HDF5 dataset keys, reference sampling rates, or synchronization offsets from this template. Missing or malformed reference samples invalidate the affected analysis window; long gaps are not extrapolated. Keep pulse/PPG/BVP distinct from ECG. Respiration is a separate outcome and is not a heart-rate reference.

## Reference schema supported by Sprint 3 tools

A canonical reference CSV has a header and one row per observation. Required columns are `timestamp_s` (seconds on the source sensor clock) and one explicitly mapped numeric signal column such as `ppg`, `bvp`, or `ecg`. `timestamp_s` may be omitted only when the manifest provides a verified positive `reference_fs_hz`, in which case sample times are derived from sample index. `time_offset_s` maps reference-clock seconds onto the trace-clock seconds as `trace_time = reference_time + time_offset_s`. The offset must come from documented synchronization, not a guessed visual match. `reference_type` distinguishes `ppg`, `bvp`, or `ecg`; respiration must be processed with a separate protocol.

## Citations and provenance

Cite the original dataset publication and provider documentation in every report or publication. This repository does not bundle dataset licenses or attest that a user has permission. The Google Drive link previously supplied was not accessible to the development environment, so no UBFC-rPPG archive or documentation has been verified here. COHFACE is also unavailable locally. Real-data evaluation is therefore explicitly NOT RUN.
