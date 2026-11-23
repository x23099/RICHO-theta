"""Compare policy A (raw gradient direction) and B (side + magnitude) on the grid.

Offline only. A uses the gradient sign; B uses the obstacle side and lets the
gradient scale the magnitude. Real measured ranges from the wide-ROI grid.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from collision_risk import (assess_path_collision, classify_candidate_risk,
                            evaluate_candidate_steering, gradient_to_direction,
                            predict_unicycle_path)
from driver_ffb_side_mapping import command

WIDTH_M = 0.354
MARGIN_M = 0.10
DELTA = 0.10
SPEEDS = (0.2, 0.4)
YAWS = (-0.3, -0.15, 0.0, 0.15, 0.3)
GRID = [
    ('1.0m center', 1.031, 0.00), ('1.0m left25', 1.082, +0.25),
    ('1.5m center', 1.583, 0.00), ('1.5m left25', 1.638, +0.25), ('1.5m right25', 1.612, -0.25),
    ('2.0m center', 2.131, 0.00), ('2.0m left25', 2.184, +0.25), ('2.0m right25', 2.187, -0.25),
]


def level(speed, yaw, forward, left):
    path = predict_unicycle_path(speed, yaw)
    if not path:
        return 'CLEAR'
    assessment = assess_path_collision(path, obstacle_forward_m=forward, obstacle_left_m=left,
                                       vehicle_width_m=WIDTH_M, safety_margin_m=MARGIN_M,
                                       path_speed_mps=speed)
    return classify_candidate_risk(assessment['in_collision_corridor'], assessment['path_eta_sec'])


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
                value = evaluate_candidate_steering(speed, yaw, distance, left, WIDTH_M,
                                                    delta_radps=DELTA)
                a_direction = gradient_to_direction(value['gradient_normalized'])
                b = command(level(speed, yaw, distance, left), left, value['gradient_normalized'])
                rows.append(dict(position=name, speed_mps=speed, yaw_radps=yaw, expected=expected,
                                 gradient=value['gradient_normalized'], a_direction=a_direction,
                                 a_mismatch=bool(expected) and a_direction not in (0, expected),
                                 b_direction=b['direction'], b_magnitude=b['normalized_magnitude'],
                                 b_mismatch=bool(expected) and b['direction'] not in (0, expected),
                                 b_reason=b['reason']))
    summary = dict(
        evaluations=len(rows),
        a_side_mismatches=sum(1 for r in rows if r['a_mismatch']),
        b_side_mismatches=sum(1 for r in rows if r['b_mismatch']),
        a_direction_counts={str(k): sum(1 for r in rows if r['a_direction'] == k) for k in (-1, 0, 1)},
        b_direction_counts={str(k): sum(1 for r in rows if r['b_direction'] == k) for k in (-1, 0, 1)},
        b_magnitude_min=min(r['b_magnitude'] for r in rows),
        b_magnitude_max=max(r['b_magnitude'] for r in rows),
        inversion_cases_where_a_mismatch_but_b_matches=sum(
            1 for r in rows if r['a_mismatch'] and not r['b_mismatch']))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'comparison.json').write_text(json.dumps(dict(schema='ffb_policy_ab_comparison_v1',
                                                             summary=summary, rows=rows), indent=2) + '\n')
    with (output / 'cases.csv').open('w') as target:
        keys = ['position', 'speed_mps', 'yaw_radps', 'expected', 'gradient', 'a_direction',
                'a_mismatch', 'b_direction', 'b_magnitude', 'b_mismatch', 'b_reason']
        target.write(','.join(keys) + '\n')
        for row in rows:
            target.write(','.join(str(row[key]) for key in keys) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
