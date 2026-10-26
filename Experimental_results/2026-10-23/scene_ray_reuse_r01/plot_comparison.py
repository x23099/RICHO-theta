"""Numerical paired-cost and simulated availability plots; no camera editing."""
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('MPLCONFIGDIR', '/tmp/theta_ray_reuse_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_comparison import read_csv, sha256


def main():
    output = HERE / 'report_r01'
    if output.exists():
        raise ValueError('fresh plot output required')
    paths = [Path(__file__), HERE / 'results_r01/summary.json',
             HERE / 'results_r01/paired_measurements.csv', HERE / 'replay_r01/summary.json',
             HERE / 'replay_r01/replay_summary.csv']
    sources = {str(p): sha256(p) for p in paths}
    proof = json.loads(paths[1].read_text())
    pairs = read_csv(paths[2]); replay = read_csv(paths[4])
    baseline = np.array([float(r['baseline_ms']) for r in pairs])
    candidate = np.array([float(r['candidate_ms']) for r in pairs])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout='constrained')
    axes[0].scatter(baseline, candidate, s=15, alpha=.6)
    lim = max(baseline.max(), candidate.max()) * 1.05
    axes[0].plot([0, lim], [0, lim], '--', color='gray', label='equal time')
    axes[0].set(xlim=(0, lim), ylim=(0, lim), xlabel='Baseline (ms)',
                ylabel='Same-frame ray reuse (ms)', title='156 paired measurements / 52 images')
    axes[0].legend()
    axes[1].hist(baseline / candidate, bins=20)
    axes[1].axvline(1., color='gray', linestyle='--')
    axes[1].set(xlabel='Baseline / reuse time', ylabel='Pairs',
                title=f"Median paired speedup: {proof['paired_speedup_median']:.2f}x")
    labels = ['Zero cost\nreference', 'Baseline\npaired median', 'Ray reuse\npaired median']
    vals = [int(r['after_pending_hold_frames']) for r in replay]
    bars = axes[2].bar(labels, vals, color=['gray', '#b36b39', '#267e9d'])
    axes[2].bar_label(bars, padding=3)
    axes[2].set(ylim=(0, max(vals) * 1.2), ylabel='Diagnostic frames / 1547',
                title='Completion replay + unchanged pending hold')
    fig.suptitle('Offline equivalence-preserving optimization: NOT physical FFB validation')
    fig.supxlabel('Same PC, single thread; scene stage only. Replay TTL=1 s; cone-query compute cost excluded.')
    output.mkdir()
    fig.savefig(output / 'paired_cost_and_availability.png', dpi=150)
    plt.close(fig)
    summary = dict(status='COMPLETED_NUMERICAL_PLOT', source_sha256=sources,
                   source_images_edited=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
