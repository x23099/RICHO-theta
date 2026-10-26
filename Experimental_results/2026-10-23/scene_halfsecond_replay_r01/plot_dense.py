"""Numerical cadence comparison, not altered camera imagery."""
import json
import os

os.environ.setdefault('MPLCONFIGDIR', '/tmp/theta_halfsecond_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from dense_common import HERE, read_csv, sha256


def main():
    output = HERE / 'report_r01'
    if output.exists():
        raise ValueError('fresh plot output required')
    paths = [HERE / 'method.md', HERE / 'plot_dense.py',
             HERE / 'scene_results_r01/session_summary.csv', HERE / 'replay_r01/session_summary.csv',
             HERE / 'replay_r01/frame_metrics.csv']
    sources = {str(p): sha256(p) for p in paths}
    scenes = read_csv(paths[2]); sessions = read_csv(paths[3]); frames = read_csv(paths[4])
    names = [r['session'] for r in scenes]
    labels = [n.split('_2026')[0].replace('cone_static_', '').replace('one_static_', '') for n in names]
    y = np.arange(len(names)); height = .36
    fig, axes = plt.subplots(1, 2, figsize=(15, 6.5), layout='constrained')
    axes[0].barh(y - height / 2, [int(r['accepted_sparse_images']) for r in scenes], height, label='1 s grid')
    axes[0].barh(y + height / 2, [int(r['accepted_images']) for r in scenes], height, label='0.5 s grid')
    axes[0].set(yticks=y, yticklabels=labels, xlabel='Accepted single-image up hypotheses', title='All 9 recordings retained')
    for interval, offset, label in [('sparse_1s', -height / 2, '1 s grid'), ('dense_0p5s', height / 2, '0.5 s grid')]:
        rows = {r['session']: r for r in sessions if r['scenario'] == interval + '__three_pass_median'}
        bars = axes[1].barh(y + offset, [int(rows[n]['diagnostic_frames']) for n in names], height, label=label)
        axes[1].bar_label(bars, padding=2)
    axes[1].set(yticks=y, yticklabels=[], xlabel='Diagnostic query frames (measured-cost replay)',
                title='Unchanged TTL and pending-input hold')
    axes[0].legend(); axes[1].legend()
    fig.suptitle('Denser saved observations: counts are NOT physical or independent validation')
    fig.supxlabel('Same scene algorithm / same per-image costs for shared frames. Paper-only recording has no cone output.')
    output.mkdir()
    fig.savefig(output / 'all_recordings_cadence_comparison.png', dpi=150)
    plt.close(fig)
    session = 'floor_cone_same_pose_r01_20261015_160621_378'
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, layout='constrained')
    for index, (interval, label) in enumerate([('sparse_1s', '1 s grid'), ('dense_0p5s', '0.5 s grid')]):
        rows = [r for r in frames if r['session'] == session and r['scenario'] == interval + '__three_pass_median']
        time = np.array([float(r['time_sec']) for r in rows])
        used = [r for r in rows if r['diagnostic_available'] == 'True']
        pending = np.array([r['newer_scene_input_pending'] == 'True' for r in rows])
        axes[0].scatter(time[pending], np.full(pending.sum(), index), s=8, color='lightgray', marker='s')
        axes[0].scatter([float(r['time_sec']) for r in used], np.full(len(used), index), s=8,
                        label=f'{label}: {len(used)} diagnostic frames')
        axes[1].scatter([float(r['time_sec']) for r in used], [float(r['diagnostic_z_m']) for r in used], s=7, alpha=.65, label=label)
        if index == 0:
            reference = [r for r in rows if r['reference_z_m']]
            axes[1].scatter([float(r['time_sec']) for r in reference], [float(r['reference_z_m']) for r in reference],
                            s=3, color='gray', alpha=.25, label='Reported placement Z (not independent calibration)')
    axes[0].set(yticks=[0, 1], yticklabels=['1 s', '0.5 s'], ylim=(-.5, 1.5),
                title='Availability; gray = new scene input unfinished, gaps are not imputed')
    axes[1].set(xlabel='Recorded CSV time (s)', ylabel='Diagnostic forward Z (m)', title='Same recording, current-frame cone observations only')
    axes[0].legend(loc='upper right'); axes[1].legend()
    fig.suptitle('Offline completion replay: NOT live latency, measured TF, or hardware FFB validation')
    fig.savefig(output / 'same_capture_cadence_timeline.png', dpi=150)
    plt.close(fig)
    report = dict(status='COMPLETED_NUMERICAL_CADENCE_PLOTS', source_sha256=sources,
                  original_images_edited=False, physical_output=False, usable_for_ffb=False,
                  output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
