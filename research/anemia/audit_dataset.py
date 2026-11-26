#!/usr/bin/env python3
"""Inventory actual local image files; never downloads or synthesizes dataset records.

Optional labels CSV must contain image_id and may include patient_id, hemoglobin,
sex, age, pregnancy_status and original_status. Output CSV includes hashes for
near-duplicate review. Protect output as potentially sensitive research metadata.

The summary reports *risks*, not just counts. A dataset can look clean (every
image present, every hash unique) while still being unusable for a supervised
experiment: missing laboratory Hb, missing participant identifiers, the same
participant on both sides of a future split, or the same eye photographed twice.
Those are reported explicitly by :func:`audit_rows` so they cannot be discovered
only after a training run.
"""
import argparse, csv, hashlib, json, math, sys
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

#: A hemoglobin value outside this sanity window is treated as a data defect.
#: This is NOT a clinical threshold and NOT an anaemia cut-off: it only separates
#: "a laboratory value was recorded" from "a typo or a placeholder".
HB_SANITY_G_DL = (1.0, 25.0)


def _hb_status(raw):
    """Classify one hemoglobin cell: ('present', value) | ('missing', None) | ('invalid', None)."""
    text = (raw or '').strip()
    if not text:
        return 'missing', None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return 'invalid', None
    if not math.isfinite(value) or not (HB_SANITY_G_DL[0] <= value <= HB_SANITY_G_DL[1]):
        return 'invalid', None
    return 'present', value


def audit_rows(rows):
    """Dataset-level risks that matter before any training attempt.

    Returns a dict of counts plus the identifiers behind each risk, so the report
    is actionable ("which participants", not just "how many"). Nothing here
    changes the data; the audit only describes it.
    """
    hb_present = [r for r in rows if _hb_status(r.get('hemoglobin'))[0] == 'present']
    hb_missing = [r for r in rows if _hb_status(r.get('hemoglobin'))[0] == 'missing']
    hb_invalid = [r for r in rows if _hb_status(r.get('hemoglobin'))[0] == 'invalid']

    patient_ids = [(r.get('patient_id') or '').strip() for r in rows]
    unlabelled_patient = [r['image_id'] for r, pid in zip(rows, patient_ids) if not pid]
    patient_counts = {}
    for pid in patient_ids:
        if pid:
            patient_counts[pid] = patient_counts.get(pid, 0) + 1

    # Exact duplicates: identical bytes under different names are one image.
    by_sha = {}
    for r in rows:
        by_sha.setdefault(r.get('sha256', ''), []).append(r['image_id'])
    exact_groups = {h: ids for h, ids in by_sha.items() if h and len(ids) > 1}

    # Near duplicates are a *review* signal only (aHash collisions are possible).
    near_groups = {}
    for r in rows:
        group = r.get('near_duplicate_group')
        if group:
            near_groups.setdefault(group, []).append(r['image_id'])

    # Label records that exist but cannot be joined to an image (image_id drift).
    unmatched_labels = sorted(
        {label for row in rows for label in (row.get('unmatched_label_ids') or [])})

    # A participant whose images disagree on Hb cannot be used at participant
    # level without a documented rule.
    conflicting_hb = []
    for pid in patient_counts:
        values = {_hb_status(r.get('hemoglobin'))[1] for r in rows
                  if (r.get('patient_id') or '').strip() == pid}
        values.discard(None)
        if len(values) > 1:
            conflicting_hb.append(pid)

    blockers = []
    if hb_missing or hb_invalid:
        blockers.append('hemoglobin_not_available_for_every_image')
    if unlabelled_patient:
        blockers.append('patient_id_missing')
    if exact_groups:
        blockers.append('exact_duplicate_images')
    if conflicting_hb:
        blockers.append('inconsistent_hemoglobin_per_participant')

    return {
        'image_count': len(rows),
        'hemoglobin_present_count': len(hb_present),
        'hemoglobin_missing_count': len(hb_missing),
        'hemoglobin_invalid_count': len(hb_invalid),
        'hemoglobin_missing_image_ids': [r['image_id'] for r in hb_missing][:50],
        'hemoglobin_invalid_image_ids': [r['image_id'] for r in hb_invalid][:50],
        'patient_id_missing_count': len(unlabelled_patient),
        'patient_id_missing_image_ids': unlabelled_patient[:50],
        'patients': len(patient_counts),
        'patients_with_multiple_images': sum(1 for n in patient_counts.values() if n > 1),
        'exact_duplicate_groups': len(exact_groups),
        'exact_duplicate_image_ids': [ids for ids in exact_groups.values()][:20],
        'near_duplicate_groups': len(near_groups),
        'near_duplicate_image_ids': list(near_groups.values())[:20],
        'unmatched_label_count': len(unmatched_labels),
        'unmatched_label_ids': unmatched_labels[:50],
        'participants_with_conflicting_hemoglobin': conflicting_hb[:50],
        'supervised_training_blockers': blockers,
        'supervised_training_ready': not blockers,
    }


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
    # Dataset-level risks (missing Hb, missing participant ids, duplicates,
    # participant leakage, label join drift). Reported, never repaired.
    summary["risks"] = audit_rows(rows)
    if a.labels and labels:
        seen = {row['image_id'] for row in rows}
        summary["risks"]["unmatched_label_count"] = len(set(labels) - seen)
        summary["risks"]["unmatched_label_ids"] = sorted(set(labels) - seen)[:50]
    print(json.dumps(summary))
if __name__ == '__main__': main()
