# Sprint 14 — real-world validation, aggregation correctness and measurement reliability

**Date:** 2026-11-26 · **Baseline:** `main` @ `d50c617` (PR #14 merged) ·
**Branch:** `arena/ae4b6f9b-rsbvp-vitals-and-anemia`

This report records what was audited, what was found, what was changed and — just
as importantly — what was **not** done. No physical-camera session was performed
(no device was available in this environment); §5 explains what that means for the
claims this repository is allowed to make.

---

## 1. Audit of the merged Sprint 13 implementation

Five files were inspected against each other: `sessionAggregate.ts`,
`SessionResult.tsx`, `rppg_core/session.py`, `BrowserPulse.tsx`, `Live.tsx`.

### Defects found

| # | Severity | Defect | Consequence |
|---|---|---|---|
| 1 | **High** | `summarizeSession` set completion to `complete` when the accepted **count** reached `targetAcceptedReadings` (8), without consulting the aggregate verdict | The UI said *"Enough accepted readings for a session average; you can stop the camera"* while the aggregate was `insufficient`. Reproduced with 8 readings from a **single** window: `targetAcceptedReadings` is 8, so the trigger fired while `n_independent_accepted` was 1 (2 required) |
| 2 | **High** | Completion had no notion of capture lifecycle | The same readings produced "collecting" whether the camera was running or had stopped; a finished session could never show a final "insufficient" state, and an interruption was indistinguishable from slow progress |
| 3 | Medium | `'complete'` and a 3-state enum could not express the states the UI needs | Initialising, interrupted and completed were unrepresentable |
| 4 | Medium | Respiratory rate appeared in the same `presentable` list as heart rate | An experimental estimate inferred from pulse-interval variability sat beside the pulse value as though the two had comparable standing |
| 5 | Low | Completion text counted 8 target readings while the gate needed 5 | Confusing, and it masked defect #1 (the target looked like the requirement) |
| 6 | Low | No detection of uneven analysis density | The all-window mean silently over-weights a densely analysed stretch; the condition was invisible |

Browser/Python consistency was **otherwise sound**: the acceptance rules, statistics,
independence accounting and export field names already matched. New parity tests
(§4) now enforce that rather than assuming it.

### The defect reproduced

```
8 accepted readings, all one 10 s window, lifecycle reported before the fix:
  completion        : complete
  completion_reason : Enough accepted readings for a session average; you can stop the camera
  aggregate verdict : insufficient  (Only 1 independent window; at least 2 are needed)
```

After the fix, the same readings with the camera running:

```
  completion        : collecting
  completion_reason : Collecting: 8 accepted readings, but they overlap (1 independent window); keep capturing
```

---

## 2. Session-completion correctness

Completion is now a **six-state machine** derived from the readings *and* the
capture lifecycle, because the same readings mean different things while running and
after a stop.

| State | When | Invites a stop? |
|---|---|---|
| `idle` | no session started, no readings | no |
| `initialising` | capture running, no analysable window yet | no |
| `collecting` | readings exist, aggregate not yet available, still capturing | no |
| `insufficient` | capture finished without an available aggregate | **no** |
| `available` | aggregate available, still capturing | yes |
| `interrupted` | capture interrupted before the aggregate was available | no |

**The invariant, enforced by test:** a stop invitation may appear only when
`resultAvailable` is true, and `resultAvailable` is defined as the *heart-rate
aggregate verdict being `available`*. A count of accepted readings is progress,
never permission to stop.

The lifecycle is supplied by the caller (`'running' | 'stopped' | 'interrupted'`),
so it is explicit rather than inferred from timestamps. `BrowserPulse` derives it
from the acquisition track (an `error` track is an interruption, `idle` is stopped);
`Live` derives it from the socket state.

**No threshold was lowered.** The gates, plausibility bands and independence
requirement are unchanged; only the *reporting* was corrected.

---

## 3. Overlapping-window statistics

### The question

The headline statistic is the arithmetic mean of **all** accepted readings. Because
the browser re-analyses a 10 s window every 500 ms, neighbouring readings share ~95 %
of their signal. A defensible alternative is the mean over **non-overlapping**
windows — the same subset already used for uncertainty. Do they differ materially?

### Method

`research/session/aggregation_analysis.py` (reproducible: fixed seed 20261126,
deterministic byte-for-byte) simulates sliding-window sessions with a **known truth
function** and compares both estimators. Crucially, the target is the *time-averaged*
truth, not the mean of truth over readings — averaging per reading would let the
densely analysed stretch define its own target, which is the bias under test.

### Results (`reports/session/aggregation_analysis.txt`)

| Scenario | readings | non-overlapping | all-window | non-overlapping | difference | lag-1 ACF |
|---|---|---|---|---|---|---|
| steady_60s | 101 | 6 | 72.01 | 71.66 | 0.36 | −0.00 |
| drift_120s | 221 | 12 | 87.24 | 86.47 | 0.77 | 0.93 |
| rejected_gap | 121 | 7 | 68.05 | 67.35 | 0.70 | 0.04 |
| uneven_density | 101 | 9 | 68.01 | 67.53 | 0.49 | −0.00 |
| **uneven_density_with_drift** | 131 | 12 | **80.75** | **85.04** | **−4.29** | 0.89 |
| single_outlier | 101 | 6 | 75.01 | 74.74 | 0.27 | −0.00 |

### Findings

1. **A rejected gap does not bias the all-window mean.** The remaining time stays
   uniformly covered, so equal weight per reading remains ~unbiased (0.05 BPM error).
   This is worth recording because "gaps cause bias" is otherwise an easy assumption.
2. **Uneven analysis density combined with drift does.** When one stretch is
   analysed four times as often *and* the value drifts, the all-window mean is
   **4.3 BPM off** while the non-overlapping mean is 0.14 BPM off. Density, not
   overlap per se, is the mechanism.
3. **Lag-1 autocorrelation of readings is 0.89–0.93** in drifting sessions.
   Non-overlapping windows reduce but do **not** remove autocorrelation: they are
   non-overlapping, not statistically independent.
4. **A single wild reading moves the mean more than the median** (0.86 vs 0.25 BPM
   in the injected-outlier case), which is why both are displayed.

### Decision: the primary estimator does not change

The all-window mean stays the headline statistic. Reasons:

- In the common case (uniform cadence, or a rejected gap) it is unbiased; the
  biased case requires *both* uneven density *and* drift.
- Switching silently to a non-overlapping mean would discard most readings and
  introduce a different, undocumented selection rule.
- The honest fix for a condition that is detectable is to **detect and disclose**
  it, not to swap estimators behind the user's back.

So the implementation now computes a **density ratio** (densest third ÷ sparsest
third of the session) and, above `densityRatioWarning` (3×), shows a plain-language
note that the average gives every accepted reading equal weight. A test
(`does not change the mean: density is reported, never silently corrected`) fails if
a future change "fixes" density by quietly changing the statistic.

### What is explicitly not claimed

- The bootstrap interval over windows is **not** a confidence interval. The module
  says so, and a test asserts that wording is present.
- "Non-overlapping" ≠ "independent". Overlap factor and lag-1 autocorrelation are
  reported so the distinction is visible.
- All scenarios are synthetic. They describe what the estimators do to a given
  input; they say nothing about real skin, cameras or physiology.

---

## 4. Respiratory rate and experimental labelling

Respiratory rate is inferred from beat-to-beat pulse-interval variability
(respiratory sinus arrhythmia). It is **not** a direct breathing measurement, has no
independent reference validation in this project, and is confounded by motion and by
errors in the pulse estimate itself.

Changes:

- `MetricSpec` gained `primary` and `experimental` flags. Respiratory rate is
  `primary: false, experimental: true` in both languages.
- It is **removed from the headline list** and rendered in a separate
  "Experimental (not part of the session result)" block, with its note and an
  explicit statement that it is not included in the session average.
- The aggregate export carries `primary` and `experimental` per metric.
- The note text was rewritten to state the mechanism and the missing validation
  rather than the previous softer "experimental; not a direct breathing measurement".

No HRV/RMSSD, SpO₂, blood-pressure or haemoglobin aggregation path was added. The
`NOT_AGGREGATED` table still covers them.

---

## 5. Physical-camera validation — **NOT PERFORMED**

**No Android device, phone camera or physical webcam session was run.** The
environment had no camera hardware, and fabricating results is not an option.

What this means, stated plainly:

- There is **no** hardware-tested evidence for camera permission flow, front-camera
  selection, HTTPS operation, actual sampling rate, dropped/duplicate frames, ROI
  tracking, gate behaviour under real lighting/motion, interruption recovery, or
  session reset on a real device.
- The browser tests remain **software verification** with mocked media streams.
- The evidence tiers in `docs/IMPLEMENTATION_STATUS.md` are kept strictly separate
  for this reason.

Delivered instead:

- `docs/MANUAL_CAMERA_TESTS.md` — the protocol, extended with steps 11-18 covering
  session completion, the count-vs-availability trap, insufficient and interrupted
  final states, reset, the experimental block, the density warning and Android
  Chrome specifics. It continues to state that it has **not** been executed.
- `research/camera/sprint14_test_record_TEMPLATE.json` — a record template with
  `execution_status: "NOT EXECUTED"`, nulls everywhere a measurement belongs, and
  every scenario marked `executed: false`. It **fails** the existing validator on
  purpose (consent is false), and a test pins that: a placeholder cannot silently
  become evidence.
- Four new tests in `tests/test_camera_record.py` assert the template stays
  unexecuted, keeps every Sprint 14 field, and carries no participant payload.

**Unresolved blockers** (also listed in §9):

1. A physical Android device running Chrome on an HTTPS origin with a consenting
   operator — none was available in this environment.
2. A synchronized reference (CMS50D-class oximeter) for any accuracy claim, plus the
   evaluation protocol that already exists but has not been run on hardware.
3. Real-session exports to characterise fluctuation sources quantitatively (§6).

---

## 6. Measurement fluctuation: diagnosis from code, not from data

The task asks to diagnose whether instability is acquisition, signal processing,
gating or display. **Without exported real-session CSVs this cannot be measured**, and
none exist in this repository. What can be established from the code is the
following, and it is offered as a hypothesis list with the measurement that would
settle each:

| Candidate cause | Evidence available now | Measurement that would settle it |
|---|---|---|
| Display | **Confirmed as the dominant *perceived* factor.** Sprint 13 showed the newest window's value; successive windows legitimately differ by a few BPM. Aggregating accepted readings is what made the display stable | Session CSV before/after: standard deviation of the live value vs of the session mean |
| Acquisition (timing) | Windows with duplicate frames, stalls or gaps are rejected, not averaged; `captureIntegrity` reports rate, gaps, duplicates and jitter per window | Duplicate-frame % and largest gap per accepted window |
| Gating | Rejections are counted and shown; a rejection pattern concentrated in a lighting or motion phase is visible in the CSV `rejection_reason` column | Rejection reason histogram by session phase |
| Signal processing | GREEN/POS/CHROM disagreement is recorded per window (`per_estimator_bpm`) and gated by a 12 BPM agreement tolerance; ROI disagreement is in `roi_coverage` and per-estimator values | Spread of `per_estimator_bpm` across accepted windows |
| Physiological variation | Cannot be separated from estimator noise without a reference | Needs a synchronized reference device |

The honest conclusion: **the display factor is fixed and testable; the rest require
real-session data that does not exist yet.** No smoothing, gate relaxation or
cross-estimator averaging was added to compensate — doing so would hide exactly the
variability a reader needs to see.

---

## 7. UI and documentation

- **Mobile layout:** at ≤480 px the headline shrinks to 2.4 rem, the metric and
  quality grids stack to two columns, secondary lines stack vertically, export
  buttons go full width, and the non-essential elapsed-seconds column is hidden.
  The headline (one value, unit, acceptance counts, acceptance %) is above the fold;
  diagnostics stay collapsed.
- **README** reconciled against the actual implementation: it now states explicitly
  that the **browser** pathway uses MediaPipe Face Landmarker landmark polygons and
  the **Python** pathway uses an OpenCV Haar-cascade face box with a fixed central
  crop (a heuristic, not landmark segmentation), and that these are two different
  ROI methods.
- **IMPLEMENTATION_STATUS** updated to baseline `d50c617` with a Sprint 14 block and
  an explicit evidence-tier legend (implemented / software-tested / synthetic-tested /
  hardware-tested / physiologically validated), marking the last two as absent.
- **docs/SESSION_AGGREGATION.md** updated with the state machine, the density
  reporting, the estimator comparison and its results, and the strengthened
  limitation list.

---

## 8. Testing

| Suite | Result |
|---|---|
| `python -m pytest -q` | **483 passed** (41.6 s) |
| `npm test` | **11 files, 144 passed** |
| `npm run build` | `tsc -b` clean, vite build ok |
| `npm run lint` | **0 errors, 1 warning** (pre-existing `exhaustive-deps`) |

New coverage in this sprint:

- **Session-completion regression** (`sessionAggregate.test.ts`, `test_session_aggregation.py`): the exact Sprint 13 defect — 8 accepted readings from one window must never invite a stop; all six states reached and distinct; an invariant sweep over 10 lifecycle/reading combinations asserting a stop invitation appears only with an available aggregate; unknown lifecycle rejected.
- **Overlapping-window statistics** (`test_aggregation_analysis.py`, 14 tests): non-overlapping selection, time-weighted truth definition, gap-does-not-bias, density-with-drift-does-bias, autocorrelation reporting, outlier sensitivity, determinism, and a guard that the bootstrap interval is never renamed a confidence interval.
- **Browser/Python parity** (`sessionParity.test.ts` + `test_session_parity.py` + `tests/fixtures/session_aggregation_parity.json`, 11 shared cases): both languages assert the same expected values from the same fixture, covering all seven states, overlap, mixed verdicts, rejections and uneven density. A rule change in either language fails a test.
- **Density accounting** in both languages, including "reported, never silently corrected".
- **Export schema**: `experimental`/`primary`, `result_available`, `density_ratio`, `uneven_density` fields.

All of it is synthetic or mocked. **No test in this sprint constitutes physiological
or hardware validation.**

---

## 9. Unresolved validation blockers

1. **No physical-camera evidence** (see §5): every capture-related claim remains
   software-tested only.
2. **No real-session dataset** for the fluctuation diagnosis in §6.
3. **Respiratory rate has no reference validation.** It stays experimental and out of
   the headline; validating it needs capnography or a belt, which is not available.
4. **The density warning is a heuristic**, threshold 3×, chosen for interpretability
   (one stretch analysed three times as often as another) and **not** calibrated on
   real sessions. The analysis shows density *can* bias the mean by ~4 BPM; it does
   not establish how often that occurs in practice.
5. **No confidence interval is claimed.** The window bootstrap is a bootstrap; the
   exchangeability assumption is only approximate under autocorrelated physiology.
6. **rPPG-10 accuracy numbers are unchanged** from Sprint 11b; nothing in this sprint
   re-ran or re-tuned them.
7. **Anemia remains unavailable**: no model, no dataset, no Hb output. The image
   pathway is untouched by this sprint and remains separate from the cardiovascular
   metrics.
