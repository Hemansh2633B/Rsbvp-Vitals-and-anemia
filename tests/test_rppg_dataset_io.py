import csv
import json
from pathlib import Path
import numpy as np
import pytest

from research.rppg.dataset_io import data_root, read_manifest, load_reference, reference_hr_windows, ReferenceSignal
from research.rppg.validate_dataset import _metrics, _participant_bootstrap, markdown_report, evaluate_manifest


def _write_manifest(root: Path, *, ref='reference.csv', license_verified='true', time_offset='0.0'):
    (root/'trace.csv').write_text('timestamp_s,forehead_r,forehead_g,forehead_b\n0,1,1,1\n1,1,1,1\n')
    t=np.arange(15*30)/30
    x=np.sin(2*np.pi*1.2*t)
    with (root/ref).open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['timestamp_s','ppg']); w.writerows(zip(t,x))
    manifest=root/'manifest.csv'
    fields=['dataset','dataset_version','participant_id','recording_id','trace_csv','reference_path','reference_format','reference_type','reference_time_column','reference_signal_column','reference_fs_hz','time_offset_s','source_citation','license_verified']
    with manifest.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerow(dict(dataset='test',dataset_version='1',participant_id='p-01',recording_id='r-01',trace_csv='trace.csv',reference_path=ref,reference_format='csv',reference_type='ppg',reference_time_column='timestamp_s',reference_signal_column='ppg',reference_fs_hz='',time_offset_s=time_offset,source_citation='synthetic test fixture',license_verified=license_verified))
    return manifest


def test_data_root_cli_precedes_environment_and_missing_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv('RSBVP_DATA_ROOT', raising=False)
    with pytest.raises(ValueError, match='RSBVP_DATA_ROOT'):
        data_root()
    monkeypatch.setenv('RSBVP_DATA_ROOT', str(tmp_path))
    assert data_root() == tmp_path.resolve()
    other=tmp_path/'cli';other.mkdir()
    assert data_root(other) == other.resolve()


def test_manifest_validation_and_missing_files_and_terms(tmp_path):
    manifest=_write_manifest(tmp_path)
    assert len(read_manifest(manifest,tmp_path)) == 1
    (tmp_path/'reference.csv').unlink()
    with pytest.raises(FileNotFoundError, match='missing reference_path'):
        read_manifest(manifest,tmp_path)
    manifest=_write_manifest(tmp_path, license_verified='false')
    with pytest.raises(ValueError, match='terms/license'):
        read_manifest(manifest,tmp_path)
    row=next(csv.DictReader(manifest.open()))
    with pytest.raises(ValueError,match='must be explicitly verified'):
        load_reference(row,tmp_path)


def test_manifest_rejects_paths_outside_data_root_and_symlinks(tmp_path):
    manifest=_write_manifest(tmp_path)
    row=read_manifest(manifest,tmp_path)[0]
    row['reference_path']='../outside.csv'
    with pytest.raises(ValueError,match='escapes configured data root'):
        from research.rppg.dataset_io import _local_path
        _local_path(tmp_path,row['reference_path'])
    outside=tmp_path.parent/'outside-reference.csv';outside.write_text('x\n1\n')
    link=tmp_path/'escape.csv';link.symlink_to(outside)
    row['reference_path']='escape.csv'
    with pytest.raises(ValueError,match='escapes configured data root'):
        _local_path(tmp_path,row['reference_path'])


def test_reference_timing_offset_and_window_specific_hr(tmp_path):
    manifest=_write_manifest(tmp_path,time_offset='2.0')
    row=read_manifest(manifest,tmp_path)[0]
    ref=load_reference(row,tmp_path)
    assert ref.sampling_hz == pytest.approx(30,abs=.01)
    assert ref.timestamps_s[0] == pytest.approx(2)
    # Declared/original and timestamp-measured rates remain distinct if they differ.
    row['reference_fs_hz']='60'
    mismatched=load_reference(row,tmp_path)
    assert mismatched.sampling_hz == pytest.approx(60)
    assert 1/mismatched.timestamp_median_interval_s == pytest.approx(30,abs=.01)
    info=reference_hr_windows(mismatched,[2],window_seconds=12)[0]
    assert info['original_sampling_hz']==pytest.approx(60)
    assert info['measured_sampling_hz']==pytest.approx(30,abs=1)
    assert info['effective_sampling_hz']==pytest.approx(30,abs=1)
    windows=reference_hr_windows(ref,[2],window_seconds=12,step_seconds=6)
    assert windows[0]['valid']
    assert windows[0]['reference_hr_bpm'] == pytest.approx(72,abs=2.5)
    assert windows[0]['reference_type']=='ppg'


def test_timestamp_jitter_rejection_and_small_jitter_resampling(tmp_path):
    manifest=_write_manifest(tmp_path); ref=load_reference(read_manifest(manifest,tmp_path)[0],tmp_path)
    t=ref.timestamps_s.copy(); base=np.arange(len(t))/30
    small=base+0.0004*np.sin(np.arange(len(t))*1.7)
    small[0]=base[0]; small[-1]=base[-1]
    smooth=ReferenceSignal(small,ref.values,30,'ppg',0,float(np.median(np.diff(small))),0)
    accepted=reference_hr_windows(smooth,[0],window_seconds=12,max_jitter_fraction=.05)
    assert accepted[0]['valid'] and accepted[0]['effective_sampling_hz'] == pytest.approx(30,abs=1)
    assert reference_hr_windows(smooth,[0],window_seconds=12,max_jitter_fraction=0)[0]['rejection_reason']=='timestamp_jitter_exceeds_tolerance'
    large=base+0.004*np.sin(np.arange(len(t))*1.7)
    large[0]=base[0]; large[-1]=base[-1]
    jitter=float(np.median(np.abs(np.diff(large)-np.median(np.diff(large))))/np.median(np.diff(large)))
    rough=ReferenceSignal(large,ref.values,30,'bvp',0,float(np.median(np.diff(large))),jitter)
    rejected=reference_hr_windows(rough,[0],window_seconds=12,max_jitter_fraction=.05)
    assert rejected[0]['rejection_reason']=='timestamp_jitter_exceeds_tolerance'


def test_short_dropped_frame_is_resampled_but_long_discontinuity_rejected(tmp_path):
    manifest=_write_manifest(tmp_path); ref=load_reference(read_manifest(manifest,tmp_path)[0],tmp_path)
    keep=np.ones(len(ref.values),dtype=bool); keep[20]=False
    short=ReferenceSignal(ref.timestamps_s[keep],ref.values[keep],30,'ppg',0,ref.timestamp_median_interval_s,0)
    assert reference_hr_windows(short,[0],window_seconds=12,max_gap_seconds=.25)[0]['valid']
    assert reference_hr_windows(short,[0],window_seconds=12,max_gap_seconds=.05)[0]['rejection_reason']=='reference_gap_exceeds_limit'
    keep=np.ones(len(ref.values),dtype=bool); keep[140:160]=False
    long=ReferenceSignal(ref.timestamps_s[keep],ref.values[keep],30,'ppg',0,ref.timestamp_median_interval_s,0)
    assert reference_hr_windows(long,[0],window_seconds=12,max_gap_seconds=.25)[0]['rejection_reason']=='reference_gap_exceeds_limit'


def test_duplicate_and_nonmonotonic_timestamps_rejected(tmp_path):
    manifest=_write_manifest(tmp_path); row=read_manifest(manifest,tmp_path)[0]
    path=tmp_path/'reference.csv'
    rows=list(csv.DictReader(path.open()))
    rows[10]['timestamp_s']=rows[9]['timestamp_s']
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['timestamp_s','ppg']);w.writeheader();w.writerows(rows)
    with pytest.raises(ValueError,match='strictly increasing'):
        load_reference(row,tmp_path)
    rows[10]['timestamp_s']='-1'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['timestamp_s','ppg']);w.writeheader();w.writerows(rows)
    with pytest.raises(ValueError,match='strictly increasing'):
        load_reference(row,tmp_path)


def test_ecg_is_explicitly_rejected_while_ppg_and_bvp_use_pulse_method(tmp_path):
    manifest=_write_manifest(tmp_path); row=read_manifest(manifest,tmp_path)[0]
    ppg=load_reference(row,tmp_path)
    assert reference_hr_windows(ppg,[0],window_seconds=12)[0]['valid']
    from dataclasses import replace
    bvp=replace(ppg,signal_type='bvp')
    assert reference_hr_windows(bvp,[0],window_seconds=12)[0]['valid']
    ecg=replace(ppg,signal_type='ecg')
    result=reference_hr_windows(ecg,[0],window_seconds=12)[0]
    assert result['reference_hr_bpm'] is None
    assert result['rejection_reason']=='ecg_rpeak_estimator_unavailable'


def test_offset_boundaries_require_complete_synchronized_window(tmp_path):
    manifest=_write_manifest(tmp_path); ref=load_reference(read_manifest(manifest,tmp_path)[0],tmp_path)
    # Positive offset moves a 0..15 s reference onto trace clock 2..17 s.
    from dataclasses import replace
    positive=replace(ref,timestamps_s=ref.timestamps_s+2,offset_s=2)
    assert reference_hr_windows(positive,[2],window_seconds=12)[0]['valid']
    # Negative offset moves the same reference onto -2..13 s.
    negative=replace(ref,timestamps_s=ref.timestamps_s-2,offset_s=-2)
    assert reference_hr_windows(negative,[0],window_seconds=12)[0]['valid']
    late=replace(ref,timestamps_s=ref.timestamps_s+1)
    assert reference_hr_windows(late,[0],window_seconds=12)[0]['rejection_reason']=='reference_does_not_cover_window_start'
    early_end=replace(ref,timestamps_s=ref.timestamps_s-4)
    assert reference_hr_windows(early_end,[0],window_seconds=12)[0]['rejection_reason']=='reference_does_not_cover_window_end'


def test_missing_samples_and_long_gaps_reject_reference_windows(tmp_path):
    manifest=_write_manifest(tmp_path)
    row=read_manifest(manifest,tmp_path)[0]
    ref=load_reference(row,tmp_path)
    vals=ref.values.copy(); vals[20]=np.nan
    from dataclasses import replace
    missing=reference_hr_windows(replace(ref,values=vals),[0],window_seconds=12)
    assert missing[0]['rejection_reason']=='missing_or_malformed_reference_samples'
    keep=np.ones(len(ref.values),dtype=bool); keep[150:165]=False
    gap=replace(ref,timestamps_s=ref.timestamps_s[keep],values=ref.values[keep])
    result=reference_hr_windows(gap,[0],window_seconds=12,max_gap_seconds=.25)
    assert result[0]['rejection_reason']=='reference_gap_exceeds_limit'
    short=replace(ref,timestamps_s=np.delete(ref.timestamps_s,20),values=np.delete(ref.values,20))
    assert reference_hr_windows(short,[0],window_seconds=12)[0]['valid']


def test_end_to_end_synthetic_manifest_report_generation(tmp_path):
    manifest=_write_manifest(tmp_path)
    # Supply 30 Hz RGB and independently sampled 25 Hz reference fixture.
    tref=np.arange(15*25)/25; refpulse=np.sin(2*np.pi*1.2*tref)
    with (tmp_path/'reference.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['timestamp_s','ppg']);w.writerows(zip(tref,refpulse))
    fs=30; t=np.arange(15*fs)/fs; pulse=.01*np.sin(2*np.pi*1.2*t)
    with (tmp_path/'trace.csv').open('w',newline='') as f:
        fields=['timestamp_s']+[f'{roi}_{c}' for roi in ('forehead','left_cheek','right_cheek') for c in 'rgb']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for ti,p in zip(t,pulse):
            row={'timestamp_s':ti}
            for roi in ('forehead','left_cheek','right_cheek'):
                row.update({f'{roi}_r':100*(1+p),f'{roi}_g':120*(1-p),f'{roi}_b':90*(1+.5*p)})
            w.writerow(row)
    result= evaluate_manifest(manifest,tmp_path,window_seconds=12,step_seconds=6)
    assert result['status']=='COMPLETED' and result['recording_count']==1
    assert result['participant_count']==1
    assert result['recordings'][0]['signal_sampling_hz']==pytest.approx(30,abs=.01)
    assert result['recordings'][0]['reference_original_sampling_hz']==pytest.approx(25,abs=.01)
    assert result['metrics_by_algorithm_roi']['forehead_green']['windows_total'] >= 1
    assert result['metrics_by_algorithm_roi']['forehead_green']['quality_gate_coverage'] is None
    report=markdown_report(result,'synthetic test invocation')
    assert 'quality-gate coverage' in report and 'forehead_green' in report


def test_metrics_group_participants_and_no_fake_report_results():
    m=_metrics([(70,72),(80,78)])
    assert m['n_windows']==2 and m['mae_bpm']==2
    groups={'p1':[(70,72)],'p2':[(80,78)]}
    assert _participant_bootstrap(groups,n_boot=100,seed=2)['participants']==2
    assert _participant_bootstrap({'p1':[(70,72)]}) is None
    md=markdown_report({'status':'NOT RUN','reason':'dataset absent'},'test command')
    assert 'NOT RUN — DATASET NOT AVAILABLE' in md
