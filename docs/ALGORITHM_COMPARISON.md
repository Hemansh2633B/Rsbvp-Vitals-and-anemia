# rPPG recording comparison workflow

The comparison script accepts a browser-exported timestamped RGB trace CSV or a manifest (`recording_id,csv_path`). It computes independent per-window Green, POS and CHROM estimates for forehead, each cheek, both cheeks combined, and combined available ROIs. Each method/ROI remains independently visible in the JSON. It regularizes timestamped traces on the median sampling grid, interpolates only across short gaps, rejects long gaps and leaves missing ROI channels unavailable. It never substitutes zero for missing pixels or traces.

```bash
python research/rppg/compare_algorithms.py /data/session.csv --output session_eval.json
# multiple recordings
python research/rppg/compare_algorithms.py /data/manifest.csv --reference-source 'synchronized ECG/pulse reference; protocol and provenance recorded separately' --output evaluation.json
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
  --output-dir reports/validation/local-run
```

The reference CSV requires a time column or verified reference sampling rate, an explicit signal column/type, and `time_offset_s` mapping reference clock onto trace clock. HDF5 requires `h5py`, an explicit dataset path, and verified sampling rate. HR is extracted independently per window; missing samples, insufficient windows, and long gaps receive rejection reasons. No long-gap interpolation or silent synchronization is done. The report gives per-window and per-recording results, participant-level summaries and participant bootstrap for 2+ participant groups. Overlapping-window aggregates are descriptive, not independent subjects. The RGB-only offline tool has no stored per-window browser gate state; it reports estimator availability, not quality-gate coverage. Synthetic traces remain automated software tests only and are never dataset benchmark results.
