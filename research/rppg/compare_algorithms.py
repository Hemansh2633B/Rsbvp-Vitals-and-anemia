#!/usr/bin/env python3
"""Compare classical rPPG methods on an already acquired RGB trace CSV.

Input columns: timestamp_s, forehead_r/g/b, left_cheek_r/g/b,
right_cheek_r/g/b; optional reference_hr_bpm constant per recording. Each row
is a frame/sample. Uses no fabricated data and reports missing references as
unscored. Exposes global Green/POS/CHROM and ROI Green/POS/CHROM. This does not
replace recording-grouped benchmark design or synchronized reference review.
"""
import argparse, csv, json, sys
from pathlib import Path
import numpy as np
from scipy.signal import welch, find_peaks
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'gui'))
from rppg_core.research import chrom_rppg, timestamps_to_fs
from rppg_core.pipeline import pos_rppg, MIN_BPM, MAX_BPM

ROIS = ('forehead', 'left_cheek', 'right_cheek')
def _hr(x, fs):
    x = np.asarray(x, float)
    if len(x) < int(8*fs) or not np.isfinite(x).all() or np.std(x) < 1e-8:
        return None
    nperseg = min(len(x), int(12*fs))
    f, p = welch(x-np.mean(x), fs=fs, nperseg=nperseg)
    use = (f >= MIN_BPM/60) & (f <= MAX_BPM/60)
    if not use.any() or np.max(p[use]) <= 0:
        return None
    return float(f[use][np.argmax(p[use])] * 60)

def _methods(rgb, fs):
    out = {'green': _hr(rgb[:,1], fs)}
    try:
        out['pos'] = _hr(pos_rppg(rgb, fs), fs)
        out['chrom'] = _hr(chrom_rppg(rgb, fs)[0], fs)
    except (ValueError, FloatingPointError):
        out.update(pos=None, chrom=None)
    return out

def compare(path):
    rows = list(csv.DictReader(Path(path).open(newline='', encoding='utf-8-sig')))
    if len(rows) < 3: raise ValueError('CSV must contain at least 3 samples')
    t = np.array([float(r['timestamp_s']) for r in rows])
    fs, dropped_fraction = timestamps_to_fs(t)
    result = {'sampling_rate_hz': fs, 'sample_count': len(rows), 'dropped_interval_fraction': dropped_fraction,
              'passband_bpm': [MIN_BPM, MAX_BPM], 'methods': {}}
    reference = None
    for r in rows:
        value = r.get('reference_hr_bpm', '')
        if value not in ('', None):
            v = float(value)
            if reference is not None and abs(reference-v) > 1e-6:
                raise ValueError('reference_hr_bpm must be constant per input window')
            reference = v
    def add(prefix, rgb):
        methods = _methods(rgb, fs)
        for key, estimate in methods.items():
            name = f'{prefix}{key}'
            result['methods'][name] = {'estimate_bpm': estimate, 'reference_bpm': reference,
                'absolute_error_bpm': abs(estimate-reference) if estimate is not None and reference is not None else None}
    # Per-row spatial average over available ROIs; never replace missing ROI values with zero.
    for roi in ROIS:
        rgb = np.array([[float(r[f'{roi}_{c}']) for c in 'rgb'] for r in rows])
        add(f'{roi}_', rgb)
    roi_traces = [np.array([[float(r[f'{roi}_{c}']) for c in 'rgb'] for r in rows]) for roi in ROIS]
    valid = np.stack([np.isfinite(a).all(axis=1) for a in roi_traces])
    cube = np.stack(roi_traces)
    mean = np.divide(np.nansum(cube, axis=0), valid.sum(axis=0)[:,None], out=np.full((len(rows),3), np.nan), where=valid.sum(axis=0)[:,None]>0)
    # Multi-ROI only on complete rows; retaining gaps is preferred to fabricated interpolation.
    good = np.isfinite(mean).all(axis=1)
    if good.all(): add('multi_roi_', mean)
    else:
        result['multi_roi_note'] = 'Skipped: ROI gaps exist; no interpolation or imputation performed.'
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('rgb_csv',type=Path); p.add_argument('--output',type=Path,default=Path('rppg_comparison.json')); a=p.parse_args()
    result=compare(a.rgb_csv); a.output.write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps(result,indent=2))
if __name__=='__main__': main()
