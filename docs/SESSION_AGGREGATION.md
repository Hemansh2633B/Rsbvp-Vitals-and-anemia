# Session aggregation — how a session result is computed

**Status:** implemented and software-tested. **No physiological validation, no
clinical validation, and no measurement-accuracy claim** is made anywhere in this
document or by the feature it describes.

## Why it exists

Each analysis window produces its own estimate, and consecutive estimates differ
(a few BPM between neighbouring windows is normal for camera rPPG). Presenting the
newest one as "the" result makes the application look unstable even when its
quality gates are working correctly. A session result fixes *what is presented*,
not the underlying signal: it reports what the accepted windows agree on, how many
there were, and how much independent evidence backs them.

Aggregation **reduces random variation**. It does not improve accuracy, cannot
remove systematic bias, and cannot make an unvalidated method valid. A session
average of accepted readings is still an estimate from a camera.

## Where it lives

| Layer | File | Purpose |
|---|---|---|
| Statistics (browser) | `gui/frontend/src/rppg/sessionAggregate.ts` | collector, acceptance rules, statistics, exports |
| Statistics (Python) | `gui/rppg_core/session.py` | the same rules for the server-side DSP pathway |
| Presentation | `gui/frontend/src/rppg/SessionResult.tsx` | one result, quality, history, chart, advanced details |
| Wiring | `gui/frontend/src/rppg/BrowserPulse.tsx`, `gui/frontend/src/Live.tsx` | browser and server pathways feed the same collector |

There is deliberately **one** collector implementation per language and both
pathways use it. Two independent aggregators would eventually disagree, and a user
has no way to tell which one is wrong.

## A reading

Every analysed window appends one reading per series:

| Field | Meaning |
|---|---|
| `id` | monotonic within the session; restart on reset |
| `metric` | `heart_rate` or `respiratory_rate` |
| `value` | the estimate, or `null` — never 0, never interpolated |
| `algorithm` | `consensus` (the agreement-checked per-window estimate) or an estimator label (`green_fft`, `pos_fft`, `green`, `pos`, `chrom`, …) |
| `roi` | `all` (consensus across ROIs), `face`, or a named ROI |
| `qualityScore` | the existing spectral-concentration score, 0–1. Not a probability |
| `qualityVerdict` | the existing composite verdict token (`valid`, `low_signal_quality`, `roi_lost`, …) |
| `sampling` | `fsHz`, `nSamples`, `windowStartS`, `windowEndS` — `null` when unknown |
| `accepted` | whether it counts toward the average |
| `finalRejectionReason` | why it was excluded; `null` iff accepted |
| `recordedUtc`, `analyzedAtMs`, `sessionElapsedS`, `windowIndex` | provenance and ordering |

Readings are **append-only**. The aggregate is derived on every render; it never
writes back. History survives a rejected window, an interruption, or a reacquisition
until the user starts a new session.

## Acceptance rules

A reading is accepted only when **all** of these hold:

1. The metric is one this module knows (adding an unknown metric is an error, not a
   default).
2. It is not stale — it arrived within `staleAfterMs` (5 s) of being analysed. The
   pipeline re-reporting an old result describes a moment that has passed.
3. The existing quality verdict is exactly `valid`. **No threshold was relaxed for
   this feature**; the gates are the ones that already existed.
4. The value is finite and inside a wide **data-hygiene** band: 30–220 BPM, 4–60
   br/min. These catch a unit mix-up or a lost estimate (0, 3, 900). They are not
   healthy ranges and must not be read as clinical bounds.

Everything else is recorded with a reason and counted as rejected.

## Statistics

Per metric, per algorithm series, over accepted readings only:

- mean (the presented session result), median, min, max, range
- sample standard deviation (n−1); `null` for a single reading
- accepted count, rejected count, acceptance percentage
- median quality score
- **independent window count** and overlap factor
- standard error — *only* from the independent subset, and `null` when fewer than
  three independent windows exist

### Overlapping windows are not independent observations

Both pathways re-analyse a sliding window (browser: every 500 ms over 10 s; server:
per update over its buffer). 400 readings can therefore describe ~40 distinct
moments. `countIndependentWindows` applies greedy interval scheduling by end time to
find the largest set of non-overlapping windows, and the UI reports that number.
The standard error is computed from it, never from the raw reading count. When
independence cannot be established (no window bounds), the standard error is `null`
rather than guessed.

### Why the mean *and* the median

The mean is the requested average and is the presented result. The median is shown
next to it because a single drifting window can pull a mean far more than a median;
when the two disagree the outlier sensitivity is visible instead of hidden.

## What is never combined

- **Metrics**: heart rate (BPM) and respiratory rate (br/min) are separate series
  with separate plausibility bands. They are never pooled.
- **Algorithms**: GREEN, POS and CHROM are not interchangeable. Each is summarised
  in its own series and appears only in advanced details; the presented result is
  the per-window consensus, which is the value the existing agreement gate actually
  checked.
- **Units**: no conversion is attempted anywhere.
- **Metrics that must not be aggregated**: HRV/RMSSD/SDNN/pNN50 (need beat-to-beat
  timing and independent reference validation), SpO₂ and blood pressure (no
  validated estimator here), and anemia image features (a separate,
  non-cardiovascular pathway). They are listed in `NOT_AGGREGATED` and have no
  aggregation path at all.

## Insufficient data

A session average is presented only when:

- at least `minAcceptedReadings` (5) readings were accepted **and**
- at least `minIndependentWindows` (2) of them do not overlap.

Otherwise the UI states **Insufficient data** with the specific reason ("Only 3
accepted readings…", "Only 1 independent window…", "No readings accepted yet (4
rejected…)") and never shows a number in the headline position. Statistics that do
exist (mean of 3 readings, say) remain visible in advanced details, labelled with
their verdict — the point is not to hide data, but not to present it as a result.

All thresholds live in `DEFAULT_CONFIG` and are overridable per collector.

## Exports

- `rsbvp_session_readings_<stamp>.csv` — one row per reading, accepted and rejected,
  with reason, quality score/verdict, sampling rate, window bounds, and timestamp.
  Missing values are empty cells, never placeholders.
- `rsbvp_session_summary_<stamp>.json` — schema `rsbvp.session-aggregate.v1`:
  per-metric statistics, per-estimator series, window counts, acceptance band,
  aggregation config, acquisition provenance, and the statistics caveats. The
  independence caveat travels *inside* the file so it cannot be quoted without it.

Both are local downloads. Nothing is uploaded. The existing RGB-trace and
window-analysis exports are unchanged.

## Interface

Main view: one large session average with its unit; accepted/rejected counts; the
observed acceptance percentage with a Good/Fair/Poor band derived **only** from that
percentage (explicitly not a confidence score); median and range; a chart of accepted
readings against the mean; expandable individual readings; and the live value kept
visually separate and labelled "this window".

Advanced details (collapsed): per-series verdicts, counts, independent windows, SD,
standard error, and the list of metrics that are deliberately not aggregated.

## Known limitations

1. The standard error assumes independent windows are exchangeable; drifting
   physiology within a session means they are not strictly, so it is a coarse
   indicator rather than a confidence interval.
2. Overlap is estimated from window bounds. When bounds are unavailable, the
   independence claim is dropped (`null`) rather than approximated.
3. The plausibility bands are hygiene filters, not clinical ranges; a genuine
   arrhythmia or an unusual resting rate outside them would be rejected.
4. A session average cannot correct systematic bias: if the estimator reads 5 BPM
   low, the session average reads 5 BPM low — more precisely.
5. Respiratory-rate aggregation is limited to windows where its estimator produced a
   value and the shared verdict passed; it is not an independent breathing
   measurement.
6. No real-camera session has been used to evaluate these thresholds (see
   `docs/SPRINT_12_EVIDENCE.md` for the evidence tiers).
