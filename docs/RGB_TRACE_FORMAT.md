# Browser RGB experiment export (`rsbvp.rgb-trace.v1`)

Starting browser capture offers paired files: a CSV trace and JSON metadata. Both contain numeric/technical data only; no frame images are recorded or uploaded.

## CSV

Required header used by `research/rppg/compare_algorithms.py`:

```text
timestamp_s,forehead_r,forehead_g,forehead_b,left_cheek_r,left_cheek_g,left_cheek_b,right_cheek_r,right_cheek_g,right_cheek_b
```

- `timestamp_s` is a monotonic browser performance-clock timestamp in seconds, not wall-clock time. Preserve it for rate/gap handling.
- Channel values are mean 8-bit browser Canvas RGB intensities after polygon ROI selection, eye/brow/lip exclusion, and a conservative RGB skin heuristic.
- ROI failures are empty cells, not zero values. Missing or long-gap windows should remain unscored.
- A rolling buffer retains at most 18,000 recent samples (about 15 minutes at 20 Hz). The JSON reports how many earlier samples were discarded.
- No reference signal is included by default. Add a synchronized, lawfully acquired reference separately and document its provenance before computing accuracy metrics.

## JSON metadata

Contains schema version, UTC export time, trace span/count, earlier dropped-record count, duration, measured sample-rate/drop interval summary, passband, ROI/algorithm implementation notes, quality state/reason, per-estimator BPM values (null where unavailable), user-agent string and confirmation that images are absent/not uploaded. Treat the user-agent and health-derived numerical outputs as research metadata; protect files appropriately.

To run offline comparison, provide the CSV to the Python CLI. It can be used by the existing comparison workflow without copying any video or image data.
