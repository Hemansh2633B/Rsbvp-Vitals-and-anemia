# Session aggregation: why the headline statistic is what it is

**Scope.** This document answers one question with numbers: *should the session
average be the mean of all accepted readings, or the mean of the non-overlapping
subset used for uncertainty?* It records the comparison, the decision, and the
claims that are **not** made.

Everything here is produced by one script with a fixed seed, so the tables can be
regenerated and checked:

```bash
python research/session/aggregation_analysis.py            # table
python research/session/aggregation_analysis.py --json out.json
pytest -q tests/test_aggregation_analysis.py               # 14 methodology tests
```

Committed output: [`reports/session/aggregation_analysis.txt`](../reports/session/aggregation_analysis.txt)
and `.json`. Seed `20261126`, 10 s window, 0.5 s cadence. Two consecutive runs are
byte-identical.

---

## 1. The situation

The browser analyses a 10 s window and repeats every ~500 ms, so a one-minute
session yields roughly 120 accepted readings. Neighbouring readings share about
95 % of their signal. Two things follow, and they are often conflated:

1. **The readings are not independent observations.** Their lag-1 autocorrelation
   in a drifting session is 0.89–0.93 (§3).
2. **The mean of all readings is not the time-average of the underlying signal.**
   It is an average *per reading*, so a stretch that is analysed more often counts
   more.

The second is a real bias mechanism; the first affects any uncertainty statement
built on the readings. Neither is a reason to hide readings or to smooth the output.

## 2. Method

Six synthetic sessions with a known truth function:

| Scenario | What it exercises |
|---|---|
| `steady_60s` | constant truth, uniform cadence (baseline) |
| `drift_120s` | truth drifts linearly over 2 minutes |
| `rejected_gap` | a stretch of readings rejected, truth constant |
| `uneven_density` | one stretch analysed 8× more often, truth constant |
| `uneven_density_with_drift` | **both**: denser analysis *and* drift |
| `single_outlier` | one reading +60 BPM above the rest |

Two estimators are compared against the truth:

- **All-window mean** — arithmetic mean of every accepted reading (the headline).
- **Non-overlapping mean** — the maximal subset of readings whose windows do not
  overlap (the subset already used for uncertainty).

### The truth target matters

The target is the **time-weighted** average of the truth over the analysed span
(each reading contributes in proportion to the time it represents), not the average
of truth evaluated per reading. Averaging truth per reading would let the densely
analysed stretch define its own target and would therefore *manufacture* agreement
with the all-window mean. This was a bug in the first draft of the script and is now
pinned by `test_truth_is_time_weighted_not_reading_weighted`.

## 3. Results

| scenario | n | non-ovl | all-window | non-ovl | diff | \|err\| all | \|err\| nov | acf1 |
|---|---|---|---|---|---|---|---|---|
| steady_60s | 101 | 6 | 72.01 | 71.66 | 0.36 | 0.01 | 0.34 | −0.00 |
| drift_120s | 221 | 12 | 87.24 | 86.47 | 0.77 | 0.24 | 0.53 | 0.93 |
| rejected_gap | 121 | 7 | 68.05 | 67.35 | 0.70 | 0.05 | 0.65 | 0.04 |
| uneven_density | 101 | 9 | 68.01 | 67.53 | 0.49 | 0.01 | 0.47 | −0.00 |
| **uneven_density_with_drift** | 131 | 12 | **80.75** | **85.04** | **−4.29** | **4.15** | **0.14** | 0.89 |
| single_outlier | 101 | 6 | 75.01 | 74.74 | 0.27 | 0.01 | 0.26 | −0.00 |

Outlier injection (+60 BPM on one reading): all-window mean **75.60**, non-overlapping
**74.74** (0.86 apart); median **74.90** vs **74.65**.

### Reading the table

1. **A rejected gap is harmless.** Removing a stretch leaves the remaining time
   uniformly covered, so an equal-weight mean stays ~unbiased (error 0.05 BPM). This
   matters because the intuitive expectation is the opposite.
2. **Uneven density without drift is also harmless** (0.01 BPM): re-weighting a
   constant gives the constant.
3. **Uneven density *with* drift biases the all-window mean by ~4.3 BPM.** The extra
   analyses land in one phase, so that phase dominates the average.
4. **There, the non-overlapping mean is much better** (0.14 BPM) — but not because
   independence is magic. It is better because coarser sampling happened to cover
   the sparsely analysed phase too. In `rejected_gap` it is *worse* (0.65 vs 0.05)
   for the mirror reason: a lossy subset is a different sample and can miss a phase.
   **Non-overlapping is not automatically the more accurate estimator.**
5. **Autocorrelation is near zero when the truth is constant and 0.89–0.93 when it
   drifts.** Overlapping windows on a moving signal are near-duplicates.
6. **One wild reading shifts the mean ~3.4× more than the median.** Both are shown.

## 4. Decision

**The headline statistic stays the all-window mean.** Grounds:

- It is unbiased in the ordinary cases (uniform cadence, rejected gaps) and in
  constant-truth sessions with any density pattern.
- Its failure mode is *specific and detectable*: uneven density **and** drift.
- Replacing it with a non-overlapping mean would discard most readings, introduce a
  selection rule with its own failure mode (shown in row 3 above), and change the
  number the user sees without their knowing why.
- Silently swapping estimators to chase a better mean absolute error in one scenario
  is exactly the kind of tweak this project's rules forbid.

The honest remedy for a detectable condition is **detection and disclosure**:

- `density_ratio` = (reading count in the densest third of the session) ÷ (count in
  the sparsest third). `null` when fewer than 4 timed readings or zero span.
- `uneven_density` is `true` when the ratio exceeds `densityRatioWarning` (default
  **3**). The UI then says the average weights every accepted reading equally and
  that a stretch analysed more often therefore contributes more.
- The ratio **never** alters the mean. A regression test asserts the mean of
  `[70, 70, 80, 80, 80]` is exactly 76 with the warning on or off.

Threshold 3 is chosen for interpretability ("one stretch analysed three times as
often as another"), **not** calibrated on real sessions. It may need adjusting when
real exports exist; it is a disclosure threshold, so a wrong value costs a
misleading-by-omission note, never a wrong number.

## 5. What is explicitly not claimed

- **Non-overlapping ≠ independent.** Windows that do not overlap still share
  physiology and are strongly autocorrelated (acf1 up to 0.93). The non-overlapping
  subset exists to avoid counting near-duplicate readings twice in a spread estimate,
  not because those readings are exchangeable draws.
- **No confidence interval.** `standardError = sd / sqrt(n_independent)` is a
  standard error under an exchangeability assumption that overlapping, autocorrelated
  windows only approximate. The bootstrap in the analysis script resamples windows and
  is labelled a bootstrap; a test asserts the phrase "not a formal confidence
  interval" remains in the source.
- **No accuracy claim.** These are six synthetic scenarios. They describe how two
  estimators respond to chosen inputs. They say nothing about real cameras, skin,
  motion or physiology, and no hardware session has been run (see
  `docs/SPRINT_14_REPORT.md` §5).
- **No smoothing, no gate relaxation, no estimator pooling** was introduced, and none
  of the rejected readings were hidden: rejections are counted, displayed and
  exported with their reasons.
