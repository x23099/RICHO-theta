"""Measured guarded-bin cost and unchanged one-second replay, numerical only."""
import json
import os

os.environ.setdefault('MPLCONFIGDIR', '/tmp/theta_bin_reduction_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from run_fast import HERE, p


def main():
    output = HERE / 'report_r01'
    if output.exists():
        raise ValueError('fresh chart output required')
    paths = [HERE / 'plot_fast.py', HERE / 'results_guard_r02/summary.json',
             HERE / 'results_guard_r02/paired_measurements.csv', HERE / 'replay_r01/replay_summary.csv']
    sources = {str(x): p.sha256(x) for x in paths}
    proof = json.loads(paths[1].read_text())
    pairs = p.read_csv(paths[2]); replay = p.read_csv(paths[3])
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout='constrained')
    control = [float(r['control_ms']) for r in pairs]; fast = [float(r['fast_ms']) for r in pairs]
    high = max(control + fast) * 1.05
    axes[0].scatter(control, fast, s=16, alpha=.6)
    axes[0].plot([0, high], [0, high], '--', color='gray')
    axes[0].set(xlim=(0, high), ylim=(0, high), xlabel='Ray-reuse control (ms)', ylabel='Guarded bin-reduction (ms)',
                title=f"156 pairs / median speedup {proof['paired_speedup_median']:.2f}x")
    bars = axes[1].bar(['Zero cost\nreference', 'Ray reuse\npaired median', 'Bin reduction\npaired median'],
                       [int(r['diagnostic_frames']) for r in replay], color=['gray', '#b36b39', '#267e9d'])
    axes[1].bar_label(bars, padding=3)
    axes[1].set(ylim=(0, 450), ylabel='Diagnostic frames / 1547', title='Same 1 s inputs, TTL and unfinished-input hold')
    fig.suptitle('Exact result-preserving offline optimization: NOT physical FFB validation')
    fig.supxlabel('Scene stage only. Replay cone-query compute cost remains excluded. Native camera pixels unchanged.')
    output.mkdir()
    fig.savefig(output / 'guarded_bin_cost_and_availability.png', dpi=150)
    plt.close(fig)
    summary = dict(status='COMPLETED_GUARDED_BIN_NUMERICAL_CHART', source_sha256=sources,
                   source_images_edited=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={x.name: p.sha256(x) for x in output.iterdir() if x.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
