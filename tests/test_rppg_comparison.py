import csv
import json
from pathlib import Path
import numpy as np
import pytest
from research.rppg.compare_algorithms import compare,evaluate_recording

def make_csv(path, n=900, missing=True):
    fs=30; t=np.arange(n)/fs
    fields=['timestamp_s','reference_hr_bpm']+[f'{roi}_{c}' for roi in ('forehead','left_cheek','right_cheek') for c in 'rgb']
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for i,ti in enumerate(t):
            pulse=np.sin(2*np.pi*1.2*ti)*.01
            row={'timestamp_s':ti,'reference_hr_bpm':72}
            for roi,scale in zip(('forehead','left_cheek','right_cheek'),(1,.9,1.1)):
                for c,base,s in zip('rgb',(100,120,90),(1,-1,.5)):
                    row[f'{roi}_{c}']='' if (missing and roi=='left_cheek' and 300<=i<320) else base*(1+scale*s*pulse)
            w.writerow(row)
    return path

def test_missing_roi_isolated_and_no_reference_metrics_by_default(tmp_path):
    path=make_csv(tmp_path/'trace.csv')
    result=compare(path)
    assert result['aggregate_metrics']=={}
    assert result['reference_metrics_authorized'] is False
    windows=result['recordings'][0]['windows']
    assert windows[0]['estimates_bpm']['forehead_green'] is not None
    assert any(w['estimates_bpm']['left_cheek_green'] is None for w in windows)
    assert any(w['estimates_bpm']['multi_roi_green'] is not None for w in windows)

def test_reference_metrics_require_provenance_and_include_agreement(tmp_path):
    result=compare(make_csv(tmp_path/'trace.csv',missing=False),reference_authorized=True)
    metrics=result['aggregate_metrics']['forehead_green']['pooled_window_metrics']
    assert metrics['n_windows']>0
    assert {'mae_bpm','rmse_bpm','bias_bpm','loa_lower_95_bpm','loa_upper_95_bpm'}<=set(metrics)

def test_shared_fixture_matches_documented_python_algorithm_outputs():
    fixture=Path(__file__).parent/'fixtures/rppg_rgb_fixture.csv'
    expected=json.loads((Path(__file__).parent/'fixtures/rppg_rgb_fixture_expected.json').read_text())
    result=evaluate_recording(fixture)
    estimates=result['windows'][0]['estimates_bpm']
    for key,value in expected['reference_free_expected_python_estimates_bpm'].items():
        assert estimates[key] == pytest.approx(value,abs=.1)


def test_manifest_yields_recording_level_summaries(tmp_path):
    one=make_csv(tmp_path/'one.csv',missing=False)
    manifest=tmp_path/'manifest.csv'
    with manifest.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['recording_id','csv_path']);w.writeheader();w.writerow({'recording_id':'session-1','csv_path':'one.csv'})
    result=compare(manifest,reference_authorized=True)
    assert result['recordings'][0]['recording_id']=='session-1'
    assert 'recording_metrics' in result['aggregate_metrics']['forehead_green']
