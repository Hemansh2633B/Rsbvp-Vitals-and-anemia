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

### Duplicate windows are not new observations

Sliding-window analysis re-analyses every 500 ms over a 10 s window, so the same
underlying moment can reach the collector more than once — a re-delivered worker
result, a retried frame, a resume that replays a window. Counting it twice would
give one moment two votes in the mean, the median and every count on screen.

A reading is a **duplicate** when its metric, algorithm and window bounds match one
already recorded (`windowKey`). It is:

- **recorded** — the history stays complete, and the CSV includes the row;
- **refused** — `final_rejection_reason = "duplicate_window"`;
- **counted separately** — `n_duplicate_windows`, never inside `n_rejected`.

That last point matters for honesty: "the signal was bad" and "this window was
already counted" are different messages and must not be added together. The
interface shows a *Repeated* figure beside *Accepted* and *Rejected*.

Windows with **unknown bounds are never treated as duplicates.** "I do not know the
window" is not evidence that it repeats one. Suppression can be disabled
(`suppressDuplicateWindows` / `suppress_duplicate_windows`) for diagnostics; doing
so changes nothing else.

### Outliers are flagged, never removed

A reading may not be deleted for disagreeing with the others. Silently trimming it
would hide exactly the disagreement a reader most needs to know about, and with
autocorrelated windows it would bias the result toward whatever the survivors
happened to say.

Instead, each accepted reading is compared against the **other** accepted readings
(leave-one-out):

- centre = mean of the others, spread = sample SD of the others;
- a reading is flagged when it is more than `outlierSdThreshold` (2.5) spreads from
  that centre **and** at least `outlierMinDeviation` (6 BPM, 3 br/min) away from it.

Two details, both learned from tests rather than assumed:

1. **Leave-one-out is required.** Comparing a reading with an SD that includes it
   lets a wild value inflate the very spread it is judged against. In
   `[70, 71, 72, 71, 70, 155]` the naive limit is 2.5 × 34.4 = 86 BPM, so 155 passes
   unremarked. Leave-one-out gives a limit of ~2.5 around ~70.8 and catches it.
2. **A materiality floor is required.** With six windows agreeing to within 1 BPM, a
   1.4 BPM difference is statistically "far" and would be flagged on every steady
   session. A reading must be *both* statistically unusual and materially different.

Flagged readings are **included in every statistic**. The flags drive a disclosure
in the UI and `flagged_outliers` / `flagged_outlier_ids` in the export, which is why
the median is shown beside the mean.

### Variability warning

`variable` is true when the spread of accepted readings is at or above
`variabilitySdWarning` (8 BPM). It is expressed in the metric's own unit so it is
interpretable, and it **never changes a number** — it only decides whether the user
sees "Your readings varied during this session. Consider repeating the measurement
under steady conditions."

### Mean versus median

The headline is the **arithmetic mean of accepted readings**, because a user asking
for "my average" is asking for a mean, and because it is unbiased under uniform
cadence and under constant truth at any analysis density (see
`AGGREGATION_ANALYSIS.md`). The median is shown beside it because it is far less
sensitive to a single unusual reading — in `[70, 71, 72, 71, 70, 155]` the mean is
84.8 and the median is 71. Showing both is the disclosure that makes flagging
sufficient: the reader can see the disagreement's effect for themselves.

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

## Session completion states

Completion is derived from the **aggregate's availability**, never from a count of
accepted readings. A session can accumulate many readings and still have no result,
because those readings may all come from the same window. The state machine takes
the readings *and* the capture lifecycle (`running` / `stopped` / `interrupted`):

| State | Condition | Copy | Stop invited? |
|---|---|---|---|
| `idle` | no session, no readings | "No session yet: press Start…" | no |
| `initialising` | running, no analysable window yet | "Waiting for the first analysable window" | no |
| `collecting` | running, aggregate not available | "Collecting: N of 5 accepted readings" / "…they overlap (1 independent window); keep capturing" | no |
| `insufficient` | stopped, aggregate not available | "Insufficient data: N accepted readings…" | **no** |
| `available` | running, aggregate available | "Enough independent readings…; you can stop the camera" | yes |
| `interrupted` | interrupted before the aggregate was available | "Capture interrupted with N accepted readings…" | no |
| `completed` | stopped, aggregate available | "Session complete: N accepted readings" | n/a |

**Invariant:** a stop invitation may appear only when `resultAvailable` is true,
which is exactly the heart-rate aggregate verdict being `available`. This is
enforced by a sweep test over lifecycle/reading combinations and mirrored in both
languages (`docs/SPRINT_14_REPORT.md` §2 describes the defect it fixes).

A session average is presented only when:

- at least `minAcceptedReadings` (5) readings were accepted **and**
- at least `minIndependentWindows` (2) of them do not overlap.

Otherwise the UI states **Insufficient data** with the specific reason ("Only 3
accepted readings…", "Only 1 independent window…", "0 of 3 readings passed the
quality checks…") and never shows a number in the headline position. Statistics that
do exist (mean of 3 readings, say) remain visible in advanced details, labelled with
their verdict — the point is not to hide data, but not to present it as a result.

All thresholds live in `DEFAULT_CONFIG` and are overridable per collector. None of
them was lowered in Sprint 14; only the reporting was corrected.

## Experimental metrics

`METRICS[...]` carries `primary` and `experimental`. Heart rate is primary.
Respiratory rate is experimental: it is inferred from beat-to-beat pulse-interval
variability, is not a direct breathing measurement, and has no independent reference
validation here. It is therefore rendered in a separate "Experimental (not part of
the session result)" block, is excluded from the session average, and is flagged in
the export (`primary: false, experimental: true`). The browser pathway commonly has
no respiratory estimate at all, in which case the block states that it was not
reported and why.

## Analysis density

The headline mean weights every accepted reading equally, so a stretch that is
analysed more often contributes more. That is only material when density is uneven
**and** the value drifts; see [the aggregation analysis](AGGREGATION_ANALYSIS.md) for
the comparison of all-window vs non-overlapping means and why the headline statistic
is unchanged.

- `density_ratio` = (count in the densest third of the session) / (count in the
  sparsest third); `null` when there are fewer than 4 timed readings or zero span.
- `uneven_density` is `true` above `densityRatioWarning` (default 3).
- The ratio is **reported, never applied**: it does not alter the mean, does not
  reweight readings and does not drop any. A regression test asserts this.

## Exports

- `rsbvp_session_readings_<stamp>.csv` — one row per reading, accepted and rejected,
  with reason, quality score/verdict, sampling rate, window bounds, and timestamp.
  Missing values are empty cells, never placeholders.
- `rsbvp_session_summary_<stamp>.json` — schema `rsbvp.session-aggregate.v1`:
  per-metric statistics, per-estimator series, window counts, acceptance band,
  aggregation config, acquisition provenance, and the statistics caveats. The
  independence caveat travels *inside* the file so it cannot be quoted without it.
  Sprint 14 added (additively, so existing readers keep working): top-level
  `completion_state`, `result_available`, `density_ratio`, `uneven_density`; per
  aggregate `primary` and `experimental`; config `density_ratio_warning`.

Both are local downloads. Nothing is uploaded. The existing RGB-trace and
window-analysis exports are unchanged.

## Interface

Main view (mobile first: one value above the fold, diagnostics collapsed):

- one large session average with its unit, plus the completion-state chip;
- accepted / rejected counts and the observed acceptance percentage with a
  Good/Fair/Poor band derived **only** from that percentage (explicitly not a
  confidence score);
- median and range; a chart of accepted readings against the mean;
- a plain-language note on what the number does and does not mean;
- the density warning, shown only when analysis density is uneven;
- the live value kept visually separate and labelled "this window";
- expandable individual readings (elapsed seconds hidden below 480 px width).

A separate dashed block lists **experimental** metrics, headed "Experimental (not
part of the session result)", with the reason each is unvalidated and any metric that
was simply not reported.

Advanced details (collapsed): per-series verdicts, counts, independent windows, SD,
standard error, and the list of metrics that are deliberately not aggregated.

## Minimum eligible data

A session result requires **all** of:

| Requirement | Default | Why |
|---|---|---|
| Accepted readings | ≥ 5 | each already passed the spectral, agreement, coverage and timing gates; a lower bar buys speed, not accuracy |
| Independent (non-overlapping) windows | ≥ 2 | a session average must never be one moment re-counted |
| Headline metric | heart rate | respiratory rate stays in advanced details (see `METRICS`) |

Below either threshold the aggregate verdict is `insufficient` and **no number is
displayed as the result** — the mean and median remain visible in the diagnostics,
but are never presented as the session answer. Duplicate windows do not count toward
either threshold.

## Known limitations

1. The standard error assumes independent windows are exchangeable; drifting
   physiology within a session means they are not strictly, and readings from
   overlapping windows are strongly autocorrelated (lag-1 up to 0.93 in the
   analysis fixtures). It is a coarse indicator, **not a confidence interval**, and
   no formal interval is claimed.
2. Overlap is estimated from window bounds. When bounds are unavailable, the
   independence claim is dropped (`null`) rather than approximated.
3. The plausibility bands are hygiene filters, not clinical ranges; a genuine
   arrhythmia or an unusual resting rate outside them would be rejected.
4. A session average cannot correct systematic bias: if the estimator reads 5 BPM
   low, the session average reads 5 BPM low — more precisely.
5. Respiratory rate is experimental and excluded from the headline result. It is
   inferred from pulse-interval variability, not measured from breathing, and has no
   reference validation here.
6. No real-camera session has been used to evaluate these thresholds. Sprint 14
   performed no hardware testing; see `docs/SPRINT_14_REPORT.md` §5 and the evidence
   tiers in `docs/IMPLEMENTATION_STATUS.md`.
7. The density warning threshold (3x) is a disclosure heuristic chosen for
   interpretability, not calibrated on real sessions.
