"""Evaluate the cone FFB intent (policy B) on the wide-ROI grid images.

Each image is fed three snapshots so the 3-consecutive side gate can confirm.
Known sides come from the operator-declared capture order. Offline only.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
SPEC = importlib.util.spec_from_file_location('cone_intent', ROOT / 'src/driver_cone_ffb_intent.py')
intent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intent)

CALIBRATION = dict(schema='lateral_calibration_table_v1',
                   distances=[1.0, 1.5, 2.0], cx_ref=[306.5, 308.2, 305.7],
                   k_left_m_per_px=[0.004158, 0.005945, 0.007732],
                   k_right_m_per_px=[0.003924, 0.005341, 0.006758])
ORDER = [
    (1.0, 0.00), (1.0, +0.25), (1.0, -0.25),
    (1.5, 0.00), (1.5, +0.25), (1.5, -0.25),
    (2.0, 0.00), (2.0, +0.25), (2.0, +0.25), (2.0, -0.25),
]
SPEED = 0.5


def load(archive):
    with tarfile.open(archive) as bundle:
        member = next(m for m in bundle.getmembers() if m.name.endswith('samples.jsonl'))
        rows = [json.loads(line) for line in bundle.extractfile(member).read().decode().splitlines()
                if line.strip()]
    images, seen = [], set()
    for row in rows:
        if row['variant'] != 'original':
            continue
        name = row['source_path'].split('/')[-1]
        if name in seen:
            continue
        seen.add(name)
        measurement = row['measurement']
        box = (measurement.get('selected_detector_boxes') or [{}])[0]
        images.append(dict(image=name, range_m=measurement.get('horizontal_camera_foot_range_m'),
                           box_center_x=None if box.get('x1') is None else (box['x1'] + box['x2']) / 2))
    return images


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
        raise SystemExit('unexpected image count')
    rows = []
    for index, (item, (nominal, known)) in enumerate(zip(images, ORDER)):
        unit = intent.ConeFfbIntent(CALIBRATION)
        result = None
        for step in range(3):
            result = unit.offer(item['range_m'], item['box_center_x'], SPEED, 0.0,
                                at_sec=index * 10.0 + 0.2 * (step + 1))
        expected = 0 if abs(known) < 0.05 else (-1 if known > 0 else 1)
        rows.append(dict(image=item['image'], nominal_m=nominal, known_left_m=known,
                         range_m=item['range_m'], box_center_x=item['box_center_x'],
                         left_m=result['left_m'], gradient=result['gradient'],
                         risk_level=result['risk_level'], direction=result['direction'],
                         magnitude=result['normalized_magnitude'], confirmed=result['confirmed'],
                         expected_direction=expected, mismatch=result['direction'] != expected,
                         reason=result['reason'], consistency_reason=result['consistency_reason']))
    active = [row for row in rows if row['risk_level'] in ('WARNING', 'CRITICAL', 'UNKNOWN')]
    evaluable = [row for row in active if row['range_m'] is not None]
    summary = dict(schema='cone_intent_grid_evaluation_v1',
                   images=len(rows), evaluable=len(evaluable),
                   inactive_or_no_range=len(rows) - len(evaluable),
                   direction_mismatches=sum(1 for row in evaluable if row['mismatch']),
                   confirmed=sum(1 for row in evaluable if row['confirmed']),
                   magnitude_min=min((row['magnitude'] for row in evaluable), default=0.0),
                   magnitude_max=max((row['magnitude'] for row in evaluable), default=0.0),
                   rows=rows, camera_or_gpu_used=False, physical_metric_verified=False,
                   usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'evaluation.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (output / 'cases.csv').open('w') as target:
        keys = ['image', 'nominal_m', 'known_left_m', 'range_m', 'box_center_x', 'left_m',
                'gradient', 'risk_level', 'direction', 'magnitude', 'confirmed',
                'expected_direction', 'mismatch', 'reason', 'consistency_reason']
        target.write(','.join(keys) + '\n')
        for row in rows:
            target.write(','.join(str(row[key]) for key in keys) + '\n')
    print(json.dumps({key: summary[key] for key in ('images', 'evaluable', 'inactive_or_no_range',
                                                    'direction_mismatches', 'confirmed',
                                                    'magnitude_min', 'magnitude_max')}, indent=2))


if __name__ == '__main__':
    main()
