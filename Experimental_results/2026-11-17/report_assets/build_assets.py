"""Two sourced scientific figures; no camera image editing or live test."""
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
DAY = ROOT/'Experimental_results/2026-11-17'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    output = output.resolve()
    if ROOT/'Experimental_results' not in output.parents:
        raise ValueError('scoped assets output required')
    names = ['codec_samples.csv', 'comparison.csv', 'packet_size.png', 'codec_time.png', 'manifest.json']
    if any((output/n).exists() for n in names):
        raise ValueError('use unused asset outputs')
    audit_path = DAY/'frame_motion_packet_r01/results_r01/audit.json'
    samples = DAY/'frame_motion_packet_r01/results_r01/codec_samples.csv'
    audit = json.loads(audit_path.read_bytes())
    m = audit['metrics']
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(samples, output/'codec_samples.csv')
    rows = [('VP8 packet', m['packet_bytes']['median'], m['packet_encode_ms']['median']),
            ('PNG payload', m['png_bytes']['median'], m['png_encode_ms']['median'])]
    with (output/'comparison.csv').open('x', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['format', 'median_bytes', 'median_encode_ms'])
        writer.writerows(rows)
    fig, ax = plt.subplots(figsize=(6.7, 4), layout='constrained')
    bars = ax.bar([r[0] for r in rows], [r[1]/1000 for r in rows], color=['#287e91', '#b56c3b'])
    ax.bar_label(bars, fmt='%.1f', padding=3)
    ax.set(ylabel='Median size [decimal kB]', ylim=(0, 1150),
           title='One saved native image, 5 local codec runs; NOT live bandwidth')
    fig.savefig(output/'packet_size.png', dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.7, 4), layout='constrained')
    keys = ['packet_encode_ms', 'packet_decode_and_copy_ms', 'png_encode_ms']
    y = [m[k]['median'] for k in keys]
    ax.errorbar(range(3), y, yerr=[[m[k]['median']-m[k]['minimum'] for k in keys],
                [m[k]['maximum']-m[k]['median'] for k in keys]], fmt='o', capsize=7, color='#287e91')
    ax.set(xticks=range(3), xticklabels=['VP8 packet encode', 'Decode + copy', 'PNG encode'],
           ylabel='Local time [ms]; median and observed min/max', ylim=(0, 45),
           title='Analysis PC only: not matunuc/GPU/network/FFB latency')
    ax.grid(axis='y', alpha=.25)
    fig.savefig(output/'codec_time.png', dpi=160); plt.close(fig)
    manifest = dict(work_date='2026-11-17', representative_figures=2, new_camera_images=False,
        input_sha256={str(p.relative_to(ROOT)):sha(p) for p in (audit_path, samples, Path(__file__).resolve())},
        output_sha256={n:sha(output/n) for n in names if n != 'manifest.json'},
        source_motion_is_synthetic=True, live_adoption_or_performance_certified=False)
    with (output/'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2); stream.write('\n')
    print('Two sourced figures saved; no camera images changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    run(parser.parse_args().output_dir)
