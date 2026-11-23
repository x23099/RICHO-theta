"""Compare the binary-corridor risk with a continuous clearance risk.

Offline geometry only; no camera, ROS or FFB. Real measured ranges from the
wide-ROI grid. The continuous variant is an experiment, not a production change.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from collision_risk import (assess_path_collision, evaluate_candidate_steering,
                            gradient_to_direction, path_risk_from_eta, predict_unicycle_path)

WIDTH_M = 0.354
MARGIN_M = 0.10
SIGMA_M = 0.05
DELTA = 0.10
SPEEDS = (0.2, 0.4)
YAWS = (-0.3, -0.15, 0.0, 0.15, 0.3)
GRID = [
    ('1.0m center', 1.031, 0.00), ('1.0m left25', 1.082, +0.25),
    ('1.5m center', 1.583, 0.00), ('1.5m left25', 1.638, +0.25), ('1.5m right25', 1.612, -0.25),
    ('2.0m center', 2.131, 0.00), ('2.0m left25', 2.184, +0.25), ('2.0m right25', 2.187, -0.25),
]


def truncated_path(speed, omega, forward):
    return [point for point in predict_unicycle_path(speed, omega) if point[0] <= forward + 0.10]


def truncated_binary_risk(speed, yaw, forward, left):
    risks = []
    for omega in (yaw - DELTA, yaw, yaw + DELTA):
        path = truncated_path(speed, omega, forward)
        if not path:
            risks.append(0.0)
            continue
        assessment = assess_path_collision(path, obstacle_forward_m=forward, obstacle_left_m=left,
                                           vehicle_width_m=WIDTH_M, safety_margin_m=MARGIN_M,
                                           path_speed_mps=speed)
        risks.append(path_risk_from_eta(assessment['path_eta_sec'], assessment['in_collision_corridor']))
    gradient = (risks[2] - risks[0]) / (2.0 * DELTA)
    return max(-1.0, min(1.0, gradient))


def continuous_risk(speed, yaw, forward, left, truncate=False):
    risks = []
    for omega in (yaw - DELTA, yaw, yaw + DELTA):
        path = truncated_path(speed, omega, forward) if truncate else predict_unicycle_path(speed, omega)
        if not path:
            risks.append(0.0)
            continue
        assessment = assess_path_collision(path, obstacle_forward_m=forward, obstacle_left_m=left,
                                           vehicle_width_m=WIDTH_M, safety_margin_m=MARGIN_M,
                                           path_speed_mps=speed)
        clearance = assessment['clearance_from_vehicle_m']
        eta = assessment['path_eta_sec']
        lateral = 1.0 / (1.0 + math.exp((clearance - MARGIN_M) / SIGMA_M))
        urgency = 1.0 / min(10.0, max(0.1, eta)) if eta is not None else 1.0
        risks.append(lateral * urgency)
    gradient = (risks[2] - risks[0]) / (2.0 * DELTA)
    return max(-1.0, min(1.0, gradient))


def binary_direction(speed, yaw, forward, left):
    value = evaluate_candidate_steering(speed, yaw, forward, left, WIDTH_M, delta_radps=DELTA)
    return value['gradient_normalized'], gradient_to_direction(value['gradient_normalized'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    rows = []
    for name, distance, left in GRID:
        expected = 0 if abs(left) < 1e-9 else (-1 if left > 0 else 1)
        for speed in SPEEDS:
            for yaw in YAWS:
                binary_g, binary_dir = binary_direction(speed, yaw, distance, left)
                continuous_g = continuous_risk(speed, yaw, distance, left)
                continuous_dir = gradient_to_direction(continuous_g)
                trunc_g = truncated_binary_risk(speed, yaw, distance, left)
                trunc_dir = gradient_to_direction(trunc_g)
                trunc_cont_g = continuous_risk(speed, yaw, distance, left, truncate=True)
                trunc_cont_dir = gradient_to_direction(trunc_cont_g)
                shifts = {key: [] for key in ('binary', 'continuous', 'truncated', 'truncated_continuous')}
                for shift in (-0.01, 0.0, 0.01):
                    shifts['binary'].append(binary_direction(speed, yaw, distance + shift, left)[1])
                    shifts['continuous'].append(gradient_to_direction(continuous_risk(speed, yaw, distance + shift, left)))
                    shifts['truncated'].append(gradient_to_direction(truncated_binary_risk(speed, yaw, distance + shift, left)))
                    shifts['truncated_continuous'].append(gradient_to_direction(continuous_risk(speed, yaw, distance + shift, left, truncate=True)))
                rows.append(dict(position=name, speed_mps=speed, yaw_radps=yaw, expected=expected,
                                 binary_gradient=binary_g, binary_direction=binary_dir,
                                 continuous_gradient=continuous_g, continuous_direction=continuous_dir,
                                 truncated_gradient=trunc_g, truncated_direction=trunc_dir,
                                 truncated_continuous_gradient=trunc_cont_g,
                                 truncated_continuous_direction=trunc_cont_dir,
                                 **{f'{key}_jitter': len(set(values)) > 1 for key, values in shifts.items()}))
    summary = {}
    for label, key in (('binary', 'binary_direction'), ('continuous', 'continuous_direction'),
                       ('truncated', 'truncated_direction'),
                       ('truncated_continuous', 'truncated_continuous_direction')):
        deadband = sum(1 for r in rows if abs(r[f'{label}_gradient']) < 0.15)
        mismatches = sum(1 for r in rows if r['expected'] and abs(r[f'{label}_gradient']) >= 0.15
                         and r[key] not in (0, r['expected']))
        jitter = sum(1 for r in rows if r[f'{label}_jitter'])
        summary[label] = dict(evaluations=len(rows), near_deadband=deadband,
                              side_mismatches=mismatches, jitter_direction_changes=jitter)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'comparison.json').write_text(json.dumps(dict(schema='continuous_risk_comparison_v1',
                                                             summary=summary, rows=rows), indent=2) + '\n')
    with (output / 'cases.csv').open('w') as target:
        keys = ['position', 'speed_mps', 'yaw_radps', 'expected', 'binary_gradient', 'binary_direction',
                'continuous_gradient', 'continuous_direction', 'truncated_gradient', 'truncated_direction',
                'truncated_continuous_gradient', 'truncated_continuous_direction',
                'binary_jitter', 'continuous_jitter', 'truncated_jitter', 'truncated_continuous_jitter']
        target.write(','.join(keys) + '\n')
        for row in rows:
            target.write(','.join(str(row[key]) for key in keys) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
