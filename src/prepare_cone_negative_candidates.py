#!/usr/bin/env python3
"""Export unlabelled whole-frame background candidates, never automatic negatives."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import cv2

from cone_dataset import (ID, REVIEW_FIELDS, dataset_yaml, integer, label_path, parse_label,
                          read_csv, sha256, validate, verify_image, write_csv)

PURPOSE = 'unlabelled legacy background review queue; NOT trainable dataset'


def load_plan(path):
    path = Path(path).resolve()
    rows = read_csv(path)
    required = {'session_dir', 'group_id', 'samples', 'notes'}
    if not rows or any(required - row.keys() for row in rows):
        raise ValueError('nonempty session_dir/group_id/samples/notes plan required')
    sessions, result = set(), []
    for row in rows:
        if not row['session_dir'].strip() or not ID.fullmatch(row['group_id']):
            raise ValueError('existing session and ASCII capture group required')
        session = Path(row['session_dir']).expanduser()
        session = (path.parent / session).resolve() if not session.is_absolute() else session.resolve()
        if session in sessions or not row['notes'].strip():
            raise ValueError('unique sessions and explicit capture-context notes required')
        sessions.add(session)
        result.append(dict(row, session_dir=str(session), samples=integer(row['samples'], 'samples')))
    return result


def sample_frames(count, samples):
    if count < 1 or samples < 1 or samples > count:
        raise ValueError('samples must be between 1 and video/CSV frame count')
    if samples == 1:
        return [1 + (count - 1) // 2]
    return [1 + round(i * (count - 1) / (samples - 1)) for i in range(samples)]


def prepare(plan_path, reference, output):
    reference, output = Path(reference).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('NEW output required; no overwrite')
    validate(reference)
    plan = load_plan(plan_path)
    if any(output.is_relative_to(p) or p.is_relative_to(output)
           for p in [reference] + [Path(row['session_dir']) for row in plan]):
        raise ValueError('output must not overlap reference/source sessions')
    baseline = read_csv(reference / 'manifest.csv')
    existing_videos = {row['source_raw_sha256'] for row in baseline}
    existing_groups = {row['group_id'] for row in baseline}
    existing_pixels = {row['decoded_bgr_sha256'] for row in baseline}
    input_hashes = {str(reference / name): sha256(reference / name)
                    for name in ('manifest.csv', 'reviews.csv', 'dataset.json')}
    sources, exported, seen_videos, seen_pixels = [], [], set(), set()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cone_background_', dir=output.parent) as temporary:
        stage = Path(temporary) / 'queue'
        (stage / 'images/train').mkdir(parents=True)
        (stage / 'labels/train').mkdir(parents=True)
        for entry in plan:
            session = Path(entry['session_dir'])
            files = [session / name for name in ('raw.avi', 'metadata.json', 'detections.csv')]
            if any(not p.is_file() or p.is_symlink() for p in files):
                raise ValueError('regular raw.avi/metadata.json/detections.csv required')
            hashes = {p.name: sha256(p) for p in files}
            if (hashes['raw.avi'] in existing_videos | seen_videos
                    or entry['group_id'] in existing_groups):
                raise ValueError('candidate source/group overlaps existing cone data or duplicate video')
            seen_videos.add(hashes['raw.avi'])
            metadata = json.loads(files[1].read_text())
            width = integer(metadata['requested_camera_width'], 'width')
            height = integer(metadata['requested_camera_height'], 'height')
            rows = read_csv(files[2])
            if not rows or [int(row['frame']) for row in rows] != list(range(1, len(rows) + 1)):
                raise ValueError('CSV requires contiguous one-based frame IDs')
            times = [float(row['time_sec']) for row in rows]
            if (any(not math.isfinite(t) or t < 0 for t in times)
                    or any(b <= a for a, b in zip(times, times[1:]))):
                raise ValueError('finite increasing recording times required')
            selected = set(sample_frames(len(rows), entry['samples']))
            capture = cv2.VideoCapture(str(files[0]))
            try:
                if not capture.isOpened():
                    raise ValueError('cannot open raw video')
                for number in range(1, len(rows) + 1):
                    ok, frame = capture.read()
                    if not ok or frame.shape != (height, width, 3):
                        raise ValueError('video shorter than CSV or geometry mismatch')
                    if number not in selected:
                        continue
                    digest = hashlib.sha256(frame.tobytes()).hexdigest()
                    if digest in existing_pixels | seen_pixels:
                        raise ValueError('candidate pixels duplicate existing data or another candidate')
                    seen_pixels.add(digest)
                    image = f"images/train/{entry['group_id']}_{hashes['raw.avi'][:16]}_f{number:06d}.png"
                    target = stage / image
                    if target.exists() or not cv2.imwrite(str(target), frame):
                        raise ValueError('image naming collision or PNG export failure')
                    saved = cv2.imread(str(target))
                    if saved is None or hashlib.sha256(saved.tobytes()).hexdigest() != digest:
                        raise ValueError('export changed raw pixels')
                    exported.append(dict(image=image, split='train', group_id=entry['group_id'],
                        session=session.name, frame=number, time_sec=times[number-1], width=width,
                        height=height, png_sha256=sha256(target), decoded_bgr_sha256=digest,
                        source_raw_sha256=hashes['raw.avi']))
                if capture.read()[0]:
                    raise ValueError('video longer than CSV')
            finally:
                capture.release()
            if any(sha256(p) != hashes[p.name] for p in files):
                raise ValueError('source changed during export')
            sources.append(dict(entry, sha256=hashes, decoded_frames=len(rows)))
        if any(sha256(Path(path)) != expected for path, expected in input_hashes.items()):
            raise ValueError('reference changed during export')
        write_csv(stage / 'manifest.csv', exported)
        write_csv(stage / 'raw_review_manifest.csv', [dict(row, file=row['image'],
            reason='time-based background candidate; cone absence NOT established') for row in exported])
        write_csv(stage / 'reviews.csv', [dict(image=row['image'], status='pending', note='',
            label_sha256='') for row in exported], REVIEW_FIELDS)
        summary = dict(schema_version=1, classes=['traffic_cone'], available_splits=['train'],
            development_only=True, purpose=PURPOSE,
            manifest_sha256=sha256(stage / 'manifest.csv'), plan_sha256=sha256(plan_path),
            reference_dataset=str(reference), reference_input_sha256=input_hashes,
            sources=sources, images=len(exported), script_sha256=sha256(Path(__file__)),
            automatic_labels_created=False, data_yaml_created=False, training_performed=False,
            independent_test=False, image_policy='whole original-resolution raw frame; unchanged BGR pixels',
            review_required='Human must check BOTH lenses; visible red/yellow cones are positives, ambiguity stays pending',
            leakage_limit='Hashes reject identical source/pixels; capture similarity and undisclosed overlap need human review')
        (stage / 'dataset.json').write_text(json.dumps(summary, indent=2) + '\n')
        stage.rename(output)
    return summary


def merge_negatives(queue, reference, output):
    """Add ONLY explicitly human-reviewed empty labels; keep other candidates held."""
    queue, reference, output = [Path(p).resolve() for p in (queue, reference, output)]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in (queue, reference)):
        raise ValueError('NEW output outside input datasets required')
    validate(reference)
    metadata = json.loads((queue / 'dataset.json').read_text())
    if (metadata.get('purpose') != PURPOSE or metadata.get('classes') != ['traffic_cone']
            or Path(metadata['reference_dataset']).resolve() != reference
            or sha256(queue / 'manifest.csv') != metadata['manifest_sha256']):
        raise ValueError('intact background queue from exact reference required')
    for path, expected in metadata['reference_input_sha256'].items():
        if sha256(path) != expected:
            raise ValueError('reference changed since queue preparation')
    for source in metadata['sources']:
        for name, expected in source['sha256'].items():
            if sha256(Path(source['session_dir']) / name) != expected:
                raise ValueError('raw source changed since queue preparation')
    rows, reviews = read_csv(queue / 'manifest.csv'), read_csv(queue / 'reviews.csv')
    by_image = {r['image']:r for r in reviews}
    if (len(by_image) != len(reviews) or len({r['image'] for r in rows}) != len(rows)
            or set(by_image) != {r['image'] for r in rows}):
        raise ValueError('complete unique candidate/review tables required')
    reference_meta = json.loads((reference / 'dataset.json').read_text())
    baseline = read_csv(reference / 'manifest.csv')
    groups = {r['group_id'] for r in baseline}
    videos = {r['source_raw_sha256'] for r in baseline}
    pixels = {r['decoded_bgr_sha256'] for r in baseline}
    existing_images = {r['image'] for r in baseline}
    additions, added_reviews, held = [], [], []
    for row in rows:
        verify_image(queue, row)
        if (row['split'] != 'train' or row['group_id'] in groups or row['source_raw_sha256'] in videos
                or row['decoded_bgr_sha256'] in pixels or row['image'] in existing_images):
            raise ValueError('new unique train capture group/video/pixels required')
        pixels.add(row['decoded_bgr_sha256']); existing_images.add(row['image'])
        review = by_image[row['image']]
        if review['status'] not in ('pending', 'positive', 'negative'):
            raise ValueError('unsupported review status')
        if review['status'] != 'negative':
            held.append(dict(image=row['image'], reason='not explicitly confirmed negative', status=review['status']))
            continue
        label = label_path(queue, row['image'])
        if (not review['note'].startswith('human full-frame review:') or not label.is_file()
                or label.is_symlink() or sha256(label) != review['label_sha256'] or parse_label(label)):
            raise ValueError('negative needs explicit current human full-frame review and empty label')
        additions.append(row); added_reviews.append(review)
    expected_labels = {str(label_path(queue, r['image']).relative_to(queue)) for r in rows}
    if ({str(p.relative_to(queue)) for p in (queue / 'images').rglob('*') if p.is_file()} != {r['image'] for r in rows}
            or not {str(p.relative_to(queue)) for p in (queue / 'labels').rglob('*') if p.is_file()}.issubset(expected_labels)):
        raise ValueError('unmanifested queue images/labels forbidden')
    if not additions:
        raise ValueError('no human-confirmed negatives; no training dataset produced')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cone_negative_merge_', dir=output.parent) as temporary:
        stage = Path(temporary) / 'dataset'
        for split in reference_meta['available_splits']:
            (stage / 'images' / split).mkdir(parents=True)
            (stage / 'labels' / split).mkdir(parents=True)
        for source, manifest in ((reference, baseline), (queue, additions)):
            for row in manifest:
                shutil.copyfile(source / row['image'], stage / row['image'])
                shutil.copyfile(label_path(source, row['image']), label_path(stage, row['image']))
                if (sha256(stage / row['image']) != sha256(source / row['image'])
                        or sha256(label_path(stage, row['image'])) != sha256(label_path(source, row['image']))):
                    raise ValueError('copy changed original image/label')
        write_csv(stage / 'manifest.csv', baseline + additions)
        write_csv(stage / 'reviews.csv', read_csv(reference / 'reviews.csv') + added_reviews)
        merged_meta = dict(reference_meta, manifest_sha256=sha256(stage / 'manifest.csv'),
            sources=reference_meta.get('sources', []) + metadata['sources'],
            negative_augmentation=dict(queue=str(queue), queue_manifest_sha256=sha256(queue / 'manifest.csv'),
                queue_reviews_sha256=sha256(queue / 'reviews.csv'), added=len(additions), held=held,
                reference_input_sha256=metadata['reference_input_sha256'], script_sha256=sha256(Path(__file__)),
                val_test_unchanged=True, independent_test_added=False))
        (stage / 'dataset.json').write_text(json.dumps(merged_meta, indent=2) + '\n')
        (stage / 'data.yaml').write_text(dataset_yaml(stage, development_only=reference_meta['development_only']))
        validate(stage)
        (stage / 'data.yaml').write_text(dataset_yaml(output, development_only=reference_meta['development_only']))
        stage.rename(output)
    result = validate(output)
    result.update(negative_images_added=len(additions), candidates_held=len(held), val_test_unchanged=True,
                  training_performed=False)
    (output / 'merge_verification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--merge-reviewed-queue', type=Path,
                        help='Merge ONLY explicitly human-confirmed negatives; other images stay held')
    parser.add_argument('--reference-dataset', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.plan) == bool(args.merge_reviewed_queue):
        parser.error('specify exactly one of --plan or --merge-reviewed-queue')
    try:
        if args.plan:
            result = prepare(args.plan, args.reference_dataset, args.output_dir)
            result = dict(images=result['images'], status='PENDING_HUMAN_REVIEW_NOT_NEGATIVE_LABELS')
        else:
            result = merge_negatives(args.merge_reviewed_queue, args.reference_dataset, args.output_dir)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f'[ERROR] {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
