"""Offline sensitivity of the risk gradient to a range error of a few cm.

No camera, vehicle, ROS or FFB. Pure geometry from src/collision_risk.py.
Question: does the measured VP8-vs-original range difference (about ±3 cm)
change the steering-gradient direction or the risk level?
"""
import argparse
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from collision_risk import (assess_path_collision, classify_candidate_risk,
                            evaluate_candidate_steering, gradient_to_direction)

WIDTH_M = 0.354  # existing car_width default
SPEEDS = (0.2, 0.4, 0.8)
YAWS = (-0.5, -0.25, 0.0, 0.25, 0.5)
FORWARD = (1.0, 1.5, 2.0)
LEFT = (-0.4, -0.2, 0.0, 0.2, 0.4)
DELTAS = (0.01, 0.0274, 0.0302, 0.05)


def level(speed, yaw, forward, left):
    path = __import__('collision_risk').predict_unicycle_path(speed, yaw)
    assessment = assess_path_collision(path, obstacle_forward_m=forward, obstacle_left_m=left,
                                       vehicle_width_m=WIDTH_M, safety_margin_m=0.10,
                                       path_speed_mps=speed, ttc_sec=None)
    return classify_candidate_risk(assessment['in_collision_corridor'], assessment['path_eta_sec'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    rows = []
    for speed, yaw, forward, left in itertools.product(SPEEDS, YAWS, FORWARD, LEFT):
        base = evaluate_candidate_steering(speed, yaw, forward, left, WIDTH_M)
        base_direction = gradient_to_direction(base['gradient_normalized'])
        base_level = level(speed, yaw, forward, left)
        for delta in DELTAS:
            for sign in (-1, 1):
                shifted = forward + sign * delta
                value = evaluate_candidate_steering(speed, yaw, shifted, left, WIDTH_M)
                direction = gradient_to_direction(value['gradient_normalized'])
                rows.append(dict(speed_mps=speed, yaw_radps=yaw, forward_m=forward, left_m=left,
                                 delta_m=sign * delta, direction_base=base_direction,
                                 direction_shifted=direction,
                                 direction_changed=direction != base_direction,
                                 gradient_base=base['gradient_normalized'],
                                 gradient_shifted=value['gradient_normalized'],
                                 gradient_abs_change=abs(value['gradient_normalized']
                                                         - base['gradient_normalized']),
                                 level_base=base_level, level_shifted=level(speed, yaw, shifted, left),
                                 level_changed=level(speed, yaw, shifted, left) != base_level))
    summary = []
    for delta in DELTAS:
        for sign in (-1, 1):
            subset = [r for r in rows if r['delta_m'] == sign * delta]
            summary.append(dict(delta_m=sign * delta, cases=len(subset),
                                direction_changes=sum(r['direction_changed'] for r in subset),
                                level_changes=sum(r['level_changed'] for r in subset),
                                max_abs_gradient_change=max(r['gradient_abs_change'] for r in subset),
                                mean_abs_gradient_change=sum(r['gradient_abs_change'] for r in subset) / len(subset)))
    report = dict(schema='risk_gradient_range_sensitivity_v1',
                  state='offline_geometry_NOT_field_validation',
                  width_m=WIDTH_M, speeds=SPEEDS, yaws=YAWS, forward_m=FORWARD, left_m=LEFT,
                  grid_cells=len(SPEEDS) * len(YAWS) * len(FORWARD) * len(LEFT),
                  deltas_m=list(DELTAS), summary=summary,
                  camera_or_gpu_used=False, field_data_used=False,
                  physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'sensitivity.json').write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'cases.csv').open('w') as target:
        keys = ['speed_mps', 'yaw_radps', 'forward_m', 'left_m', 'delta_m', 'direction_base',
                'direction_shifted', 'direction_changed', 'gradient_base', 'gradient_shifted',
                'gradient_abs_change', 'level_base', 'level_shifted', 'level_changed']
        target.write(','.join(keys) + '\n')
        for row in rows:
            target.write(','.join(str(row[key]) for key in keys) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
