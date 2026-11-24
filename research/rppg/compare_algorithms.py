#!/usr/bin/env python3
"""Recording/window-level comparison from actual timestamped RGB traces.

CSV columns: timestamp_s; optional externally computed reference_hr_bpm; ROI
channel columns forehead_r/g/b, left_cheek_r/g/b, right_cheek_r/g/b. This legacy
trace comparator does not process reference waveforms or derive/synchronize HR;
use validate_dataset.py for local PPG/BVP waveform references. A supplied scalar
reference is user-attested and may be constant only when the source genuinely
provides only that value. A missing ROI/channel is unavailable. Frames are
regularized only across short gaps; longer gaps invalidate that analysis window.
For multiple recordings pass --manifest CSV with recording_id,csv_path.
Error metrics are emitted only with --reference-source describing a genuine,
synchronized reference; this tool cannot authenticate supplied provenance.
"""
import argparse, csv, json, sys
from pathlib import Path
import numpy as np
from scipy.signal import welch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'gui'))
from rppg_core.research import chrom_rppg,timestamps_to_fs
from rppg_core.pipeline import pos_rppg,MIN_BPM,MAX_BPM
from rppg_core.version import software_info as _software_info
ROIS=('forehead','left_cheek','right_cheek')
CHANNELS='rgb'
WINDOW_SECONDS=12.0
STEP_SECONDS=6.0

def _read(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
    if len(rows)<3 or not rows[0] or 'timestamp_s' not in rows[0]: raise ValueError(f'{path}: requires timestamp_s and at least 3 rows')
    t=np.array([float(r['timestamp_s']) for r in rows])
    fs,drop=timestamps_to_fs(t)
    if fs<=2*(MAX_BPM/60): raise ValueError(f'{path}: sampling rate too low for configured upper pulse band')
    return rows,t,fs,drop

def _rgb(rows,roi):
    cols=[f'{roi}_{c}' for c in CHANNELS]
    if not all(c in rows[0] for c in cols): return None
    out=[]
    for row in rows:
        try: val=[float(row[c]) if row[c] not in ('',None) else np.nan for c in cols]
        except (TypeError,ValueError): val=[np.nan]*3
        out.append(val)
    return np.asarray(out,float)

def _regularize(t,values,fs,max_gap=.25):
    if values is None:return None,None
    values=np.asarray(values,float)
    grid=np.arange(t[0],t[-1]+.25/fs,1/fs)
    out=np.full((len(grid),values.shape[1]),np.nan)
    for c in range(values.shape[1]):
        good=np.isfinite(values[:,c]); tg=t[good]; vg=values[good,c]
        if len(tg)<8:return None,None
        pos=np.searchsorted(tg,grid,side='right'); lo=np.clip(pos-1,0,len(tg)-1); hi=np.clip(pos,0,len(tg)-1)
        gaps=tg[hi]-tg[lo]; valid=(grid>=tg[0])&(grid<=tg[-1])&(gaps<=max_gap)
        frac=np.divide(grid-tg[lo],gaps,out=np.zeros_like(grid),where=gaps>0)
        ix=np.flatnonzero(valid); fv=frac[ix]
        out[ix,c]=vg[lo[ix]]*(1-fv)+vg[hi[ix]]*fv
    return grid,out

def _hr(x,fs):
    x=np.asarray(x,float)
    if x.ndim!=1 or len(x)<max(8,int(8*fs)) or not np.isfinite(x).all() or np.std(x)<1e-8:return None
    f,p=welch(x-x.mean(),fs=fs,nperseg=min(len(x),int(12*fs)))
    use=(f>=MIN_BPM/60)&(f<=MAX_BPM/60)
    if not use.any() or not np.isfinite(p[use]).all() or p[use].max()<=0:return None
    return float(f[use][np.argmax(p[use])]*60)

def _estimators(rgb,fs):
    if rgb is None or not np.isfinite(rgb).all():return {'green':None,'pos':None,'chrom':None}
    try: pos=_hr(pos_rppg(rgb,fs),fs)
    except (ValueError,FloatingPointError):pos=None
    try: chrom=_hr(chrom_rppg(rgb,fs)[0],fs)
    except (ValueError,FloatingPointError):chrom=None
    return {'green':_hr(rgb[:,1],fs),'pos':pos,'chrom':chrom}

def evaluate_recording(path,recording_id=None,window_seconds=WINDOW_SECONDS,step_seconds=STEP_SECONDS,reference_authorized=False):
    rows,t,fs,drop=_read(path)
    grids={};signals={}
    for roi in ROIS:
        raw=_rgb(rows,roi);grid,reg=_regularize(t,raw,fs)
        if reg is not None:grids[roi]=grid;signals[roi]=reg
    ref=None
    if reference_authorized and 'reference_hr_bpm' in rows[0]:
        refraw=np.array([float(r['reference_hr_bpm']) if r.get('reference_hr_bpm') not in ('',None) else np.nan for r in rows])[:,None]
        refgrid,refreg=_regularize(t,refraw,fs)
        if refreg is not None: ref=refreg[:,0]
    start=t[0];end=t[-1];windows=[]
    begins=np.arange(start,max(start,end-window_seconds)+1e-6,step_seconds)
    for ws in begins:
        we=ws+window_seconds
        per_roi={}
        for roi in ROIS:
            if roi not in signals:per_roi[roi]=None;continue
            grid=grids[roi];mask=(grid>=ws)&(grid<we);segment=signals[roi][mask]
            per_roi[roi]=_estimators(segment,fs) if len(segment)>=int(8*fs) else None
        combined={}
        for name,these in [('cheeks',('left_cheek','right_cheek')),('multi_roi',ROIS)]:
            available=[signals[r] for r in these if r in signals]
            if not available:combined[name]=None;continue
            grid=grids[next(r for r in these if r in signals)]
            if any(not np.array_equal(grids[r],grid) for r in these if r in signals):combined[name]=None;continue
            cube=np.stack([signals[r] for r in these if r in signals])
            valid=np.isfinite(cube).all(axis=2)
            required=1 if name=='cheeks' else min(2,len(these))
            counts=valid.sum(axis=0)
            mean=np.divide(np.nansum(cube,axis=0),counts[:,None],out=np.full((len(grid),3),np.nan),where=counts[:,None]>0)
            mean[counts<required]=np.nan
            mask=(grid>=ws)&(grid<we);seg=mean[mask]
            combined[name]=_estimators(seg,fs) if len(seg)>=int(8*fs) and np.isfinite(seg).all() else None
        values={}
        for roi,method_results in per_roi.items():
            for method in ('green','pos','chrom'):values[f'{roi}_{method}']=method_results.get(method) if method_results else None
        for strategy,method_results in combined.items():
            for method in ('green','pos','chrom'):values[f'{strategy}_{method}']=method_results.get(method) if method_results else None
        reference=None
        if ref is not None:
            grid=refgrid;mask=(grid>=ws)&(grid<we)&np.isfinite(ref);vals=ref[mask]
            if len(vals):reference=float(np.median(vals))
        windows.append({'recording_id':recording_id or Path(path).stem,'start_s':float(ws),'end_s':float(we),'reference_bpm':reference,'estimates_bpm':values})
    return {'recording_id':recording_id or Path(path).stem,'source':str(path),'sampling_rate_hz':fs,'sample_count':len(rows),'dropped_interval_fraction':drop,'windows':windows}

def _metrics(pairs):
    if not pairs:return {'n_windows':0,'mae_bpm':None,'rmse_bpm':None,'bias_bpm':None,'loa_lower_95_bpm':None,'loa_upper_95_bpm':None}
    e=np.array([est-ref for ref,est in pairs]);bias=float(e.mean());sd=float(e.std(ddof=1)) if len(e)>1 else None
    return {'n_windows':len(e),'mae_bpm':float(np.abs(e).mean()),'rmse_bpm':float(np.sqrt(np.mean(e**2))),'bias_bpm':bias,'loa_lower_95_bpm':bias-1.96*sd if sd is not None else None,'loa_upper_95_bpm':bias+1.96*sd if sd is not None else None}

def compare(input_path,reference_authorized=False):
    p=Path(input_path);records=[]
    if p.suffix.lower()=='.json':raise ValueError('Use CSV or --manifest CSV; JSON manifests are unsupported')
    with p.open(newline='',encoding='utf-8-sig') as f:first=next(csv.reader(f),[])
    if {'recording_id','csv_path'}.issubset(first):
        with p.open(newline='',encoding='utf-8-sig') as f: items=list(csv.DictReader(f))
        for item in items:
            source=Path(item['csv_path']);source=source if source.is_absolute() else p.parent/source
            records.append(evaluate_recording(source,item['recording_id'],reference_authorized=reference_authorized))
    else:records.append(evaluate_recording(p,reference_authorized=reference_authorized))
    names=sorted({k for rec in records for w in rec['windows'] for k in w['estimates_bpm']})
    aggregate={}
    if reference_authorized:
        for name in names:
            per_record={};pairs=[]
            for rec in records:
                these=[(w['reference_bpm'],w['estimates_bpm'].get(name)) for w in rec['windows'] if w['reference_bpm'] is not None and w['estimates_bpm'].get(name) is not None]
                pairs.extend(these);per_record[rec['recording_id']]=_metrics(these)
            aggregate[name]={'pooled_window_metrics':_metrics(pairs),'recording_metrics':per_record}
    return {'passband_bpm':[MIN_BPM,MAX_BPM],'window_seconds':WINDOW_SECONDS,'step_seconds':STEP_SECONDS,'reference_metrics_authorized':bool(reference_authorized),'reference_note':'Metrics are computed only when --reference-source is provided. Provenance is user-supplied and not independently authenticated.' if reference_authorized else 'No numerical errors computed: no --reference-source was provided.','recordings':records,'aggregate_metrics':aggregate}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path,help='trace CSV, or manifest CSV (recording_id,csv_path)');p.add_argument('--output',type=Path,default=Path('rppg_comparison.json'));p.add_argument('--reference-source',help='Provenance string for genuine synchronized reference data; enables error metrics.');a=p.parse_args()
    result=compare(a.input,reference_authorized=bool(a.reference_source));result['reference_source']=a.reference_source
    result['generated_by']={'tool':'research/rppg/compare_algorithms.py',**_software_info()}
    a.output.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
