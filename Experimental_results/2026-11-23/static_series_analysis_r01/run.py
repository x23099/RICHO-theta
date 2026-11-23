"""Static-position distance-series analysis from the 2026-11-21 archives.

For each position: longest contiguous numeric run, jitter, gate transitions.
No camera, GPU, ROS or FFB.
"""
import argparse
import json
from pathlib import Path
import statistics
import tarfile


def load(archive):
    with tarfile.open(archive) as bundle:
        member = next(m for m in bundle.getmembers() if m.name.endswith('motion_distance_frames.jsonl'))
        rows = [json.loads(line) for line in bundle.extractfile(member).read().decode().splitlines()
                if line.strip()]
    return rows


def analyse(rows):
    series = []
    for row in rows:
        value = row.get('horizontal_camera_foot_range_m')
        series.append((row.get('completed_time_sec'), value, row.get('reason')))
    numeric = [(t, d) for t, d, _ in series if d is not None]
    if not numeric:
        return dict(frames=len(series), numeric=0, numeric_rate=0.0)
    # longest contiguous numeric run
    best, current = [], []
    for item in series:
        if item[1] is None:
            if len(current) > len(best):
                best = current
            current = []
        else:
            current.append(item)
    if len(current) > len(best):
        best = current
    values = [item[1] for item in best]
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    times = [item[0] for item in best if item[0] is not None]
    transitions = sum(1 for i in range(1, len(series))
                      if (series[i][1] is None) != (series[i - 1][1] is None))
    return dict(
        frames=len(series), numeric=len(numeric), numeric_rate=round(len(numeric) / len(series), 4),
        run_frames=len(best), run_seconds=round(max(times) - min(times), 3) if len(times) > 1 else None,
        run_median_m=round(statistics.median(values), 5),
        run_stdev_mm=round(statistics.pstdev(values) * 1000, 3),
        run_min_m=round(min(values), 5), run_max_m=round(max(values), 5),
        run_span_mm=round((max(values) - min(values)) * 1000, 3),
        consecutive_diff_p95_mm=round(sorted(diffs)[int(.95 * (len(diffs) - 1))] * 1000, 3) if diffs else None,
        gate_transitions=transitions,
        reasons=sorted({reason for _, _, reason in series if reason}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    archives = sorted(args.input_dir.glob('*.tar.xz'))
    if len(archives) < 2:
        raise SystemExit('at least two static archives required')
    results = {}
    for archive in archives:
        label = archive.name.replace('static_motion_yellow_', '').replace('_20261121_r01.tar.xz', '')
        results[label] = analyse(load(archive))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'static_series.json').write_text(json.dumps(results, indent=2) + '\n')
    with (output / 'static_series.csv').open('w') as target:
        keys = ['frames', 'numeric', 'numeric_rate', 'run_frames', 'run_seconds', 'run_median_m',
                'run_stdev_mm', 'run_min_m', 'run_max_m', 'run_span_mm', 'consecutive_diff_p95_mm',
                'gate_transitions']
        target.write('position,' + ','.join(keys) + '\n')
        for label, value in results.items():
            target.write(label + ',' + ','.join(str(value.get(key)) for key in keys) + '\n')
    for label, value in results.items():
        print(f"{label:6s} frames={value['frames']:5d} numeric={value['numeric_rate']:.1%} "
              f"run={value['run_frames']:4d} med={value['run_median_m']} stdev={value['run_stdev_mm']}mm "
              f"span={value['run_span_mm']}mm p95diff={value['consecutive_diff_p95_mm']}mm "
              f"transitions={value['gate_transitions']}")


if __name__ == '__main__':
    main()
