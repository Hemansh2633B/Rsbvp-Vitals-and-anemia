# RSBVP validation guide

How to take a real RSBVP session export and a synchronised independent reference, and
produce an evaluation you could defend to someone who does not trust it.

The platform is `research/validation/`. It is deliberately **separate from the
application**: nothing here runs on the measurement screen, and no output of this
code is shown to a user taking a measurement.

---

## 0. The one thing that goes wrong

Almost every failed validation is an input problem, and almost every input problem
is synchronisation. The export mixes **three time bases**:

| Column | Measured from | Drifts against the reference? |
|---|---|---|
| `window_start_s` / `window_end_s` | `performance.now()`, i.e. page-relative | Resets on reload; not comparable across sessions |
| `session_elapsed_s` | the moment acquisition started | Stable, but starts at 0 for the session |
| `recorded_utc` | wall clock | Stable, but subject to clock changes |

A CSV containing `0.0, 10.0` cannot tell you which of these it means. Pairing it
against a capture-relative reference under the wrong assumption produces errors that
are *almost entirely the offset*: a study can look like a 12 BPM error when the
algorithm is fine.

So the platform refuses to guess. You must state the time base, and if it is not
zero you must establish the offset from something independent.

## 1. Prepare the inputs

### 1.1 Session export

Take the app's existing export, unchanged:

- `rsbvp_session_readings_<UTC>.csv` — one row per window per algorithm per ROI
- `rsbvp_session_summary_<UTC>.json` — the session aggregate (`rsbvp.session-aggregate.v1`)

Nothing needs reformatting. See [`docs/EXPORT_SCHEMA.md`](EXPORT_SCHEMA.md) §4.

### 1.2 Reference

A CSV in one of two layouts:

```csv
start_s,end_s,bpm
0,10,68
10,20,69
```

```csv
t_s,bpm
0,68
1,69
2,70
```

The interval layout is preferred: it says what the reference actually measured. The
sample layout is accepted and converted to piecewise-constant intervals (each value
holds until the next sample), and that conversion is recorded in the report as a
finding, because it is a modelling choice and not a fact.

Requirements the loader enforces, all of which reject the file rather than repair it:

- values inside 20–250 BPM — a value outside is a unit error, not a heart rate
- intervals that do not overlap — two candidate values for one moment makes the pairing arbitrary
- at least 5 s of span
- increasing sample times

Gaps are allowed but disclosed: windows falling in a gap are reported as unmatched,
never dropped quietly.

## 2. Establish the time base and the offset

Pick the time base that describes what `window_start_s` is measured from:

```bash
--time-base capture_start | page_load | reference_clock
```

- `capture_start` — `window_start_s` counts from the moment acquisition began. Use
  `--offset 0` if the reference device was started at the same moment.
- `page_load` — `window_start_s` counts from page load. You need an offset.
- `reference_clock` — `window_start_s` is already on the reference device's clock.
  A supplied offset is ignored, and that fact is recorded.

For `page_load`, supply **anchors**: moments you observed directly, given as
`session_s,reference_s`.

```bash
--anchors 1000.0,0.0 --anchors 1005.0,5.0 --anchors 1010.0,10.0
```

Each anchor is the *same event seen by both clocks*. `derive_offset` computes
`offset_i = session_i − reference_i` for every anchor, and:

- requires at least **two** anchors (one cannot distinguish an offset from a mistake)
- refuses when the anchors disagree by more than 1 s, because that means the clocks
  drifted or an anchor was misread — and in that case no single constant offset fits
- reports the mean and the per-anchor residuals

You can also pass the offset directly with `--offset`. Either way it is recorded in
the report; there is no path where zero is assumed.

## 3. Check before you evaluate

```bash
.venv/bin/python -m research.validation check \
  --readings exports/rsbvp_session_readings_2026-11-27T101500Z.csv \
  --summary  exports/rsbvp_session_summary_2026-11-27T101500Z.json \
  --reference reference.csv \
  --time-base capture_start --offset 0
```

`check` validates both files, derives the offset, aligns the windows, and prints the
coverage and every finding — without writing a report. Most input problems are found
here.

Exit codes: `0` fine, `2` input rejected (each finding printed), `3` insufficient
evidence.

A rejection looks like this and names the decision that was refused:

```
INPUT REJECTED — no evaluation was produced.
  reject time_base_undeclared: the session's time base is not declared. …
  reject no_paired_observations: no window estimate could be paired with a reference value. …
```

Two different failures are worth distinguishing:

- **excluded** — the window is outside the reference span, too short, or the reference
  varied across it. For an offset error this happens to *every* window, which is how
  you recognise it.
- **unmatched** — the window is inside the reference span but in a gap. A few of these
  are normal.

## 4. Run the evaluation

```bash
.venv/bin/python -m research.validation evaluate \
  --readings … --summary … --reference … \
  --time-base capture_start --offset 0 \
  --out reports/validation
```

Outputs:

| File | Contents |
|---|---|
| `validation.json` | `rsbvp.validation-results.v1` — everything below, machine-readable |
| `validation.md` | the same numbers, with their limits, in prose |
| `plots/*.png` | seven figures, each stamped with its n and its limitation |

The Markdown is generated from the same object as the JSON, and a test asserts they
agree, because a report that contradicts its own machine-readable output is worse than
no report.

## 5. Reading the output

### 5.1 Correlation is not agreement

Always read the bias and the limits of agreement beside `r`. The platform's own
fixtures demonstrate the failure mode: a method that reads **exactly 8 BPM high** with
a **Pearson r of 1.000**. Correlation is invariant to offset and scale, so a perfectly
consistent method can be perfectly wrong. The report says this in words next to the
number, not in a footnote.

### 5.2 Every number has an n

A cell with an MAE and no count is a defect. If there are fewer than 3 paired windows
nothing is reported at all — the report says **insufficient evidence** and names the
shortfall. Limits of agreement need 5, because they are a ±1.96 SD construct and an SD
over 4 points is not one.

### 5.3 Coverage sits beside accuracy

A small MAE over 12 paired windows out of 300 recorded describes those 12 windows.
The coverage block reports, for each stage: recorded → accepted → paired →
independent (non-overlapping). Windows are ~10 s wide and emitted every 0.5 s, so
neighbouring windows share almost all their samples. The independent count is the one
that matters for "how much evidence is this", and it is always smaller.

### 5.4 Algorithms are not participants

Four algorithms and three ROIs on one session is **one session**, not twelve studies
and not twelve people. The comparison section:

- compares two methods only on the windows **both** could score (a shared subset), so
  a method that only answers when the signal is easy cannot win on a favourable subset;
- flags `favourable_subset` when the shared overlap falls below 70 % of the smaller
  subset;
- never counts a method as an independent observation in any interval.

### 5.5 The session average is a question, not an assumption

The platform compares:

- the individual accepted windows,
- the session **mean**,
- the session **median**,
- against a **duration-weighted** reference for the session interval — so a stretch
  that was analysed more often cannot shift the comparison by itself.

Verdicts: `averaging_helped`, `averaging_did_not_help`,
`averaging_may_increase_bias`, `indeterminate`. Averaging removes zero-mean window
noise; it cannot remove a systematic offset, and with a drifting error it can make
things **worse**, because the mean is weighted by how often each period was analysed.
The drifting fixture is the worked example.

### 5.6 Outliers are disclosed, never removed

`detect_outliers` flags windows whose error is beyond 2.5 robust SDs (from the MAD, so
the outliers do not inflate the threshold) **and** more than 6 BPM from the session's
median error. Both conditions are required: a very tidy session would otherwise flag a
0.3 BPM difference.

Flagged ids are reported. **No statistic excludes them.** The median is reported
beside the mean precisely because it is not pulled by them; if the two disagree
sharply, that is the signal to go and look at the flagged windows yourself.

### 5.7 Missing metadata is `unknown`

Device, browser, resolution, frame rate, lighting and motion are taken from the export
when present and labelled `unknown` when not. They are never inferred from the
estimated BPM. No participant-identifiable information is written: stratification by
participant uses the export's own id, and the report says so.

## 6. What the output will *not* support

The report carries these limits in its own text, because the numbers are what get
copied out:

- It describes the paired windows of **this session**. It is not a claim about RSBVP
  in general.
- It is **not** a clinical or physiological validation. No blood pressure, no SpO₂, no
  HRV or RMSSD derived from an average heart rate.
- It is **not** evidence that a phone measurement is accurate.
- Overlapping windows are not independent observations, and the intervals labelled
  "bootstrap (windows)" are marked optimistic for that reason. A participant-level
  interval needs several participants, not several windows.
- A synthetic fixture proves the **code** works. It proves nothing about performance,
  and every artefact generated from one is stamped
  `SYNTHETIC TEST DATA — NOT VALIDATION`.

## 7. Bringing in an external dataset

See [`docs/DATA_READINESS.md`](DATA_READINESS.md). The short version: obtain it
lawfully, keep it outside the repository, point the environment variable at it, and
write a reviewed adapter. The dataset layer ends at validated reference intervals;
the metrics code cannot tell which dataset an interval came from, and a test enforces
that.

## 8. Adding a test fixture

Fixtures live in `tests/fixtures/validation/` and are generated by
`tests/fixtures/generate_validation_fixtures.py`. Every file is named `synthetic_*`
and the directory README states what it is not. Keep generation deterministic — no
`random`, no clock, no network — so that a failure is reproducible.

Two cautions learned the hard way:

- A fixture that does not exercise the code path it is named for is worse than no
  fixture. The duplicate fixture originally emitted its duplicate rows with an empty
  value, so they were classified "valid verdict without an estimate" and duplicate
  suppression was never reached.
- Fixtures must be *internally* consistent. They are validated by the same loader as
  real input, including the acceptance-mismatch check.

## 9. Command reference

```bash
# full evaluation + report + figures
python -m research.validation evaluate --readings R.csv --summary S.json \
  --reference REF.csv --time-base capture_start --offset 0 --out reports/validation

# validation and alignment only
python -m research.validation check --readings R.csv --reference REF.csv \
  --time-base page_load --anchors 1000,0 --anchors 1005,5

# dataset availability, no downloads
python -m research.validation readiness
```

Useful options: `--min-overlap` (default 0.5), `--min-window-s` (4.0),
`--from-s` / `--to-s` (restrict the evaluated interval), `--stem` (output filename),
`--stratum` and `--notes` (free-text provenance recorded in the report).
