#!/usr/bin/env python3
"""Inventory actual local image files; never downloads or synthesizes dataset records.

Optional labels CSV must contain image_id and may include patient_id, hemoglobin,
sex, age, pregnancy_status and original_status. Output CSV includes hashes for
near-duplicate review. Protect output as potentially sensitive research metadata.
"""
import argparse, csv, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gui"))
import cv2
from anemia_core.image_features import assess_image

EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'}

def ahash(path, size=8):
    """8x8 average hash (luminance); near-duplicate review aid, not a proof."""
    import numpy as _np
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return ''
    small = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA).astype(_np.float64)
    bits = small > small.mean()
    return ''.join('1' if b else '0' for row in bits for b in row)

def hamming(a, b):
    return sum(c1 != c2 for c1, c2 in zip(a, b))

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('image_dir', type=Path)
    p.add_argument('--labels', type=Path)
    p.add_argument('--output', type=Path, default=Path('dataset_audit.csv'))
    a = p.parse_args()
    labels = {}
    if a.labels:
        with a.labels.open(newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                labels[row.get('image_id', '')] = row
    rows = []
    for path in sorted(x for x in a.image_dir.rglob('*') if x.is_file() and x.suffix.lower() in EXTS):
        digest = sha(path)
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        qa = assess_image(image)
        label = labels.get(path.stem, {})
        rows.append({"image_id": path.stem, "relative_path": str(path.relative_to(a.image_dir)),
                     "sha256": digest, "duplicate_sha256_count": 0,
                     "ahash8": ahash(path),
                     "patient_id": label.get('patient_id', ''), "hemoglobin": label.get('hemoglobin', ''),
                     "age": label.get('age', ''), "sex": label.get('sex', ''),
                     "pregnancy_status": label.get('pregnancy_status', ''),
                     "original_status": label.get('original_status', ''),
                     "label_present": bool(label), **qa})
    counts = {}
    for row in rows: counts[row['sha256']] = counts.get(row['sha256'], 0) + 1
    for row in rows: row['duplicate_sha256_count'] = counts[row['sha256']]
    # Near-duplicate grouping: union-find over aHash Hamming distance <= 5.
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    by_hash = [(i, r['ahash8']) for i, r in enumerate(rows) if r['ahash8']]
    for i in range(len(by_hash)):
        gi, gih = by_hash[i]
        for j in range(i + 1, len(by_hash)):
            gj, gjh = by_hash[j]
            if hamming(gih, gjh) <= 5:
                ri, rj = find(gi), find(gj)
                if ri != rj: parent[rj] = ri
    groups = {}
    for i in range(len(rows)):
        if rows[i]['ahash8']:
            groups.setdefault(find(i), []).append(i)
    near_groups = [g for g in groups.values() if len(g) > 1]
    near_id = {}
    for n, g in enumerate(near_groups, 1):
        for i in g: near_id[i] = n
    for i, row in enumerate(rows):
        row['near_duplicate_group'] = near_id.get(i, 0) or ''
    if rows:
        with a.output.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    else:
        a.output.write_text('', encoding='utf-8')
    patient_counts = {}
    for row in rows:
        pid = (row.get('patient_id') or '').strip()
        if pid: patient_counts[pid] = patient_counts.get(pid, 0) + 1
    summary = {"image_count": len(rows),
               "label_matched_count": sum(r['label_present'] for r in rows),
               "label_missing_count": sum(not r['label_present'] for r in rows),
               "qa_reject_count": sum(not r.get('usable', False) for r in rows),
               "qa_reject_reasons": {},
               "exact_duplicate_groups": sum(n > 1 for n in counts.values()),
               "near_duplicate_groups": len(near_groups),
               "patients": len(patient_counts),
               "patients_with_multiple_images": sum(1 for n in patient_counts.values() if n > 1),
               "output": str(a.output)}
    for row in rows:
        if not row.get('usable', False):
            summary["qa_reject_reasons"][row.get('reason') or 'unknown'] = summary["qa_reject_reasons"].get(row.get('reason') or 'unknown', 0) + 1
    print(json.dumps(summary))
if __name__ == '__main__': main()
