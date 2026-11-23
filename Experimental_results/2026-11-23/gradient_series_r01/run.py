"""Gradient series and 3-consecutive consistency on real distance sequences.

Static positions use the operator-declared lateral offset; live/drive runs assume
a centred obstacle with the measured radial range. Approximations are explicit.
No camera, GPU, ROS or FFB.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from collision_risk import evaluate_candidate_steering, gradient_to_direction

SPEC = importlib.util.spec_from_file_location('risk_consistency', ROOT / 'src/driver_risk_consistency.py')
consistency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(consistency)

WIDTH_M = 0.354
SPEEDS = (0.2, 0.4)
YAWS = (-0.3, -0.15, 0.15, 0.3)
LATERAL = {'C': 0.0, 'L': 0.25, 'R': -0.25}


class FrameClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def frames(archive):
    with tarfile.open(archive) as bundle:
        member = next(m for m in bundle.getmembers() if m.name.endswith('motion_distance_frames.jsonl'))
        return [json.loads(line) for line in bundle.extractfile(member).read().decode().splitlines()
                if line.strip()]


def series(rows, interval_sec=0.2):
    """Resample the frame series at 5 Hz: the gradient is consumed at that rate."""
    out, last = [], None
    for row in rows:
        distance = row.get('horizontal_camera_foot_range_m')
        at = row.get('completed_time_sec')
        if distance is None or at is None:
            continue
        if last is not None and at - last < interval_sec:
            continue
        last = at
        out.append((at, distance))
    return out


def run(values, speed, yaw, lateral, window=3):
    clock = FrameClock()
    unit = consistency.DirectionConsistency(window=window, required=window, clock=clock)
    raw = []
    confirmed = []
    previous_direction = None
    raw_flips = confirmed_flips = 0
    confirmed_count = 0
    for at, distance in values:
        forward = max(0.0, (distance ** 2 - lateral ** 2)) ** 0.5
        value = evaluate_candidate_steering(speed, yaw, forward, lateral, WIDTH_M)
        direction = gradient_to_direction(value['gradient_normalized'])
        if previous_direction is not None and direction != previous_direction:
            raw_flips += 1
        previous_direction = direction
        clock.now = at
        result = unit.offer(value['gradient_normalized'], risk_level='WARNING', at_sec=at)
        raw.append(direction)
        if result['confirmed']:
            confirmed_count += 1
            if confirmed and confirmed[-1] is not None and confirmed[-1] != result['direction']:
                confirmed_flips += 1
            confirmed.append(result['direction'])
        else:
            confirmed.append(None)
    return dict(frames=len(values), confirmed=confirmed_count,
                confirmed_rate=round(confirmed_count / len(values), 4) if values else 0.0,
                raw_direction_flips=raw_flips, confirmed_direction_flips=confirmed_flips,
                raw_direction_counts={str(k): raw.count(k) for k in (-1, 0, 1)},
                confirmed_direction_counts={str(k): confirmed.count(k) for k in (-1, 0, 1, None)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static-dir', type=Path, required=True)
    parser.add_argument('--live', type=Path, nargs='*', default=[])
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')

    results = {}
    for archive in sorted(args.static_dir.glob('*.tar.xz')):
        label = archive.name.replace('static_motion_yellow_', '').replace('_20261121_r01.tar.xz', '')
        lateral = LATERAL[label[-1]]
        values = series(frames(archive))
        results[label] = {f'v{speed}_yaw{yaw:+}': run(values, speed, yaw, lateral)
                          for speed in SPEEDS for yaw in YAWS}
    for archive in args.live:
        label = 'live_' + Path(archive).name.split('_')[0]
        values = series(frames(archive))
        results[label] = {f'v{speed}_yaw{yaw:+}': run(values, speed, yaw, 0.0)
                          for speed in SPEEDS for yaw in YAWS}

    output.mkdir(parents=True, exist_ok=False)
    (output / 'gradient_series.json').write_text(json.dumps(results, indent=2) + '\n')
    with (output / 'gradient_series.csv').open('w') as target:
        target.write('series,condition,frames,confirmed,confirmed_rate,raw_flips,confirmed_flips,'
                     'raw_minus1,raw_zero,raw_plus1,confirmed_minus1,confirmed_none,confirmed_plus1\n')
        for label, conditions in results.items():
            for condition, value in conditions.items():
                counts = value['raw_direction_counts']
                ccounts = value['confirmed_direction_counts']
                target.write(','.join(str(x) for x in (
                    label, condition, value['frames'], value['confirmed'], value['confirmed_rate'],
                    value['raw_direction_flips'], value['confirmed_direction_flips'],
                    counts['-1'], counts['0'], counts['1'],
                    ccounts['-1'], ccounts['None'], ccounts['1'])) + '\n')
    for label, conditions in list(results.items())[:3]:
        print(label, {k: (v['confirmed_rate'], v['raw_direction_flips'], v['confirmed_direction_flips'])
                      for k, v in list(conditions.items())[:4]})


if __name__ == '__main__':
    main()
