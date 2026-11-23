# rPPG recording comparison workflow

The comparison script accepts a browser-exported timestamped RGB trace CSV or a manifest (`recording_id,csv_path`). It computes independent per-window Green, POS and CHROM estimates for forehead, each cheek, both cheeks combined, and combined available ROIs. Each method/ROI remains independently visible in the JSON. It regularizes timestamped traces on the median sampling grid, interpolates only across short gaps, rejects long gaps and leaves missing ROI channels unavailable. It never substitutes zero for missing pixels or traces.

```bash
python research/rppg/compare_algorithms.py /data/session.csv --output session_eval.json
# multiple recordings
python research/rppg/compare_algorithms.py /data/manifest.csv --reference-source 'synchronized ECG/pulse reference; protocol and provenance recorded separately' --output evaluation.json
```

The CSV may include a per-row synchronized `reference_hr_bpm` column. Error metrics are intentionally absent unless `--reference-source` is supplied. Supplying the string is an assertion by the researcher, not machine-verifiable provenance. Preserve source device, synchronization, participant/session split, and protocol outside the tool output and review before publication. Manifest paths resolve relative to the manifest directory.

Window outputs are 12-second windows stepped by 6 seconds. Aggregate MAE, RMSE, bias, and Bland–Altman limits of agreement are reported pooled and per recording. These overlapping windows are correlated, so pooled window counts are not independent participant counts and must not be represented as such. For inferential uncertainty, pre-specify participant-level aggregation/bootstrapping and use held-out participants. A single recording is not a validation study.

Browser export contains frame timestamps and ROI mean RGB values only; it does not contain video or a reference signal. A reference must be synchronized, separately measured, and lawfully available. Synthetic traces appear only in automated software tests and are never benchmark results.
