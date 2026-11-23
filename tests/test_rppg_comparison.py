import csv
import numpy as np
from research.rppg.compare_algorithms import compare


def test_comparison_reports_algorithms_and_never_invents_reference(tmp_path):
    path = tmp_path / 'trace.csv'
    fs = 30
    fields = ['timestamp_s'] + [f'{roi}_{c}' for roi in ('forehead','left_cheek','right_cheek') for c in 'rgb']
    t = np.arange(600)/fs
    with path.open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for i,ti in enumerate(t):
            pulse=np.sin(2*np.pi*1.2*ti)*.01
            row={'timestamp_s':ti}
            for roi,scale in zip(('forehead','left_cheek','right_cheek'),(1,.9,1.1)):
                for c,base,s in zip('rgb',(100,120,90),(1,-1,.5)):
                    row[f'{roi}_{c}']=base*(1+scale*s*pulse)
            w.writerow(row)
    result=compare(path)
    for key in ('forehead_green','forehead_pos','forehead_chrom','multi_roi_green','multi_roi_pos','multi_roi_chrom'):
        assert key in result['methods']
        assert result['methods'][key]['reference_bpm'] is None
        assert result['methods'][key]['absolute_error_bpm'] is None
