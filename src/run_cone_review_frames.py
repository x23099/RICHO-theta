#!/usr/bin/env python3
"""Re-infer untouched, provenance-checked review PNGs; no GT, ROS or training."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import time
import sys

import cv2

from cone_dataset import read_csv, sha256, write_csv
from cone_detection_diagnostics import PRED_FIELDS, extract_predictions, prediction_kwargs
from run_cone_yolo import check_cuda


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, help='Optional read-only manifest outside input-dir; file paths remain input-relative')
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--imgsz', type=int, default=960)
    parser.add_argument('--prediction-floor', type=float, default=.01)
    parser.add_argument('--nms-iou', type=float, default=.7)
    parser.add_argument('--max-det', type=int, default=300)
    parser.add_argument('--dry-run', action='store_true')
    return parser


def validate_args(args):
    if args.device < 0 or args.imgsz < 32 or args.imgsz % 32 or args.max_det < 1:
        raise ValueError('GPU device>=0, imgsz multiple of32, max_det>=1 required')
    if not all(math.isfinite(v) and 0 < v <= 1 for v in (args.prediction_floor, args.nms_iou)):
        raise ValueError('finite confidence/IoU in (0,1] required')
    for name in ('input_dir', 'weights', 'output_dir'):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    args.manifest = (args.manifest.expanduser().resolve() if args.manifest
                     else args.input_dir / 'raw_review_manifest.csv')
    if not args.weights.is_file() or args.output_dir.exists():
        raise ValueError('existing local checkpoint and NEW output directory required')
    if (args.output_dir.is_relative_to(args.input_dir) or args.input_dir.is_relative_to(args.output_dir)
            or args.output_dir.is_relative_to(args.weights.parent)
            or args.weights.is_relative_to(args.output_dir)):
        raise ValueError('output must not overlap original images/checkpoint')
    if not args.manifest.is_file() or args.manifest.is_relative_to(args.output_dir):
        raise ValueError('existing read-only manifest outside new output required')
    return args


def verify_frame(root, row):
    relative = Path(row['file'])
    path = (root / relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root):
        raise ValueError('review image must stay inside input directory')
    if (root / relative).is_symlink() or not path.is_file():
        raise ValueError('regular review PNG required')
    if sha256(path) != row['png_sha256']:
        raise ValueError('original PNG hash mismatch')
    pixels = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if pixels is None or pixels.shape != (int(row['height']), int(row['width']), 3):
        raise ValueError('original image geometry mismatch')
    if hashlib.sha256(pixels.tobytes()).hexdigest() != row['decoded_bgr_sha256']:
        raise ValueError('original decoded pixels mismatch')
    return path, pixels


def load_manifest(root, manifest_path=None):
    rows = read_csv(manifest_path or root / 'raw_review_manifest.csv')
    required = {'file','session','frame','time_sec','width','height','png_sha256',
                'decoded_bgr_sha256','source_raw_sha256','reason'}
    if not rows or any(required - row.keys() for row in rows):
        raise ValueError('nonempty complete raw review manifest required')
    seen_files, seen_frames = set(), set()
    for row in rows:
        key = (row['session'], int(row['frame']))
        if row['file'] in seen_files or key in seen_frames:
            raise ValueError('duplicate review file/session-frame')
        seen_files.add(row['file']); seen_frames.add(key)
        if (not row['session'] or key[1] < 1 or min(int(row['width']), int(row['height'])) < 1
                or not math.isfinite(float(row['time_sec'])) or float(row['time_sec']) < 0):
            raise ValueError('invalid review metadata')
        if any(len(row[name]) != 64 or any(c not in '0123456789abcdef' for c in row[name])
               for name in ('png_sha256','decoded_bgr_sha256','source_raw_sha256')):
            raise ValueError('valid SHA256 provenance required')
        verify_frame(root, row)
    return rows


def infer_frames(model, args, images):
    predictions, timings = [], []
    for index, image in enumerate(images):
        path, pixels = verify_frame(args.input_dir, image)
        started = time.perf_counter()
        results = model.predict(source=pixels, **prediction_kwargs(args))
        if len(results) != 1:
            raise ValueError('exactly one result per original frame required')
        rows = extract_predictions(results[0], dict(image, image=image['file']))
        if len(rows) > args.max_det or any(r['confidence'] < args.prediction_floor - 1e-7 for r in rows):
            raise ValueError('prediction floor/max_det contract violated')
        speeds = [results[0].speed[name] for name in ('preprocess', 'inference', 'postprocess')]
        if any(not math.isfinite(v) or v < 0 for v in speeds):
            raise ValueError('invalid detector timing')
        predictions.extend(rows)
        timings.append(dict(image=image['file'], session=image['session'], frame=image['frame'],
            time_sec=image['time_sec'], first_call=int(index == 0), predictions=len(rows),
            max_det_reached=int(len(rows) == args.max_det), predict_export_ms=(time.perf_counter()-started)*1000,
            preprocess_ms=speeds[0], inference_ms=speeds[1], postprocess_ms=speeds[2]))
        verify_frame(args.input_dir, image)  # Refuse a successful result if inference changed inputs.
        print(f"[INFO] Review {index+1}/{len(images)} frame={image['frame']}: {len(rows)} candidates", flush=True)
    write_csv(args.output_dir / 'predictions.csv', predictions, PRED_FIELDS)
    write_csv(args.output_dir / 'timing.csv', timings)
    return dict(status='COMPLETED_SELECTED_FRAMES_NOT_ACCURACY_OR_DEPLOYMENT_APPROVAL',
                images=len(images), predictions=len(predictions), original_pixels_verified=True,
                max_det_reached_images=sum(row['max_det_reached'] for row in timings),
                physical_output=False, training_performed=False,
                limitations=['Selected failure/jump examples, not independent or unbiased test images.',
                             'Candidate existence is not a TP without object/location review.',
                             'The single traffic_cone class includes yellow and red cones.',
                             'A visible/lifted cone does not establish a valid floor contact point.'])


def main():
    parser = build_parser()
    try:
        args = validate_args(parser.parse_args())
        images = load_manifest(args.input_dir, args.manifest)
        if args.dry_run:
            print(json.dumps(dict(status='PREVIEW_ONLY_NOT_GPU_VERIFIED', images=len(images),
                                  prediction_kwargs=prediction_kwargs(args)), indent=2)); return
        import torch
        gpu = check_cuda(torch, args.device)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / 'ultralytics_config/Ultralytics').mkdir(parents=True)
        os.environ['YOLO_CONFIG_DIR'] = str(args.output_dir / 'ultralytics_config')
        from ultralytics import YOLO, settings
        for key in ('wandb','comet','clearml','mlflow','neptune','hub'):
            if key in settings: settings.update({key:False})
        model = YOLO(str(args.weights))
        if model.names != {0:'traffic_cone'}:
            raise ValueError('trained single-class traffic_cone detector required')
        provenance = dict(status='STARTED_SELECTED_FRAMES_NOT_APPROVAL', gpu=gpu,
            input_dir=str(args.input_dir), weights=str(args.weights), weights_sha256=sha256(args.weights),
            manifest_path=str(args.manifest), manifest_sha256=sha256(args.manifest), images=images,
            prediction_kwargs=prediction_kwargs(args),
            versions={name:importlib.metadata.version(name) for name in ('torch','torchvision','ultralytics','opencv-python')},
            code_sha256={name:sha256(Path(__file__).with_name(name)) for name in
                         ('run_cone_review_frames.py','cone_detection_diagnostics.py','run_cone_yolo.py','cone_dataset.py')},
            training_performed=False, physical_output=False)
        target = args.output_dir / 'provenance.json'
        target.write_text(json.dumps(provenance, indent=2)+'\n')
        (args.output_dir / 'environment_freeze.txt').write_text(subprocess.check_output(
            [sys.executable,'-m','pip','freeze'], text=True))
        report = infer_frames(model, args, images)
        if sha256(args.weights) != provenance['weights_sha256'] or sha256(args.manifest) != provenance['manifest_sha256']:
            raise ValueError('checkpoint/manifest changed during diagnostics')
        provenance['status'] = report['status']; target.write_text(json.dumps(provenance, indent=2)+'\n')
        (args.output_dir / 'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, KeyError, ImportError) as error:
        parser.exit(2, f'[ERROR] {error}\n')


if __name__ == '__main__':
    main()
