"""Reproduce the 2026-11-21 daily-report tables and figures from saved archives."""
import csv
import json
from pathlib import Path
import tarfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
INTAKE = ROOT / 'recordings/2026-11-21/yellow_grid_intake_r01'
GRAD = ROOT / 'Experimental_results/2026-11-21/gradient_dry_run_r01/results_r01/dry_run.json'

GROUPS = {
    'narrow': (INTAKE / 'yellow_grid_s170_20261121_r01.tar.xz', [('1.0m', 3), ('1.5m', 3), ('2.0m', 3)]),
    'wide': (INTAKE / 'yellow_grid_wide_s170_20261121_r01.tar.xz', [('1.0m', 3), ('1.5m', 3), ('2.0m', 4)]),
}


def numeric_flags(archive):
    with tarfile.open(archive) as bundle:
        member = next(m for m in bundle.getmembers() if m.name.endswith('samples.jsonl'))
        rows = [json.loads(line) for line in bundle.extractfile(member).read().decode().splitlines()
                if line.strip()]
    seen, order = {}, []
    for row in rows:
        if row['variant'] != 'original':
            continue
        name = row['source_path'].split('/')[-1]
        if name not in seen:
            seen[name] = row['measurement'].get('horizontal_camera_foot_range_m') is not None
            order.append(name)
    return [seen[name] for name in order]


def main():
    rows = []
    for label, (archive, groups) in GROUPS.items():
        flags = numeric_flags(archive)
        index = 0
        for distance, count in groups:
            subset = flags[index:index + count]
            index += count
            rows.append(dict(roi=label, distance=distance, images=count,
                             numeric=sum(subset), withheld=count - sum(subset),
                             numeric_rate=round(sum(subset) / count, 4)))
    with (HERE / 'roi_coverage.csv').open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    figure, axes = plt.subplots(1, 1, figsize=(7, 3.8))
    labels = ['1.0 m', '1.5 m', '2.0 m']
    narrow = [r['numeric_rate'] for r in rows if r['roi'] == 'narrow']
    wide = [r['numeric_rate'] for r in rows if r['roi'] == 'wide']
    positions = range(len(labels))
    axes.bar([p - 0.18 for p in positions], narrow, width=0.36, label='ROI 270..350 (80 px)', color='#a0aec0')
    axes.bar([p + 0.18 for p in positions], wide, width=0.36, label='ROI 150..450 (300 px)', color='#2b6cb0')
    axes.set_ylim(0, 1.1)
    axes.set_ylabel('numeric rate (centre/left/right slots)')
    axes.set_xticks(list(positions))
    axes.set_xticklabels(labels)
    axes.set_title('Lateral recognition vs ROI width (yellow, S=170)')
    axes.legend(fontsize=8)
    axes.grid(axis='y', alpha=.3)
    for index, value in enumerate(narrow):
        axes.text(index - 0.18, value, f'{value:.0%}', ha='center', va='bottom', fontsize=7)
    for index, value in enumerate(wide):
        axes.text(index + 0.18, value, f'{value:.0%}', ha='center', va='bottom', fontsize=7)
    figure.tight_layout()
    figure.savefig(HERE / 'roi_coverage.png', dpi=130)
    plt.close(figure)

    value = json.loads(GRAD.read_bytes())
    selected = ['1.0m left25', '1.5m right25', '2.0m left25']
    figure, axes = plt.subplots(1, 1, figsize=(7, 3.8))
    for name in selected:
        points = [(r['yaw_radps'], r['gradient']) for r in value['rows']
                  if r['position'] == name and r['speed_mps'] == 0.4]
        points.sort()
        axes.plot([p[0] for p in points], [p[1] for p in points], marker='o', label=name)
    axes.axhline(0.1, color='gray', linestyle=':', linewidth=1)
    axes.axhline(-0.1, color='gray', linestyle=':', linewidth=1)
    axes.set_xlabel('yaw rate (rad/s)')
    axes.set_ylabel('normalized gradient at v=0.4 m/s (sign kept)')
    axes.set_title('Gradient vs steering (real measured ranges)')
    axes.legend(fontsize=8)
    axes.grid(alpha=.3)
    figure.tight_layout()
    figure.savefig(HERE / 'gradient_dry_run.png', dpi=130)
    plt.close(figure)

    with (HERE / 'gradient_dry_run.csv').open('w', newline='') as target:
        writer = csv.writer(target)
        writer.writerow(['position', 'speed_mps', 'yaw_radps', 'gradient', 'direction',
                         'expected_side_direction', 'near_deadband'])
        for row in value['rows']:
            writer.writerow([row['position'], row['speed_mps'], row['yaw_radps'], row['gradient'],
                             row['direction'], row['expected_side_direction'], row['near_deadband']])
    print(json.dumps(dict(roi=rows, gradient=dict(
        evaluations=value['evaluations'], near_deadband=value['near_deadband'],
        side_mismatches=value['side_mismatches'],
        jitter_direction_changes=value['jitter_direction_changes'])), indent=2))


if __name__ == '__main__':
    main()
