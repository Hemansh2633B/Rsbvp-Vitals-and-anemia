# rPPG recording comparison workflow

The comparison script accepts a browser-exported timestamped RGB trace CSV or a manifest (`recording_id,csv_path`). It computes independent per-window Green, POS and CHROM estimates for forehead, each cheek, both cheeks combined, and combined available ROIs. Each method/ROI remains independently visible in the JSON. It regularizes timestamped traces on the median sampling grid, interpolates only across short gaps, rejects long gaps and leaves missing ROI channels unavailable. It never substitutes zero for missing pixels or traces.

```bash
python research/rppg/compare_algorithms.py /data/session.csv --output session_eval.json
# multiple recordings
python research/rppg/compare_algorithms.py /data/manifest.csv --reference-source 'documented externally computed reference BPM; protocol and provenance recorded separately' --output evaluation.json
```

The CSV may include a per-row synchronized `reference_hr_bpm` column. Error metrics are intentionally absent unless `--reference-source` is supplied. Supplying the string is an assertion by the researcher, not machine-verifiable provenance. Preserve source device, synchronization, participant/session split, and protocol outside the tool output and review before publication. Manifest paths resolve relative to the manifest directory.

Window outputs are 12-second windows stepped by 6 seconds. Aggregate MAE, RMSE, bias, and Bland–Altman limits of agreement are reported pooled and per recording. These overlapping windows are correlated, so pooled window counts are not independent participant counts and must not be represented as such. For inferential uncertainty, pre-specify participant-level aggregation/bootstrapping and use held-out participants. A single recording is not a validation study.

Browser export contains frame timestamps and ROI mean RGB values only; it does not contain video or a reference waveform. The exported final estimate/status is not a per-window quality-gate label, so offline estimate availability must not be described as the browser quality-gate coverage. A reference must be synchronized, separately measured, and lawfully available.

## Local reference-waveform evaluation

Use the Sprint 3 explicit manifest and local-only evaluator after inspecting the actual dataset archive and verifying its license and clock mapping:

```bash
export RSBVP_DATA_ROOT=/absolute/path/to/local-research-data
python research/rppg/validate_dataset.py /absolute/path/to/manifest.csv \
  --window-seconds 12 --step-seconds 6 --max-reference-gap-seconds 0.25 \
  --max-timestamp-jitter-fraction 0.05 \
  --output-dir reports/validation/local-run
```

The reference CSV requires a time column or verified reference sampling rate, an explicit signal column/type, and `time_offset_s` mapping the reference clock onto the trace clock. HDF5 requires `h5py`, an explicit dataset path, and verified sampling rate; HDF5 time arrays are not guessed. Reference timestamps must be finite and strictly increasing. The configurable robust median absolute interval jitter tolerance defaults to 0.05; the configurable maximum interval gap defaults to 0.25 seconds. Accepted PPG/BVP windows are linearly interpolated onto a uniform grid only after coverage, jitter, gap, missing-value, Nyquist, and waveform-quality checks, then filtered and processed with a Hann-window periodogram. Complete `[start, end)` coverage is required, allowing at most one source sample of endpoint quantization. Reports preserve declared/original, timestamp-measured, and resampled effective rates, jitter, and rejection reasons. ECG is deliberately rejected (`ecg_rpeak_estimator_unavailable`) until a validated R-peak implementation exists; no ECG-HRV claim is supported. Missing values invalidate the affected window; long gaps are never crossed.

Heart rate is extracted independently per window. Reports separate total windows, valid reference windows, available estimates, paired windows, and reference rejection reasons. Per-recording and per-participant summaries are emitted; participant bootstrap is only available with 2+ distinct participant groups. Overlapping-window aggregates are descriptive, not independent subjects. Browser RGB exports do not contain per-window gate state, so quality-gate coverage is explicitly NOT AVAILABLE; estimate availability is not substituted for it. Synthetic traces remain automated software tests only and are never dataset benchmark results.
