# Shared RGB trace contract (`rsbvp.rgb-trace.v1`)

Two pathways emit the same CSV contract, but they are **not interchangeable**: the browser path uses MediaPipe landmark polygons in-page; the legacy Python path uses heuristic face/forehead/cheek extraction with OpenCV. Per-ROI numeric values are not guaranteed byte-identical between them. Missing ROIs are explicit in both (empty CSV cells; `null` in JSON); neither pathway fabricates a replacement.

Browser capture offers paired files: a CSV trace and JSON metadata, plus a per-window analysis JSON (`rsbvp.window-analysis.v1`). All contain numeric/technical data only; no frame images are recorded or uploaded.

## Required CSV header (both pathways)

```text
timestamp_s,forehead_r,forehead_g,forehead_b,left_cheek_r,left_cheek_g,left_cheek_b,right_cheek_r,right_cheek_g,right_cheek_b
```

Field semantics for `rsbvp.rgb-trace.v1`:

| Field | Meaning |
|---|---|
| `timestamp_s` | Monotonic seconds (browser `performance.now()/1000`; Python decoder times). Not wall-clock. Gaps are diagnostic, never interpolated across. |
| `*_r/g/b` per ROI | Mean 8-bit RGB intensity of the masked skin pixels for that ROI at that sample. Empty cell = that ROI unusable at that sample (never zero-filled). |
| validity | Implicit per-cell: a missing cell invalidates the ROI sample; it never invalidates other ROIs in the same row. |
| ROI coverage | Reported per window, not per cell: fraction of samples with a usable ROI, and the union-of-ROIs coverage used by the availability gate (`scores.roiCoverage` per ROI and `scores.roiCoverageOverall` in window analysis records). |
| missing-sample info | Empty cells in CSV; `dropped_interval_fraction` and the union coverage in JSON/window records; `earlier_samples_dropped_due_to_buffer_limit` for the rolling buffer. |
| tracking metadata | Browser: MediaPipe Face Landmarker presence (face/no-face per frame), per-ROI state strings, camera-reported FPS via `getVideoPlaybackQuality()`. Python heuristic path: detector bounding-box state; no landmark export. Neither records images. |
| provenance | Browser JSON records user-agent, export time, and confirmation that images are absent/not uploaded. Treat numeric output and user-agent as research metadata; protect accordingly. |

## CSV

The header above is exactly what `research/rppg/compare_algorithms.py` consumes.

- `timestamp_s` is a monotonic browser performance-clock timestamp in seconds, not wall-clock time. Preserve it for rate/gap handling.
- Channel values are mean 8-bit browser Canvas RGB intensities after polygon ROI selection, eye/brow/lip exclusion, and a conservative RGB skin heuristic.
- ROI failures are empty cells, not zero values. Missing or long-gap windows should remain unscored.
- A rolling buffer retains at most 18,000 recent samples (about 15 minutes at 20 Hz). The JSON reports how many earlier samples were discarded.
- No reference signal is included by default. Add a synchronized, lawfully acquired reference separately and document its provenance before computing accuracy metrics.

## JSON metadata

Contains schema version, UTC export time, trace span/count, earlier dropped-record count, duration, measured sample-rate/drop interval summary, passband, ROI/algorithm implementation notes, quality state/reason, per-estimator BPM values (null where unavailable), separated quality concepts, per-ROI and overall ROI coverage, user-agent string and confirmation that images are absent/not uploaded. Treat the user-agent and health-derived numerical outputs as research metadata; protect files appropriately.

## Browser-local vs Python-local extraction

- Browser (default live path): MediaPipe Face Landmarker polygons with eye/lip/brow exclusion; mean RGB per ROI computed in-page; nothing leaves the machine.
- Python (offline, `pipeline.py`): OpenCV face detection with heuristic forehead/cheek placement and YCrCb-style skin heuristics; used for uploaded/local video analysis on the backend host. Hardware = the backend host's, not the user's browser.
- Both paths emit the same CSV columns; only the browser path emits `rsbvp.window-analysis.v1` per-window records (see `docs/EXPORT_SCHEMA.md`).

To run offline comparison, provide the CSV to the Python CLI. It can be used by the existing comparison workflow without copying any video or image data.
