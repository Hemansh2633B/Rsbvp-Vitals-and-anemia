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
                     "patient_id": label.get('patient_id', ''), "hemoglobin": label.get('hemoglobin', ''),
                     "age": label.get('age', ''), "sex": label.get('sex', ''),
                     "pregnancy_status": label.get('pregnancy_status', ''),
                     "original_status": label.get('original_status', ''),
                     "label_present": bool(label), **qa})
    counts = {}
    for row in rows: counts[row['sha256']] = counts.get(row['sha256'], 0) + 1
    for row in rows: row['duplicate_sha256_count'] = counts[row['sha256']]
    if rows:
        with a.output.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    else:
        a.output.write_text('', encoding='utf-8')
    print(json.dumps({"image_count": len(rows), "label_matched_count": sum(r['label_present'] for r in rows),
                      "exact_duplicate_groups": sum(n > 1 for n in counts.values()), "output": str(a.output)}))
if __name__ == '__main__': main()
