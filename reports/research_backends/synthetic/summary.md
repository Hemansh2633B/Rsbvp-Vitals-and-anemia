# RSBVP research backend benchmark

- Schema: `rsbvp.benchmark-summary.v1`
- Reference metrics authorized: YES — deterministic synthetic fixture (software verification only)
- Windowing: {'window_seconds': 12.0, 'step_seconds': 6.0}
- Passband (Hz): [0.7, 3.5]

> Synthetic or aggregate outputs in this file are software verification artifacts.
> They are not physiological validation, not clinical evidence, and not a ranking of medical devices.

## Inputs

| Recording | Participant | fs (Hz) | Dropped intervals |
|---|---|---|---|
| synthetic_70bpm | — | 30.000 | 0.0 |

## Backends

| Backend | Status | License | Latency (s) |
|---|---|---|---|
| rsbvp_native | completed | MIT | 0.594 |
| rsbvp_reference | completed | MIT | 0.738 |

## Availability and rejection accounting

| Backend:algorithm | Windows | With estimate | Availability | Rejected/unavailable |
|---|---|---|---|---|
| rsbvp_native:CHROM | 45 | 45 | 1.000 | 0 |
| rsbvp_native:GREEN | 45 | 45 | 1.000 | 0 |
| rsbvp_native:POS | 45 | 45 | 1.000 | 0 |
| rsbvp_reference:CHROM | 45 | 45 | 1.000 | 0 |
| rsbvp_reference:GREEN | 45 | 45 | 1.000 | 0 |
| rsbvp_reference:ICA | 45 | 45 | 1.000 | 0 |
| rsbvp_reference:PBV | 45 | 45 | 1.000 | 0 |
| rsbvp_reference:POS | 45 | 45 | 1.000 | 0 |

## Paired comparison (identical windows)

*Pooled descriptive statistics; participant-level metrics are primary. Overlapping windows are correlated.*

| Backend:algorithm | n | MAE | RMSE | Bias | LoA 95% | Pearson r |
|---|---|---|---|---|---|---|
| rsbvp_native:CHROM | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_native:GREEN | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_native:POS | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_reference:CHROM | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_reference:GREEN | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_reference:ICA | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_reference:PBV | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |
| rsbvp_reference:POS | 45 | 0.00 | 0.00 | 0.00 | 0.00 to 0.00 | — |

## Notes

- Identical recordings and identical time windows were used for every in-process backend.
- Native and reference backends share the same passband (0.7-3.5 Hz default) and HR estimator (hann-periodogram-v1); differences reflect the transform, not the estimator.
- Overlapping windows are correlated; pooled metrics are descriptive only. Prefer participant-level metrics and the participant bootstrap CI.
- Subprocess backends (rppg_toolbox, pyvhr) report aggregate records only and are excluded from window-level pairing statistics.
- Reference measurements were never passed to any backend; they were joined after prediction.
- Synthetic fixtures are software verification only; no physiological validation is claimed.
