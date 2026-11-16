"""Three 11/16 report assets: untouched native PNG and two sourced plots."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
DAY = ROOT/'Experimental_results/2026-11-16'
PIN = 'decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    output = output.resolve()
    if ROOT/'Experimental_results' not in output.parents:
        raise ValueError('scoped report output required')
    names = [PIN, 'three_distance_points.csv', 'three_distance_difference.png',
             'clock_read_bracket.csv', 'clock_read_bracket.png', 'manifest.json']
    if any((output/n).exists() for n in names):
        raise ValueError('asset outputs already exist; use an unused output directory')
    audit_path = DAY/'body_display_range_audit_r01/results_r01/audit.json'
    audit = json.loads(audit_path.read_bytes())
    source_pin = ROOT/'recordings/2026-11-16/body_display_full_intake_r02/comparison'/PIN
    if sha(source_pin) != audit['supplied_files_sha256']['comparison/'+PIN]:
        raise ValueError('pin differs from verified unmodified original')
    points_path = DAY/'body_display_range_check_r01/observations.csv'
    with points_path.open(newline='') as stream:
        points = list(csv.DictReader(stream))
    clock_path = DAY/'sender_ros_clock_live_audit_r01/results_r02/audit.json'
    clock = json.loads(clock_path.read_bytes())
    stats = clock['bracket_width_us']
    output.mkdir(parents=True, exist_ok=True)
    # Byte copy only: no decode, resize, annotation, compositing or color edit.
    shutil.copyfile(source_pin, output/PIN)
    shutil.copyfile(points_path, output/'three_distance_points.csv')
    x = [float(row['reported_floor_range_m']) for row in points]
    y = [float(row['signed_difference_m'])*100 for row in points]
    fig, ax = plt.subplots(figsize=(7.0, 4.3), layout='constrained')
    ax.axhline(0, color='black', linewidth=.8)
    ax.scatter(x, y, color='#176b98', s=65)
    for a, b in zip(x, y):
        ax.annotate(f'{b:+.1f} cm', (a, b), xytext=(0, 10), textcoords='offset points', ha='center')
    ax.set(xlabel='User-reported camera-foot floor range [m]', ylabel='Displayed - reported range [cm]',
           title='2026-11-16: three displayed points (not a continuous accuracy bound)',
           xticks=x, xlim=(.85, 2.15), ylim=(-5.0, 2.0))
    ax.grid(alpha=.25)
    fig.savefig(output/'three_distance_difference.png', dpi=160)
    plt.close(fig)
    keys = ['minimum', 'median', 'p95', 'maximum']
    with (output/'clock_read_bracket.csv').open('x', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['statistic', 'read_bracket_us', 'telemetry_samples', 'meaning'])
        for key in keys:
            writer.writerow([key, stats[key], clock['telemetry_records'], 'sender_read_interval_NOT_cross_PC_accuracy'])
    fig, ax = plt.subplots(figsize=(7.0, 4.3), layout='constrained')
    bars = ax.bar(['Min', 'Median', 'P95', 'Max'], [stats[k] for k in keys], color='#358778')
    ax.bar_label(bars, fmt='%.3f', padding=3)
    ax.set(ylabel='Sender clock read bracket [microseconds]', ylim=(0, 330),
           title='1,177 recorded observations: NOT cross-PC synchronization accuracy')
    ax.grid(axis='y', alpha=.25)
    ax.set_axisbelow(True)
    fig.savefig(output/'clock_read_bracket.png', dpi=160)
    plt.close(fig)
    manifest = dict(work_date='2026-11-16', camera_image_byte_identical=True,
        camera_session=audit['session'], camera_frame=audit['pin_frame'],
        camera_image_is_reference_pin_NOT_three_measured_points=True,
        input_sha256={str(p.relative_to(ROOT)):sha(p) for p in
                      (source_pin, audit_path, points_path, clock_path, Path(__file__).resolve())},
        output_sha256={n:sha(output/n) for n in names if n != 'manifest.json'},
        physical_accuracy_or_clock_sync_certified=False)
    with (output/'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2); stream.write('\n')
    if sha(source_pin) != sha(output/PIN):
        raise ValueError('camera original changed')
    print('Three representative assets saved; camera PNG byte-identical.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    run(args.output_dir)
