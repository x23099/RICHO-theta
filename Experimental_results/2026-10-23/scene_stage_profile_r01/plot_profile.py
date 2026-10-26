"""Exclusive timing charts from saved numerical evidence, no image editing."""
import json
import os

os.environ.setdefault('MPLCONFIGDIR', '/tmp/theta_stage_profile_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from run_profile import HERE, read_csv, sha256, STAGES


def main():
    output = HERE / 'report_r01'
    if output.exists():
        raise ValueError('fresh chart output required')
    output.mkdir()
    paths = [HERE / 'plot_profile.py', HERE / 'method.md', HERE / 'results_r01/summary.json',
             HERE / 'results_r01/stage_summary.csv', HERE / 'results_r01/paired_measurements.csv']
    sources = {str(p): sha256(p) for p in paths}
    rows = read_csv(paths[3]); pairs = read_csv(paths[4])
    focus = sorted((r for r in rows if r['population'] == 'fixed_52_images_three_pass'), key=lambda r: float(r['mean_ms']))
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), layout='constrained')
    labels = [r['stage'].replace('_', ' ') for r in focus]
    bars = axes[0].barh(labels, [float(r['mean_ms']) for r in focus])
    axes[0].bar_label(bars, labels=[f"{float(r['mean_ms']):.2f} ms / {float(r['share_of_mean_wall_percent']):.1f}%" for r in focus], padding=3)
    axes[0].set(xlabel='Mean exclusive time (ms)', title='Fixed 52 images x 3 passes / same denominator')
    axes[0].set_xlim(right=max(float(r['mean_ms']) for r in focus) * 1.45)
    plain = [float(r['plain_wall_ms']) for r in pairs]
    instrumented = [float(r['profiled_wall_ms']) for r in pairs]
    axes[1].scatter(plain, instrumented, s=15, alpha=.6)
    high = max(plain + instrumented) * 1.05
    low = min(plain + instrumented) * .95
    axes[1].plot([low, high], [low, high], '--', color='gray')
    axes[1].set(xlabel='Uninstrumented call time (ms)', ylabel='Instrumented call time (ms)',
                title='156 alternating-order pairs; instrumentation is not free')
    fig.suptitle('Offline scene-stage profile: unchanged outputs, NOT end-to-end latency or FFB validation')
    fig.savefig(output / 'scene_stage_budget_and_instrumentation.png', dpi=150)
    plt.close(fig)
    populations = sorted({r['population'] for r in rows if r['population'].startswith('session_one_pass:')})
    fig, ax = plt.subplots(figsize=(14, 7), layout='constrained')
    labels = [p.split(':', 1)[1].split('_2026')[0] for p in populations]
    left = np.zeros(len(populations))
    for stage in (*STAGES, 'other_and_instrumentation'):
        values = [float(next(r['mean_ms'] for r in rows if r['population'] == p and r['stage'] == stage)) for p in populations]
        ax.barh(labels, values, left=left, label=stage.replace('_', ' '))
        left += values
    ax.set(xlabel='Mean instrumented wall time (ms)', title='All 9 recordings / fixed half-second images / one pass')
    ax.legend(loc='upper center', bbox_to_anchor=(.5, -.1), ncols=3, fontsize=8)
    fig.suptitle('Per-recording budgets; no failed recording dropped and no camera pixels modified')
    fig.savefig(output / 'all_recordings_stage_budget.png', dpi=150)
    plt.close(fig)
    summary = dict(status='COMPLETED_NUMERICAL_STAGE_PROFILE_CHARTS', source_sha256=sources,
                   source_images_edited=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
