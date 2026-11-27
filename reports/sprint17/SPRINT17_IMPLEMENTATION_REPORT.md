# Sprint 17 — reproducible research validation and performance analysis platform

**Status:** implemented and software-tested. **No real-world validation has been
performed, because no dataset with a synchronised independent reference exists in this
repository.** Every number in this document comes from deterministic synthetic
fixtures and is labelled as such.

Baseline: `main` @ `29e0f1c` (Sprint 16 merged).
Python suite: **657 passed** (up from 516; 141 new tests). Frontend: vitest **15 files /
295 tests**, `tsc` clean, lint **0 errors / 1 pre-existing warning**, production build
succeeds.

---

## 0. Delivery notes

**Branch name.** The sprint brief asks for `feature/sprint17-research-validation`.
This session is pinned to `arena/ae4b6f9b-rsbvp-vitals-and-anemia`, and the branch
cannot be renamed or recreated from here, so all work is committed there and the pull
request is opened against `main` from it. This is the same deviation disclosed in
Sprint 16 §0. Squash-merging produces a commit on `main` with no trace of the branch
name, so the artefact can be renamed if that matters.

**Not merged.** Per the brief, the pull request is left open for review.

## 1. What this sprint actually added

The mission was a *research platform*, not another dashboard. The deliverable is
therefore a set of modules under `research/validation/` that a researcher runs from a
command line, plus one document that explains how to use them honestly
(`docs/SPRINT_17_VALIDATION_GUIDE.md`).

| Module | Responsibility |
|---|---|
| `errors.py` | `InputFinding` (severity + code + source row) and `InputRejection` |
| `metric_rules.py` | The shared rule constants and duplicate identity, mirroring the TypeScript |
| `loader.py` | Parse the existing export; recompute acceptance; reject rather than repair |
| `reference.py` | Parse a reference CSV; intervals or samples; reject rather than clip |
| `alignment.py` | Time bases, clock offsets, timestamp pairing |
| `metrics.py` | Agreement, correlation, coverage, percentiles, bootstrap |
| `method_comparison.py` | Per-series evaluation, shared-subset comparison, session aggregation, outlier disclosure |
| `pipeline.py` | `evaluate_session`: the whole sequence, packaged as `EvaluationResult` |
| `plots.py` | Seven figures, each stamped with its n and its limitation |
| `report.py` | JSON + Markdown from one object, so they cannot disagree |
| `datasets.py` | Readiness audit with isolated adapters; downloads nothing |
| `cli.py` | `evaluate`, `check`, `readiness` with distinct exit codes |

**Reuse, not a duplicate pipeline.** The acceptance rule, duplicate identity, coverage
counting and outlier thresholds come from the Sprint 15/16 constants, mirrored in
`metric_rules.py` and asserted against the TypeScript by the existing parity tests. The
session-average analysis reuses the estimator theory from
`research/session/aggregation_analysis.py` (Sprint 16) rather than re-deriving it. No
existing test was modified: the 516 pre-existing tests still pass unchanged.

## 2. The design decisions that matter

### 2.1 The export's three time bases

`window_start_s` comes from `performance.now()` (page-relative), `session_elapsed_s`
from `acquisitionStart`, and `recorded_utc` from the wall clock. A CSV containing
`0.0, 10.0` cannot say which. Pairing against a capture-relative reference under the
wrong assumption produces errors that are almost entirely the offset, which would
report a working algorithm as badly inaccurate.

The platform therefore requires a declared `TimeBase` and an established offset. There
is no code path that defaults the offset to zero.

### 2.2 Offset derivation, and two wrong versions of it

`derive_offset` takes anchors — the same event seen by both clocks — and computes
`offset_i = session_i − reference_i` per anchor, requiring at least two and refusing a
disagreement above 1 s.

Two earlier implementations were **wrong and are recorded here so they are not
reintroduced**:

1. Scoring candidates by the spread of `reference − (anchor + offset)`. That quantity
   is algebraically invariant to the offset — a constant shift preserves the spread —
   so every candidate tied and the function returned `0.0` for any input while looking
   like a considered result.
2. Shifting the *displacements* between anchors. Same defect, same silent `0.0`.

A regression test asserts that two anchor sets differing by a constant produce offsets
differing by that constant, which both broken versions fail.

### 2.3 Correlation is not agreement

The fixtures include a method that reads **exactly 8 BPM high with Pearson r = 1.000**.
The report presents it as exactly that, in words, next to the numbers. This is the case
the platform exists to make visible.

### 2.4 Paired means by timestamp, never by row

A window is compared against the overlap-weighted mean of the reference intervals it
covers. The weight is `overlap_s(start, end)`, not interval duration: weighting by
duration lets the *reference file's granularity* choose the matched value.

A related rule that was tried and removed: requiring one reference interval to hold
≥60 % of a window before pairing. With a 10 s window over 2 s intervals every share is
0.2, so it excluded every window. Ambiguity is when the covered values *disagree*, which
is the variation test, not when the coverage is fine-grained.

### 2.5 Outliers are disclosed, never removed

`detect_outliers` flags a window only when it is beyond 2.5 robust SDs (MAD-based, so
the outliers do not inflate their own threshold) **and** more than 6 BPM from the
session-median error. Both conditions are needed: on a very tidy session, robust SDs
alone flag a 0.3 BPM difference.

Flagged ids are reported. **No statistic excludes them**, and a test asserts the
session mean is still pulled by a retained outlier. The median is reported alongside
precisely because it is not pulled.

### 2.6 Dataset adapters are isolated and refuse to guess

`research/validation/datasets.py` audits four datasets without downloading anything (a
test asserts no network import). A dataset is ready only when an operator supplies a
local root *and* its adapter verifies the layout. The three external adapters are
**refusing stubs**: given an unrecognised tree they return not-ready with the reason
and the top-level entries they saw. Guessing which column is the heart rate would
produce a confident wrong report, which is worse than an explicit blockage.

The dataset layer ends at validated `ReferenceTable` intervals. A test asserts that
`metrics.py`, `method_comparison.py`, `alignment.py`, `pipeline.py` and `metric_rules.py`
do not import the dataset layer, so a dataset quirk cannot change how an error is
computed.

## 3. Defects found and fixed during the sprint

These are the ones worth recording, because each would have produced a plausible wrong
answer rather than an error.

| # | Defect | Consequence if shipped |
|---|---|---|
| 1 | `load_reference` recorded `REJECT` findings for implausible values, overlapping intervals and too-short spans **without raising** | A caller could evaluate against a reference the loader itself had refused. Now any `REJECT` raises |
| 2 | The comparison dict was built from consensus series only | The report said "only one method series was paired" directly above a table listing ten scored series — every estimator was silently excluded |
| 3 | The shared-subset key included algorithm and ROI | Two different methods can never share such a key, so every comparison reported 0 shared windows and the verdict `insufficient_shared_observations`. Now keyed on the time interval |
| 4 | The duplicate fixture emitted its duplicate rows with an **empty value** | They were classified "valid verdict without an estimate" before reaching the duplicate check, so duplicate suppression was never exercised while the test that named it passed |
| 5 | The bootstrap interval had no accompanying note | A copied `mae_ci95_bpm` read as an interval about the method, when it only resamples overlapping windows. `mae_ci95_note` now travels with it |
| 6 | `DatasetStatus.blocker` kept the standing text when the dataset was ready | A caller reading the attribute (not `as_dict`) saw a dataset as simultaneously ready and blocked |
| 7 | Figures drew their synthetic banner as a floating annotation | It collided with the title it was warning about. Now it is the first line of the title, in red |
| 8 | Coverage-vs-error labels were drawn per point | Methods sharing a (coverage, MAE) pair produced an unreadable smear. Now clustered with one block per cluster |

None of these were caught by inspection alone; each was found by writing a test that
asserted the intended property rather than the current behaviour.

## 4. Evidence

### 4.1 The three oracles

Fixtures: 101 recorded windows each, every fifth rejected by the quality gates, 81
paired. Deterministic, no clock, no `random`, no network.

| Fixture | n | MAE | Bias | Pearson r | Session verdict |
|---|---|---|---|---|---|
| `good` | 81 | 0.76 | +0.31 | +0.980 | `averaging_helped` |
| `biased` | 81 | **8.00** | **+8.00** | **+1.000** | `averaging_did_not_help` |
| `drifting` | 81 | 3.04 | −0.04 | +1.000 | `averaging_may_increase_bias` |

The `biased` row is the platform's central demonstration: perfect correlation, 8 BPM
wrong. The `drifting` row is the second: a method with no bias overall whose error
ramps, where averaging is not neutral because the mean is weighted by how often each
period was analysed.

### 4.2 A committed example artefact

`reports/sprint17/fixture_evaluation/` holds a full run of the `good` fixture: the JSON,
the Markdown, and seven figures. It exists to show the output shape and to make the
report format reviewable without running anything. It is stamped
`SYNTHETIC TEST DATA — NOT VALIDATION` in the banner, in the figure titles and in the
`input_is_synthetic` field.

### 4.3 Test coverage by requirement

| Brief requirement | Tests |
|---|---|
| Export parsing and validation | `test_validation_loader.py` (30) |
| Reference loading, alignment, clock offsets | `test_validation_alignment.py` (31) |
| Metrics, Bland–Altman, coverage, insufficient n | `test_validation_metrics.py` (22) |
| Pipeline, comparison, session average, outliers, report consistency | `test_validation_pipeline.py` (40) |
| Dataset readiness and adapter isolation | `test_validation_datasets.py` (11) |
| CLI and exit codes | `test_validation_cli.py` (7) |

## 5. What this sprint does not establish

- **No accuracy claim of any kind.** There is no real export, no participant, no
  reference device recording. The fixtures prove the code computes what it says.
- **No dataset evidence.** rPPG-10, UBFC-rPPG, COHFACE and MMPD are all still
  unavailable; `docs/DATA_READINESS.md` records the blocker and the intake procedure
  for each. Nothing was downloaded and nothing was fabricated.
- **No clinical or physiological validation**, no blood pressure, no SpO₂, no HRV or
  RMSSD from an average heart rate.
- **No evidence that a phone measurement is accurate.** Offline dataset results, were
  they available, would describe that dataset's recordings, that reference device and
  those conditions.

The current standing of the whole project remains: **no HARDWARE-TESTED and no
PHYSIOLOGICALLY VALIDATED claims.**

## 6. Next actions

1. **Run one real session** through `docs/SPRINT_17_VALIDATION_GUIDE.md` §2. This is
   the only step that turns any of this into evidence, and it needs a reference device
   and a consented participant, not more code.
2. Obtain one external dataset lawfully and write its adapter (roughly one reviewed
   function each; see `docs/DATA_READINESS.md` §3).
3. Recalibrate `OUTLIER_*`, `DENSITY_RATIO_WARNING` and the acceptance bands against
   real exports. They are currently Sprint 15/16 constants with no real-data
   calibration, and the report says so.

## 7. Reproducing this document

```bash
.venv/bin/python -m pytest -q                     # 657 passed
.venv/bin/python -m research.validation readiness  # all datasets blocked, no downloads
.venv/bin/python -m research.validation evaluate \
  --readings tests/fixtures/validation/synthetic_session_good.csv \
  --summary  tests/fixtures/validation/synthetic_session_summary_good.json \
  --reference tests/fixtures/validation/synthetic_reference_intervals.csv \
  --time-base capture_start --offset 0 \
  --out reports/sprint17/fixture_evaluation \
  --stratum "synthetic fixture, no participant"
```
