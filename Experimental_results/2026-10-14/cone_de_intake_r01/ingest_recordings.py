#!/usr/bin/env python3
"""Fixed D/E recording intake; whole-frame samples, no labels or model adoption."""
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import cv2
from analyze_field_recording import safe_extract_archive
from cone_dataset import read_csv, sha256, write_csv
from inventory_recording_archives import inspect_archive, OUTPUT_FIELDS
from prepare_cone_negative_candidates import prepare, sample_frames

CAPTURES = [
    ('d01', 'train', 'cone_negative_train_d01_c_20261014_164134_986'),
    ('d02', 'train', 'cone_negative_train_d02_c_20261014_164419_986'),
    ('e01', 'val', 'cone_negative_eval_e01_c_20261014_164701_256'),
    ('e02', 'val', 'cone_positive_eval_e02_c_20261014_165209_894'),
    ('e03', 'val', 'cone_positive_eval_e03_c_20261014_165444_176'),
]


def main():
    output = Path(__file__).resolve().parent
    ingest = ROOT / 'recordings/2026-10-14_cone_ingest_de'
    evaluation = ROOT / 'datasets/cone/de_evaluation_review_v01'
    train_queue = ROOT / 'datasets/cone/de_negative_train_review_v01'
    if any(p.exists() for p in (ingest, evaluation, train_queue, output / 'input_inventory.json')):
        raise ValueError('new intake/queue outputs required; do not overwrite past runs')
    # Freeze the comparison BEFORE examining model predictions on E.
    models = {name: dict(path=str(ROOT / path), sha256=sha256(ROOT / path)) for name, path in [
        ('baseline_35', 'runs/cone/train_ab_baseline_local_20261014_r01/yolov8n/weights/best.pt'),
        ('augmented_36', 'runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt')]}
    (output / 'frozen_comparison.json').write_text(json.dumps(dict(models=models,
        confidence_thresholds=[.25, .5], prediction_floor=.01, nms_iou=.7, imgsz=960,
        selection='8 equally spaced whole frames per session, determined before model inference',
        use='D train review, E same-room separate-capture evaluation; E never training',
        user_note='E02 kept as fixed-position coverage; E03 adds repositioned coverage',
        limitations='No independent-background claim; repeated comparisons/tuning make E development evaluation',
        source_script_sha256=sha256(Path(__file__))), indent=2) + '\n')
    ingest.mkdir(parents=True)
    (evaluation / 'images/val').mkdir(parents=True)
    (evaluation / 'labels/val').mkdir(parents=True)
    inventory, integrity, evaluations, training_plan, video_plan = [], [], [], [], []
    existing = read_csv(ROOT / 'datasets/cone/ab_bootstrap_augmented_v03/manifest.csv')
    prior_video = {r['source_raw_sha256'] for r in existing}
    prior_pixels = {r['decoded_bgr_sha256'] for r in existing}
    seen_video, seen_pixels = set(), set()
    for key, split, stem in CAPTURES:
        archive = Path('/home/robo25/Downloads') / (stem + '.tar.xz')
        item = inspect_archive(archive)
        if item['tar_xz_status'] != 'PASS' or item['complete_core_sessions'] != 1:
            raise ValueError('each archive must contain exactly one complete recording session')
        inventory.append(item)
        destination = ingest / key
        safe_extract_archive(archive, destination, 3 * 1024**3)
        sessions = [p.parent for p in destination.rglob('raw.avi') if
                    all((p.parent / name).is_file() for name in ('metadata.json', 'detections.csv'))]
        if len(sessions) != 1:
            raise ValueError('unique complete raw session required')
        session = sessions[0]
        if session.name != stem:
            raise ValueError(f'archive/session identity mismatch: {session.name} != {stem}')
        hashes = {name:sha256(session / name) for name in ('raw.avi', 'metadata.json', 'detections.csv')}
        if hashes['raw.avi'] in prior_video | seen_video:
            raise ValueError('source duplicates existing cone dataset or another new session')
        seen_video.add(hashes['raw.avi'])
        rows = read_csv(session / 'detections.csv')
        times = [float(r['time_sec']) for r in rows]
        if (not rows or [int(r['frame']) for r in rows] != list(range(1, len(rows)+1))
                or any(not math.isfinite(t) or t < 0 for t in times)
                or any(b <= a for a,b in zip(times,times[1:]))):
            raise ValueError('contiguous frames and finite increasing times required')
        meta = json.loads((session / 'metadata.json').read_text())
        width, height = int(meta['requested_camera_width']), int(meta['requested_camera_height'])
        selected = set(sample_frames(len(rows), 8))
        capture = cv2.VideoCapture(str(session / 'raw.avi'))
        if not capture.isOpened():
            raise ValueError('cannot decode source')
        try:
            for number in range(1, len(rows)+1):
                ok, frame = capture.read()
                if not ok or frame.shape != (height,width,3):
                    raise ValueError('CSV/video length or recorded resolution mismatch')
                if number not in selected or split != 'val':
                    continue
                digest = hashlib.sha256(frame.tobytes()).hexdigest()
                if digest in prior_pixels | seen_pixels:
                    raise ValueError('evaluation pixels duplicate old/new data')
                seen_pixels.add(digest)
                image = f"images/val/block_e_20261014_{hashes['raw.avi'][:16]}_f{number:06d}.png"
                path = evaluation / image
                if path.exists() or not cv2.imwrite(str(path),frame):
                    raise ValueError('PNG export failed/collision')
                saved = cv2.imread(str(path))
                if saved is None or hashlib.sha256(saved.tobytes()).hexdigest() != digest:
                    raise ValueError('PNG changed original pixels')
                evaluations.append(dict(image=image,split='val',group_id='block_e_20261014',session=session.name,
                    frame=number,time_sec=times[number-1],width=width,height=height,png_sha256=sha256(path),
                    decoded_bgr_sha256=digest,source_raw_sha256=hashes['raw.avi']))
            if capture.read()[0]:
                raise ValueError('video longer than CSV')
        finally:
            capture.release()
        if any(sha256(session / name) != digest for name,digest in hashes.items()):
            raise ValueError('source changed during intake')
        item.update(key=key,split=split,group_id=f'block_{"d" if split=="train" else "e"}_20261014',
            session_dir=str(session),hashes=hashes,metadata=meta,selected_frames=sorted(selected))
        interval = times[-1]-times[0]
        integrity.append(dict(key=key,session=session.name,role=split,frames=len(rows),
            duration_sec=times[-1],sample_read_rate_fps=(len(rows)-1)/interval if interval>0 else '',
            width=width,height=height,raw_sha256=hashes['raw.avi'],video_csv_count_match=True,
            ai_enabled=meta['parameters'].get('enable_ai'),
            ffb_publish_enabled=meta['parameters'].get('collision_ffb_publish_enabled'),
            ffb_relay_enabled=meta['parameters'].get('collision_ffb_relay_enabled')))
        video_plan.append(dict(session_dir=str(session),note=f'{key}; {split}; no human GT yet'))
        if split == 'train':
            training_plan.append(dict(session_dir=str(session),group_id='block_d_20261014',samples=8,
                notes='User-designated negative training recording; both-lens absence still needs image review'))
        print(f"[INFO] {key}: {len(rows)} frames, {times[-1]:.2f}s, full raw decode/CSV PASS",flush=True)
    write_csv(evaluation / 'manifest.csv',evaluations)
    write_csv(evaluation / 'raw_review_manifest.csv',[dict(r,file=r['image'],
        reason='fixed time-based E evaluation sample; NOT training or automatic ground truth') for r in evaluations])
    write_csv(evaluation / 'reviews.csv',[dict(image=r['image'],status='pending',note='',label_sha256='') for r in evaluations])
    (evaluation / 'dataset.json').write_text(json.dumps(dict(schema_version=1,classes=['traffic_cone'],
        available_splits=['val'],development_only=True,purpose='evaluation-only human review queue; NOT training dataset',
        manifest_sha256=sha256(evaluation / 'manifest.csv'),sources=[r for r in inventory if r['split']=='val'],
        image_policy='whole original-resolution raw PNG; no edits',automatic_labels_created=False,
        independent_test=False,data_yaml_created=False),indent=2)+'\n')
    write_csv(output / 'training_candidate_plan.csv',training_plan)
    prepare(output / 'training_candidate_plan.csv',ROOT / 'datasets/cone/ab_bootstrap_augmented_v03',train_queue)
    drows = read_csv(train_queue / 'manifest.csv')
    if {r['decoded_bgr_sha256'] for r in drows} & {r['decoded_bgr_sha256'] for r in evaluations}:
        raise ValueError('D/E selected pixels overlap')
    write_csv(output / 'session_integrity.csv',integrity)
    write_csv(output / 'video_plan.csv',video_plan)
    write_csv(output / 'archive_inventory.csv',[{k:r[k] for k in OUTPUT_FIELDS} for r in inventory],OUTPUT_FIELDS)
    write_csv(output / 'selected_manifest.csv',drows+evaluations)
    (output / 'input_inventory.json').write_text(json.dumps(dict(status='PASS_RECORDING_INTEGRITY_NOT_CONE_MODEL_ACCURACY',
        inputs=inventory,train_queue=str(train_queue),evaluation_queue=str(evaluation),
        selected_train_images=len(drows),selected_evaluation_images=len(evaluations),
        d_e_raw_and_selected_pixel_overlap=0,labels_created=False,training_performed=False,
        frozen_comparison_sha256=sha256(output / 'frozen_comparison.json')),indent=2)+'\n')


if __name__ == '__main__':
    main()
