# Research methodology and current status

## Contactless pulse module

Existing research code extracts Green and POS traces from facial video and computes FFT/peak-based pulse candidates, motion classes, respiratory tachogram estimates and optional reference-device comparisons. The code retains historical correction heuristics for reproducibility; these are experimental and must be evaluated with correction on/off, by recording and motion condition. Current defaults are 0.7–3.5 Hz (42–210 BPM). CHROM is exposed as an independent RGB-trace transform. Offline ROI sampling retains separate forehead/cheek RGB traces with a conservative YCrCb skin-pixel heuristic; this is not landmark-based segmentation and is not guaranteed to exclude all non-skin pixels. Sampling frequency uses monotonic decoder timestamps where available, with nominal frame-rate fallback where decoder timestamps are absent or invalid. Frame gaps are counted for audit, not imputed as observations.

A valid measurement requires adequate duration, a tracked skin ROI, reliable pulsatile spectrum, and estimator/window consistency. An absent or poor-quality signal must remain unavailable; synthetic tests validate implementation only, not physiology. Respiratory estimates derived from pulse intervals are experimental. Pulse interval variability is PRV, not ECG HRV; no clinical or ECG agreement claim is established.

## Anemia module

No dataset or model is present. Investigate provenance, permission, original/augmented records, patient grouping, laboratory Hb and demographics before processing. Keep original records together with derived variants for splitting. Prefer interpretable baselines and patient-grouped evaluation. No screening threshold should be applied without appropriate demographic information and applicable guidance. Never infer iron deficiency specifically from pallor.

## Evaluation

For rPPG, compare Green, POS and CHROM, then ROI/quality fusion under identical recording-level partitions against synchronized references. Report errors and Bland–Altman agreement, include failures, and disclose reference-device limitations. For anemia, separate development and independent evaluation and report calibration and subgroup limitations. No performance results are reported by this repository update.
