"""Offline gradient dry-run from measured yellow-cone distances.

Uses the real measured ranges from the wide-ROI grid (operator-declared
center/left/right at 1.0/1.5/2.0 m) and checks:
  1. whether the gradient direction matches the cone side,
  2. how close the gradient is to the deadband (FFB inactive),
  3. how small distance jitter affects the direction at fixed steering.

No camera, vehicle, ROS or FFB.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from collision_risk import evaluate_candidate_steering, gradient_to_direction

WIDTH_M = 0.354
SPEEDS = (0.2, 0.4, 0.8)
YAWS = (-0.3, -0.15, 0.0, 0.15, 0.3)
# operator-declared positions; distance_m from the wide-ROI grid run
GRID = [
    ('1.0m center', 1.031, 0.00),
    ('1.0m left25', 1.082, +0.25),
    ('1.5m center', 1.583, 0.00),
    ('1.5m left25', 1.638, +0.25),
    ('1.5m right25', 1.612, -0.25),
    ('2.0m center', 2.131, 0.00),
    ('2.0m left25', 2.184, +0.25),
    ('2.0m right25', 2.187, -0.25),
]


def gradient(speed, yaw, forward, left):
    return evaluate_candidate_steering(speed, yaw, forward, left, WIDTH_M)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')

    rows = []
    for name, distance, left in GRID:
        for speed in SPEEDS:
            for yaw in YAWS:
                value = gradient(speed, yaw, distance, left)
                direction = gradient_to_direction(value['gradient_normalized'])
                expected = 0 if abs(left) < 1e-9 else (-1 if left > 0 else 1)
                rows.append(dict(position=name, distance_m=distance, left_m=left,
                                 speed_mps=speed, yaw_radps=yaw, valid=value['valid'],
                                 gradient=value['gradient_normalized'], direction=direction,
                                 expected_side_direction=expected,
                                 inactive=value['reason'] != 'ok',
                                 near_deadband=abs(value['gradient_normalized']) < 0.15))

    mismatches = [row for row in rows if not row['inactive'] and row['expected_side_direction']
                  and row['direction'] not in (0, row['expected_side_direction'])]
    inactive = [row for row in rows if row['inactive']]
    near = [row for row in rows if not row['inactive'] and row['near_deadband']]
    active = [row for row in rows if not row['inactive']]

    # Fixed steering, direction changes caused by +/-1 cm range jitter.
    jitter = []
    for name, distance, left in GRID:
        for speed in SPEEDS:
            for yaw in YAWS:
                directions = set()
                for delta in (-0.01, 0.0, 0.01):
                    value = gradient(speed, yaw, distance + delta, left)
                    directions.add(gradient_to_direction(value['gradient_normalized']))
                if len(directions) > 1:
                    jitter.append(dict(position=name, speed_mps=speed, yaw_radps=yaw,
                                       directions=sorted(directions)))

    report = dict(schema='gradient_offline_dry_run_v1',
                  state='offline_geometry_NOT_field_validation',
                  width_m=WIDTH_M, positions=len(GRID), speeds=list(SPEEDS), yaws=list(YAWS),
                  evaluations=len(rows), active=len(active), inactive=len(inactive),
                  side_mismatches=len(mismatches), near_deadband=len(near),
                  jitter_direction_changes=len(jitter),
                  rows=rows, mismatch_examples=mismatches[:10], jitter_examples=jitter[:10],
                  camera_or_vehicle_used=False, ffb_output_used=False,
                  physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'dry_run.json').write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'cases.csv').open('w') as target:
        target.write('position,distance_m,left_m,speed_mps,yaw_radps,valid,gradient,direction,'
                     'expected_side_direction,inactive,near_deadband\n')
        for row in rows:
            target.write(','.join(str(row[key]) for key in (
                'position', 'distance_m', 'left_m', 'speed_mps', 'yaw_radps', 'valid',
                'gradient', 'direction', 'expected_side_direction', 'inactive', 'near_deadband')) + '\n')
    print(json.dumps({key: report[key] for key in (
        'evaluations', 'active', 'inactive', 'side_mismatches', 'near_deadband',
        'jitter_direction_changes')}, indent=2))


if __name__ == '__main__':
    main()
