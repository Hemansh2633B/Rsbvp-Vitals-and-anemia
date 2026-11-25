"""Independent ECG reference-signal processing pathway.

Used ONLY to derive window-level reference heart rate from the rPPG-10
(or any lawfully supplied) ECG recording. This module never produces
clinical ECG interpretations, never detects arrhythmias, and does not
estimate PRV/HRV. See docs/RELIABILITY.md and docs/RPPG10_VALIDATION.md.
"""
