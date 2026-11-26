# Research export schema (browser-local capture)

Two research-only export files are produced when the user explicitly presses
**Export traces + window analysis** in the browser-local view. Nothing is
uploaded automatically; both downloads are initiated locally. Camera frames are
never included and are never stored by this app. Files may contain sensitive
research data — store them accordingly. No identifiable patient data should be
recorded; this pathway is not approved for human-participant research.

## 1. `rsbvp_rgb_trace_<UTC-stamp>.csv`

Raw, timestamped RGB means per ROI. Columns:

`timestamp_s, forehead_r, forehead_g, forehead_b, left_cheek_r, left_cheek_g,
left_cheek_b, right_cheek_r, right_cheek_g, right_cheek_b`

- `timestamp_s` — monotonic browser clock in seconds (`performance.now()/1000`), **not** wall-clock time. Relative to nothing; use consecutive differences for timing.
- ROI cells are **empty** when the ROI was missing/invalid in that frame — never zero-filled.
- ROI identity = `forehead | left_cheek | right_cheek`, polygons derived from MediaPipe Face Landmarker landmarks (see `gui/frontend/src/rppg/BrowserPulse.tsx`), intersected with an RGB skin heuristic and eye/lip/brow exclusions. This is heuristic capture-quality filtering, **not** MediaPipe segmentation.
- Sampling info in the companion `.json` (`sample_rate_median_hz`, `dropped_interval_fraction`, `passband_hz`); gaps > 0.25 s are not interpolated by the browser DSP (the window is rejected instead).

## 2. `rsbvp_rgb_trace_<UTC-stamp>.json` (trace metadata)

Schema `rsbvp.rgb-trace.v1`. Fields:

| field | meaning |
|---|---|
| `created_utc` | wall-clock export time |
| `capture_session_id` | random non-identifying id (`sess-<16 hex>`) linking this CSV to its `.json` and `_windows.json` from one capture session; not a device or person identifier |
| `software` | `{name, version, commit, package}`; `version` = `1.0.0` (matches `CITATION.cff`), `commit` = `VITE_GIT_SHA` when set at build time, else `unknown` — never invented |
| `analysis_config` | `{backend, passband_hz, required_seconds, min_roi_coverage, spectrum, roi_method, algorithms}` — the exact estimator configuration used; parameters are fixed, never tuned per recording |
| `sample_count`, `earlier_samples_dropped_due_to_buffer_limit` | surviving vs. dropped samples (cap 18000) |
| `trace_start_timestamp_s`, `trace_end_timestamp_s`, `acquisition_duration_seconds` | coverage |
| `camera_fps_reported` | from `getVideoPlaybackQuality()` (browser-reported, unverified) |
| `sample_rate_median_hz`, `dropped_interval_fraction` | measured from trace timestamps |
| `passband_hz` | `[0.7, 3.5]` Hz estimator passband |
| `roi_method`, `algorithms` | extraction method + Green/POS/CHROM |
| `measurement_status`, `measurement_reason` | composite verdict at export time |
| `estimates_bpm` | per `<roi>_<method>` estimates; `null` = unavailable |
| `valid_consensus_bpm` | consensus only when quality gates pass; else `null` |
| `quality_concepts` | six separated concepts (`face_tracking`, `roi_extraction`, `temporal_acquisition`, `pulse_signal`, `algorithm_agreement`, `availability`), each `pass` / `fail` / `not_evaluated`; never a blended score |
| `roi_coverage` | per-ROI fraction of samples with a usable skin ROI in the exported window |
| `roi_coverage_overall` | union coverage: fraction of samples with at least one usable skin ROI (gate: >= 0.50 for a `valid` verdict) |
| `browser`, `frame_images_included: false`, `frames_uploaded: false` | provenance |
| `notes` | honesty note: browser variants are not guaranteed numerically identical to Python (see §3.3 parity tests for what *is* demonstrated) |

## 3. `rsbvp_rgb_trace_<UTC-stamp>_windows.json` (per-window analysis)

Schema `rsbvp.window-analysis.v1`:

| field | meaning |
|---|---|
| `created_utc` | wall-clock export time |
| `capture_session_id` | same non-identifying session id as the trace metadata (§2) |
| `software` | `{name, version, commit, package}` as in §2 |
| `window_count` | number of retained window records (ring buffer, cap 3600) |
| `dropped_windows_due_to_buffer_limit` | windows evicted before export |
| `window_records[]` | one record per analyzed window, chronological |

Per record:

| field | meaning |
|---|---|
| `window_index` | monotonically increasing analysis-window index |
| `window_start_s`, `window_end_s` | bounds of the analyzed RGB window (`timestamp_s` clock, §1); `null` if the window bounds were unavailable — never fabricated |
| `n_samples` | samples in the analyzed window |
| `analyzed_utc` | wall-clock analysis time |
| `software` | `{name, version, commit, package}` |
| `backend` | `rsbvp-browser-liveDsp` — the implementation that produced the window |
| `analysis_config` | `{passband_hz, required_seconds, min_roi_coverage, spectrum}` used for this window |
| `effective_sampling_rate_hz` | measured from window timestamps (median interval), or `null` |
| `consensus_bpm` | consensus or `null` when the window verdict is not `valid` |
| `per_estimator_bpm` | map `<roi>_<method>` → BPM or `null` — disagreement is always visible |
| `quality_score` | spectral concentration of the window (0–1); **not** a calibrated probability |
| `consistency_bpm` | max−min spread across valid estimator BPMs |
| `availability_status` | one of `warming_up, valid, low_signal_quality, excessive_motion, face_not_detected, roi_lost, insufficient_frames, irregular_timestamps, reacquiring, processing_error` |
| `rejection_reason` | human-readable explanation; `null` iff status `valid` |
| `spectral` | `{fsHz, durationS, maxGapS, peakFraction, snrDb, separationRatio, roiCoverage, roiCoverageOverall}` — diagnostic scores; uncalibrated research metrics |
| `roi_coverage`, `roi_coverage_overall` | per-ROI and union ROI coverage fractions for the window |
| `quality_concepts` | six separated concepts, each `pass` / `fail` / `not_evaluated` |
| `selected_display_algorithm` | the algorithm chosen in the UI dropdown at analysis time (`green`, `pos`, `chrom`) |

## 4. Session exports (Sprint 13)

Two additional local downloads sit alongside the trace and window exports. They are
new schemas rather than changes to the existing ones, so consumers of
`rsbvp.rgb-trace.v1` / `rsbvp.window-analysis.v1` are unaffected.

### 4.1 `rsbvp_session_readings_<UTC-stamp>.csv`

One row per reading, **accepted and rejected alike**, so an export can never be
mistaken for a curated subset.

| column | meaning |
|---|---|
| `reading_id` | monotonic within the session |
| `metric`, `unit` | `heart_rate`/`BPM` or `respiratory_rate`/`br/min`; never mixed in one aggregate |
| `value` | estimate; empty cell when the estimator produced nothing — never 0 |
| `algorithm`, `roi` | `consensus` for the agreement-checked per-window estimate, or the estimator label; `all`/`face`/named ROI |
| `accepted` | `true`/`false` |
| `rejection_reason` | the existing verdict reason; empty iff accepted |
| `quality_score`, `quality_verdict` | existing spectral concentration (0–1, not a probability) and composite verdict token |
| `sampling_rate_hz`, `n_samples`, `window_start_s`, `window_end_s` | acquisition context; empty when unknown |
| `session_elapsed_s`, `window_index` | ordering within the session |
| `recorded_utc` | analysis wall-clock time |

### 4.2 `rsbvp_session_summary_<UTC-stamp>.json` (`rsbvp.session-aggregate.v1`)

| field | meaning |
|---|---|
| `schema` | `rsbvp.session-aggregate.v1` |
| `capture_session_id` | same non-identifying `sess-…` id as the trace exports |
| `primary_series` | `consensus` — the only series presented as the session result |
| `metrics[]` | per metric: `verdict` (`available`/`insufficient`/`no_readings`), `reason`, accepted/rejected/total, `acceptance_pct`, mean, median, min, max, sd, range, `independent_windows`, `overlap_factor`, `standard_error`, `median_quality_score` |
| `per_estimator[]` | the same block per GREEN/POS/CHROM series — diagnostics, never averaged together |
| `windows_total`, `windows_accepted`, `windows_rejected` | counts of analysed windows (consensus series) |
| `readings_total`, `readings_accepted` | counts including per-estimator series |
| `acceptance_pct`, `acceptance_band` | observed acceptance rate and its Good/Fair/Poor band; `acceptance_band_note` states explicitly that this is **not** a confidence score |
| `completion_state` | `idle`/`collecting`/`complete` |
| `aggregation_config` | `min_accepted_readings`, `min_independent_windows`, `target_accepted_readings`, `stale_after_ms`, `plausible_bounds` |
| `acquisition` | backend, algorithms, ROIs, passband, required seconds, camera label, sampling rate |
| `statistics_notes` | the independence and accuracy caveats, so the file cannot be quoted without them |
| `frames_images_included: false`, `frames_uploaded: false` | provenance |

Missing values are `null` (JSON) or empty (CSV). Nothing is zero-filled, and
`standard_error` is `null` when fewer than three independent windows exist.

## Schema versions and compatibility

Schemas are versioned in the `schema` field (`rsbvp.rgb-trace.v1`,
`rsbvp.window-analysis.v1`). Additive fields (such as the provenance block
above, added in v1 after Sprint 8) may appear in a minor consumer without a
version bump; removed or renamed fields, or changed meanings, require a new
major tag (`v2`). Consumers must tolerate unknown additive keys and must treat
unknown major tags as unreadable. The Python benchmark summary
(`rsbvp.benchmark-summary.v1`) likewise carries an additive `run` block
(`rsbvp.benchmark-run.v1`: software name/version/commit, python/numpy/scipy/
opencv versions, platform, full benchmark configuration, and the manifest
SHA-256) — see `research/backends/run_info.py`.

## Provenance and honesty rules

- Missing values are always `null`/empty/omitted — **never** zero, never the
  last known estimate.
- `valid` (availability) is a software quality gate, not a physiological or
  clinical statement; no export may be used as a diagnostic output.
- Exports carry `frame_images_included: false` and `frames_uploaded: false`;
  no frame payload exists in any export by design.
- No export contains participant identifiers; `capture_session_id` is random
  per capture and non-identifying.
- Reference-device provenance, when a CMS50D/CMS50E is ever used, must be
  recorded in the manual-session record (`docs/CAMERA_HARDWARE_VALIDATION.md`),
  not in these files.

## Honest limitations

- Window records reflect analysis ticks (≈2 Hz while running), not a fixed grid; overlapping windows are **correlated observations** and must not be treated as independent samples in statistics.
- Status `valid` is a software gate, not a physiological claim. It means capture/tracking/signal/estimator-agreement checks passed — nothing more.
- `effective_sampling_rate_hz` is derived from browser timestamps; gaps in the underlying camera stream appear as `maxGapS` and should be inspected, not assumed away.
- Comparisons against Python require the same windows, regular timestamps (`regularize_segment` conventions) and the documented parity procedure. See `tests/fixtures/generate_rppg_rgb_fixture_expected.py` and `gui/frontend/src/rppg/liveDsp.parity.test.ts`.
