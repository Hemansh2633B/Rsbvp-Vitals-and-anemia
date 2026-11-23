# Synthetic degradation suite — reliability software verification

- Schema: `rsbvp.reliability-synthetic.v1`
- Truth: 70.0 BPM (synthetic pulse; no physiology)
- Windowing: {'window_seconds': 12.0, 'step_seconds': 6.0}
- Seed: 20261123 · duration 60.0 s · base fs 30.0 Hz

> **SYNTHETIC SOFTWARE VERIFICATION ONLY — NOT PHYSIOLOGICAL VALIDATION.**
> These measurements exercise the pipelines and quality gates under controlled
> corruption. They say nothing about real cameras, skin, motion or patients.

| Condition | Backend | Algo | Availability | Quality-OK | Rejected/unavailable | MAE vs truth (BPM) |
|---|---|---|---|---|---|---|
| baseline | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_native | POS | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_reference | PBV | 1.000 | 1.000 | 0 | 0.0000 |
| baseline | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_native | POS | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_reference | PBV | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.30 | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_native | CHROM | 1.000 | 0.889 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_native | POS | 1.000 | 0.556 | 0 | 14.6296 |
| low_light_gain_0.15 | rsbvp_reference | CHROM | 1.000 | 0.889 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_reference | PBV | 1.000 | 0.889 | 0 | 0.0000 |
| low_light_gain_0.15 | rsbvp_reference | POS | 1.000 | 0.630 | 0 | 11.6667 |
| high_noise_sigma_3.0 | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_native | POS | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_reference | PBV | 1.000 | 1.000 | 0 | 0.0000 |
| high_noise_sigma_3.0 | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_native | POS | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| motion_transients | rsbvp_reference | PBV | 1.000 | 0.963 | 0 | 0.0000 |
| motion_transients | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 0.0000 |
| frame_drops_20pct | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 1.0480 |
| frame_drops_20pct | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 1.0480 |
| frame_drops_20pct | rsbvp_native | POS | 1.000 | 1.000 | 0 | 1.0480 |
| frame_drops_20pct | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 1.0480 |
| frame_drops_20pct | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 1.0480 |
| frame_drops_20pct | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 1.0480 |
| frame_drops_20pct | rsbvp_reference | PBV | 1.000 | 1.000 | 0 | 2.5373 |
| frame_drops_20pct | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 1.0480 |
| low_fs_15hz | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_native | POS | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_reference | PBV | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_15hz | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_native | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_native | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_native | POS | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_reference | CHROM | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_reference | GREEN | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_reference | ICA | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_reference | PBV | 1.000 | 1.000 | 0 | 0.0000 |
| low_fs_10hz | rsbvp_reference | POS | 1.000 | 1.000 | 0 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_native | CHROM | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_native | GREEN | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_native | POS | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_reference | CHROM | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_reference | GREEN | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_reference | ICA | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_reference | PBV | 0.667 | 0.667 | 9 | 0.0000 |
| roi_dropout_left_cheek | rsbvp_reference | POS | 0.667 | 0.667 | 9 | 0.0000 |

## Rejection reasons (aggregate)

- roi_dropout_left_cheek · rsbvp_native: {'nonfinite_samples': 27}
- roi_dropout_left_cheek · rsbvp_reference: {'nonfinite_samples': 45}
