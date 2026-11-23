"""Delta / prediction-horizon sensitivity of the steering-risk gradient.

Real measured ranges from the wide-ROI grid; offline only.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from collision_risk import evaluate_candidate_steering, gradient_to_direction

WIDTH_M = 0.354
SPEEDS = (0.2, 0.4)
YAWS = (-0.3, -0.15, 0.0, 0.15, 0.3)
DELTAS = (0.05, 0.10, 0.15)
HORIZONS = (1.5, 3.5)
GRID = [
    ('1.0m center', 1.031, 0.00), ('1.0m left25', 1.082, +0.25),
    ('1.5m center', 1.583, 0.00), ('1.5m left25', 1.638, +0.25), ('1.5m right25', 1.612, -0.25),
    ('2.0m center', 2.131, 0.00), ('2.0m left25', 2.184, +0.25), ('2.0m right25', 2.187, -0.25),
]


def evaluate(speed, yaw, forward, left, delta, horizon):
    return evaluate_candidate_steering(speed, yaw, forward, left, WIDTH_M,
                                       delta_radps=delta, prediction_time_sec=horizon)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    summary = []
    rows = []
    for delta in DELTAS:
        for horizon in HORIZONS:
            deadband = mismatches = jitter = total = 0
            for name, distance, left in GRID:
                expected = 0 if abs(left) < 1e-9 else (-1 if left > 0 else 1)
                for speed in SPEEDS:
                    for yaw in YAWS:
                        value = evaluate(speed, yaw, distance, left, delta, horizon)
                        direction = gradient_to_direction(value['gradient_normalized'])
                        total += 1
                        if abs(value['gradient_normalized']) < 0.15:
                            deadband += 1
                        elif expected and direction not in (0, expected):
                            mismatches += 1
                        directions = set()
                        for shift in (-0.01, 0.0, 0.01):
                            shifted = evaluate(speed, yaw, distance + shift, left, delta, horizon)
                            directions.add(gradient_to_direction(shifted['gradient_normalized']))
                        if len(directions) > 1:
                            jitter += 1
                        rows.append(dict(position=name, speed_mps=speed, yaw_radps=yaw,
                                         delta_radps=delta, horizon_sec=horizon,
                                         gradient=value['gradient_normalized'], direction=direction,
                                         expected=expected, near_deadband=abs(value['gradient_normalized']) < 0.15))
            summary.append(dict(delta_radps=delta, horizon_sec=horizon, evaluations=total,
                                near_deadband=deadband, side_mismatches=mismatches,
                                jitter_direction_changes=jitter))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'sensitivity.json').write_text(json.dumps(dict(schema='gradient_delta_horizon_sensitivity_v1',
                                                             summary=summary, rows=rows), indent=2) + '\n')
    with (output / 'cases.csv').open('w') as target:
        keys = ['position', 'speed_mps', 'yaw_radps', 'delta_radps', 'horizon_sec', 'gradient',
                'direction', 'expected', 'near_deadband']
        target.write(','.join(keys) + '\n')
        for row in rows:
            target.write(','.join(str(row[key]) for key in keys) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
