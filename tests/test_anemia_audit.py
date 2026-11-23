"""Dataset-audit tool tests: hashes, near-duplicates, label joins, QA buckets."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import cv2

SCRIPT = Path(__file__).resolve().parents[1] / 'research' / 'anemia' / 'audit_dataset.py'


def _fixture(tmp_path, n_patients=3):
    d = tmp_path / 'imgs'
    d.mkdir()
    rng = np.random.default_rng(7)
    for i in range(6):
        cv2.imwrite(str(d / f'img_{i:03d}.png'), rng.integers(40, 220, (200, 240, 3), dtype=np.uint8))
    img = cv2.imread(str(d / 'img_000.png'))
    cv2.imwrite(str(d / 'img_dup.png'), img)
    near = np.clip(img.astype(np.int16) + rng.integers(-2, 3, img.shape, dtype=np.int16), 0, 255).astype(np.uint8)
    cv2.imwrite(str(d / 'img_near.png'), near)
    labels = d / 'labels.csv'
    with labels.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['image_id', 'patient_id', 'hemoglobin'])
        w.writeheader()
        for i in range(6):
            w.writerow({'image_id': f'img_{i:03d}', 'patient_id': f'patient_{i % n_patients}', 'hemoglobin': ''})
    return d, labels


def test_audit_hashes_duplicates_and_patient_groups(tmp_path):
    d, labels = _fixture(tmp_path)
    out = tmp_path / 'audit.csv'
    proc = subprocess.run([sys.executable, str(SCRIPT), str(d), '--labels', str(labels), '--output', str(out)],
                          capture_output=True, text=True, check=True)
    summary = json.loads(proc.stdout)
    assert summary['image_count'] == 8
    assert summary['label_matched_count'] == 6 and summary['label_missing_count'] == 2
    assert summary['exact_duplicate_groups'] == 1
    assert summary['near_duplicate_groups'] == 1
    assert summary['patients'] == 3 and summary['patients_with_multiple_images'] == 3
    rows = {r['image_id']: r for r in csv.DictReader(out.open())}
    assert rows['img_000']['sha256'] == rows['img_dup']['sha256']
    assert int(rows['img_000']['duplicate_sha256_count']) == 2
    assert rows['img_near']['near_duplicate_group'] not in ('', '0')
    assert rows['img_000']['patient_id'] == 'patient_0'


def test_audit_handles_empty_directory(tmp_path):
    d = tmp_path / 'empty'; d.mkdir()
    out = tmp_path / 'audit.csv'
    proc = subprocess.run([sys.executable, str(SCRIPT), str(d), '--output', str(out)],
                          capture_output=True, text=True, check=True)
    summary = json.loads(proc.stdout)
    assert summary['image_count'] == 0
