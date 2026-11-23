"""Empirical pixel-to-lateral calibration from the wide-ROI yellow grid.

The cone distance pipeline gives a radial range but no left/right offset. This
script fits a per-distance scale k(d) from the operator-declared 0/+0.25/-0.25 m
positions and reports the residuals. It is a calibration for this mounting, not
a physical mount model.

Offline only; no camera, ROS or FFB.
"""
import argparse
import json
from pathlib import Path
import tarfile

import numpy as np

# capture order of the wide-ROI run: 1.0 m (C,L,R), 1.5 m (C,L,R), 2.0 m (C,L,L,R)
ORDER = [
    (1.0, 0.00), (1.0, +0.25), (1.0, -0.25),
    (1.5, 0.00), (1.5, +0.25), (1.5, -0.25),
    (2.0, 0.00), (2.0, +0.25), (2.0, +0.25), (2.0, -0.25),
]


def load(archive):
    with tarfile.open(archive) as bundle:
        member = next(m for m in bundle.getmembers() if m.name.endswith('samples.jsonl'))
        rows = [json.loads(line) for line in bundle.extractfile(member).read().decode().splitlines()
                if line.strip()]
    images = []
    for row in rows:
        if row['variant'] != 'original':
            continue
        name = row['source_path'].split('/')[-1]
        measurement = row['measurement']
        box = (measurement.get('selected_detector_boxes') or [{}])[0]
        images.append(dict(image=name, distance=measurement.get('horizontal_camera_foot_range_m'),
                           x1=box.get('x1'), x2=box.get('x2')))
    # keep first occurrence order, unique by name
    unique, seen = [], set()
    for item in images:
        if item['image'] not in seen:
            seen.add(item['image'])
            unique.append(item)
    return unique


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    images = load(args.archive)
    if len(images) < len(ORDER):
        raise SystemExit(f'expected {len(ORDER)} original images, got {len(images)}')
    points = []
    for item, (nominal, known) in zip(images, ORDER):
        box = None if item['x1'] is None else ((item['x1'] + item['x2']) / 2.0)
        points.append(dict(image=item['image'], nominal_m=nominal, known_left_m=known,
                           distance_m=item['distance'], box_center_x=box))
    # reference center per nominal group from the centre image
    references = {}
    for point in points:
        if point['known_left_m'] == 0.0 and point['box_center_x'] is not None:
            references[point['nominal_m']] = point['box_center_x']
    scales = []
    for point in points:
        if point['box_center_x'] is None or point['known_left_m'] == 0.0:
            continue
        reference = references.get(point['nominal_m'])
        if reference is None:
            continue
        offset = reference - point['box_center_x']
        if offset == 0:
            continue
        scales.append(dict(nominal_m=point['nominal_m'], side='L' if point['known_left_m'] > 0 else 'R',
                           offset_px=offset, known_left_m=point['known_left_m'],
                           k_m_per_px=point['known_left_m'] / offset))
    if not scales:
        raise SystemExit('no usable lateral points')
    x = np.array([item['nominal_m'] for item in scales])
    y = np.array([item['k_m_per_px'] for item in scales])
    slope, intercept = np.polyfit(x, y, 1) if len(set(x)) > 1 else (0.0, float(y.mean()))
    for point in points:
        reference = references.get(point['nominal_m'])
        if point['box_center_x'] is None or reference is None:
            point['estimated_left_m'] = None
            point['residual_m'] = None
            continue
        k = intercept + slope * point['nominal_m']
        point['estimated_left_m'] = round((reference - point['box_center_x']) * k, 4)
        point['residual_m'] = round(point['estimated_left_m'] - point['known_left_m'], 4)
    residuals = [point['residual_m'] for point in points if point['residual_m'] is not None]
    report = dict(schema='empirical_lateral_calibration_v1',
                  state='single_mounting_calibration_NOT_mount_model',
                  order_note='1.0 C/L/R, 1.5 C/L/R, 2.0 C/L/L/R (operator-declared capture order)',
                  references=references, scale_points=scales,
                  fit=dict(k_m_per_px_at_1m=round(float(intercept + slope), 6),
                           slope_m_per_px_per_m=round(float(slope), 6), intercept=round(float(intercept), 6)),
                  points=points,
                  residual_abs_max_m=round(max(abs(r) for r in residuals), 4),
                  residual_rms_m=round(float(np.sqrt(np.mean(np.square(residuals)))), 4),
                  camera_or_gpu_used=False, physical_metric_verified=False, usable_for_ffb=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'calibration.json').write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'points.csv').open('w') as target:
        target.write('image,nominal_m,known_left_m,distance_m,box_center_x,estimated_left_m,residual_m\n')
        for point in points:
            target.write(','.join(str(point[key]) for key in (
                'image', 'nominal_m', 'known_left_m', 'distance_m', 'box_center_x',
                'estimated_left_m', 'residual_m')) + '\n')
    print(json.dumps(dict(fit=report['fit'], residual_abs_max_m=report['residual_abs_max_m'],
                          residual_rms_m=report['residual_rms_m'], scales=scales), indent=2))


if __name__ == '__main__':
    main()
