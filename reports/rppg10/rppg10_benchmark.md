# rPPG-10 benchmark report

**Status:** RUN

Protocol: `rsbvp.rppg10-protocol.v1` (frozen 2026-11-25)

## How to read these numbers (read this first)

Two things must be said together, or the table below will be misread:

1. **The per-ROI table is availability-conditional.** Those numbers describe only the windows whose signal passed the frozen quality gates. Check the *usable coverage* column and the participation table: if coverage is low, the errors describe the easiest windows, not the method's accuracy.
2. **The gates-OFF sensitivity analysis (bottom) is what the protocol would report without quality gating on nearly every window.** For an implementation check, compare that row with the provider's own published baseline (GREEN MAE 7.57 ± 0.66 BPM using a combined forehead+both-cheek ROI) — not with the gated row.

Neither row is a clinical result, and neither may be quoted without the limitations at the end.

## Per-ROI results

| ROI | Estimator | n pairs | MAE (BPM) | RMSE (BPM) | Bias (BPM) | LoA 95% | Pearson r | usable coverage | participants | MAE CI95 (BPM) |
|---|---|---|---|---|---|---|---|---|---|---|
| forehead | green | 124 | 0.95 | 1.36 | -0.33 | -2.92 to 2.27 | 0.99 | 25.1% | 16 | 0.73 to 1.18 |
| forehead | pos | 53 | 1.22 | 3.18 | -0.53 | -6.73 to 5.68 | 0.85 | 10.7% | 9 | 0.65 to 7.84 |
| forehead | chrom | 31 | 0.84 | 1.15 | -0.14 | -2.41 to 2.13 | 0.98 | 6.3% | 7 | 0.63 to 1.32 |
| right_cheek | green | 54 | 0.81 | 1.06 | -0.33 | -2.33 to 1.67 | 1.00 | 10.9% | 11 | 0.49 to 0.98 |
| right_cheek | pos | 7 | 1.30 | 1.56 | -0.06 | -3.37 to 3.25 | 0.94 | 1.4% | 2 | 1.12 to 2.37 |
| right_cheek | chrom | 1 | 20.27 | 20.27 | -20.27 | — | — | 0.2% | 1 | — |
| left_cheek | green | 62 | 0.85 | 1.08 | -0.34 | -2.36 to 1.68 | 0.99 | 12.6% | 11 | 0.63 to 1.06 |
| left_cheek | pos | 15 | 0.71 | 0.96 | 0.08 | -1.87 to 2.03 | 0.99 | 3.0% | 5 | 0.30 to 0.73 |
| left_cheek | chrom | 6 | 1.64 | 2.74 | -1.31 | -6.49 to 3.87 | 0.94 | 1.2% | 6 | 0.39 to 3.63 |

## Participant exclusions

| Subject | Reason | Provider documentation | Evidence found on disk |
|---|---|---|---|
| 4 | explicit_exclusion_by_caller | article §4.7 states Subject_4 was excluded before release for persistent tracking failure and non-physiological ECG peaks | all ROI videos are 0 bytes (empty placeholder files) |

## Coverage and rejection accounting

See the JSON report for per-window quality tokens; rejected windows are listed, not hidden.

## Participation (who the numbers actually describe)

| Estimator | Participants contributing any pair | Participants with no usable window |
|---|---|---|
| green | 18 of 26 | 2, 5, 9, 18, 21, 22, 23, 24 |
| pos | 9 of 26 | 2, 3, 5, 6, 8, 9, 10, 11, 12, 14, 18, 20, 22, 23, 24, 26, 27 |
| chrom | 9 of 26 | 2, 5, 6, 7, 8, 9, 10, 11, 12, 17, 18, 20, 21, 22, 23, 24, 27 |

## Selection-bias diagnostic (accepted vs rejected windows)

If the mean reference HR of accepted windows differs materially from rejected ones, the error statistics describe only the easier part of the dataset.

| ROI \| estimator | accepted | rejected | accepted ref HR | rejected ref HR | difference |
|---|---|---|---|---|---|
| forehead|green | 124 | 353 | 67.0 | 82.6 | -15.6 |
| forehead|pos | 53 | 424 | 61.3 | 80.7 | -19.4 |
| forehead|chrom | 31 | 446 | 60.1 | 79.8 | -19.7 |
| right_cheek|green | 54 | 423 | 67.1 | 80.0 | -12.8 |
| right_cheek|pos | 7 | 470 | 55.8 | 78.9 | -23.1 |
| right_cheek|chrom | 1 | 476 | 80.3 | 78.5 | +1.7 |
| left_cheek|green | 62 | 415 | 65.7 | 80.4 | -14.8 |
| left_cheek|pos | 15 | 462 | 59.9 | 79.1 | -19.2 |
| left_cheek|chrom | 6 | 471 | 66.6 | 78.7 | -12.0 |

## Provider-comparable view — combined ROI, gates OFF (not a result)

Descriptive only. 'ungated_combined_roi' averages the three ROI estimates of the same window (provider-comparable: their baseline uses a combined ROI over non-overlapping 30 s windows); 'gated_combined_roi' uses only windows that survived the frozen quality gates. Neither is a validation result and neither may be quoted as this project's accuracy.

| Estimator | n windows | pooled MAE (BPM) | RMSE (BPM) | bias (BPM) | median participant MAE (BPM) | participants |
|---|---|---|---|---|---|---|
| green | 477 | 8.03 | 12.97 | -6.47 | 5.23 | 26 |
| pos | 477 | 11.29 | 15.42 | -7.65 | 9.82 | 26 |
| chrom | 477 | 13.19 | 17.13 | -6.93 | 12.23 | 26 |

## Descriptive sensitivity analysis — gates OFF (not a result)

Descriptive sensitivity analysis computed after the frozen protocol ran: these are the same spectral peaks WITHOUT the quality gates. They are not rPPG-10 results and must not be quoted as such; compare them with the gated numbers to see what the gates remove.

| ROI | estimator | n pairs | MAE (BPM) | RMSE (BPM) | bias (BPM) |
|---|---|---|---|---|---|
| forehead | green | 477 | 7.50 | 14.54 | -5.66 |
| forehead | pos | 477 | 11.88 | 18.45 | -8.99 |
| forehead | chrom | 477 | 16.18 | 23.45 | -7.93 |
| right_cheek | green | 477 | 10.51 | 17.02 | -6.89 |
| right_cheek | pos | 477 | 15.66 | 21.96 | -6.18 |
| right_cheek | chrom | 477 | 17.01 | 23.05 | -5.53 |
| left_cheek | green | 477 | 10.60 | 16.99 | -6.85 |
| left_cheek | pos | 477 | 14.13 | 20.34 | -7.78 |
| left_cheek | chrom | 477 | 16.90 | 22.95 | -7.32 |

## Interpretation limits (binding)

- 26 participants (Subject_4 excluded by the provider), predominantly young Portuguese university students; Fitzpatrick I–IV only (no V/VI). No generalisation beyond this population.
- Single-site acquisition: one room, natural indoor daylight, 10:00–16:00, one webcam type, participants seated and asked to stay still. No claim about other lighting, motion or devices.
- 64×64 ROI crops with consumer compression: fine pulsatile detail is limited by the provider's anonymisation pipeline, not by this implementation.
- Video/ECG synchronisation is manual with a documented uncertainty of up to ±500 ms; this protocol therefore evaluates 30 s windows, not sub-second timing.
- The ECG reference is a pulse-rate reference derived from R-peaks. Agreement with it is NOT validation of pulse-rate variability, HRV, or any clinical parameter.
- Non-commercial licence (CC BY-NC-SA 4.0): results are research-use only and share-alike terms apply to redistribution of derived data.

ECG reference agreement measures pulse-rate agreement only. It does not validate PRV/HRV estimation, does not establish clinical validity, and does not generalise beyond 26 young Portuguese university students under natural indoor light.
