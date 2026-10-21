"""Recover complete CSV exports from frozen observations, without rerunning corners.

The first export failed on optional CSV columns AFTER saving observations.json.
Original outputs and native images are never overwritten by this recovery.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from cone_dataset import read_csv, write_csv, sha256
from fisheye_intrinsic_calibration import FRONT_ROI, SCREEN, coverage


def union_fields(rows):
    return list(dict.fromkeys(key for row in rows for key in row))


def reference_match(image, reference):
    if image.shape != (720, 1280, 3) or reference.shape != image.shape:
        raise ValueError('full native frames required')
    difference = float(np.mean(cv2.absdiff(image, reference)))
    return difference, difference <= 1.0


def signal_intervals(rows):
    """Inclusive sampled frame ranges, not a physical USB fault diagnosis."""
    intervals = []
    for row in rows:
        if not row['matches_no_signal_reference']:
            continue
        if not intervals or row['frame'] != intervals[-1]['last_frame'] + 1:
            intervals.append(dict(first_frame=row['frame'], last_frame=row['frame'],
                                  first_time_sec=row['time_sec'], last_time_sec=row['time_sec'], frames=1))
        else:
            intervals[-1].update(last_frame=row['frame'], last_time_sec=row['time_sec'],
                                 frames=intervals[-1]['frames'] + 1)
    return intervals


def plot_diagnostics(j, signal, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), constrained_layout=True)
    train = set(j['train_indices'])
    for split, colour in [('train', 'tab:blue'), ('pose validation', 'tab:orange')]:
        views = [v for i, v in enumerate(j['retained_views']) if (i in train) == (split == 'train')]
        points = np.concatenate([v['corners_native'] for v in views])
        axes[0].scatter(points[:, 0], points[:, 1], s=2, alpha=.25, c=colour)
        axes[0].scatter([v['centre_x'] for v in views], [v['centre_y'] for v in views],
                        s=18, c=colour, label=split)
    for x in (640 / 3, 1280 / 3):
        axes[0].axvline(x, color='grey', lw=.5)
    for y in (240, 480):
        axes[0].axhline(y, color='grey', lw=.5)
    axes[0].set(xlim=(0, 640), ylim=(720, 0), xlabel='Native x [px]', ylabel='Native y [px]',
                title='Front lens: corner / centre coverage')
    axes[0].legend(fontsize=8)
    for reason, colour in [('handheld_candidate_needs_native_review', 'tab:blue'),
                           ('near_duplicate_pose', 'grey'), ('grid_too_small', 'tab:red')]:
        rows = [r for r in j['attempts'] if r['reason'] == reason]
        axes[1].scatter([r['time_sec'] for r in rows], [r['median_spacing_px'] for r in rows],
                        s=10, c=colour, label=reason.replace('handheld_candidate_needs_native_review', 'retained'))
    axes[1].axhline(SCREEN['min_grid_spacing_px'], c='black', ls='--', label='8 px screen')
    axes[1].set(xlabel='Recording time [s]', ylabel='Median grid spacing [px]', title='Detected full grids, every 5 frames')
    axes[1].legend(fontsize=7)
    names = ['X span', 'Y span']
    values = [j['train_only_coverage']['span_fraction_x'] * 100,
              j['train_only_coverage']['span_fraction_y'] * 100]
    axes[2].bar(names, values, color=['tab:blue', 'tab:red'])
    axes[2].axhline(35, c='black', ls='--', label='35% screen')
    axes[2].set(ylim=(0, 100), ylabel='Training corner span / ROI [%]', title='54 views; no intrinsic fit')
    for x, value in enumerate(values):
        axes[2].text(x, value + 2, f'{value:.2f}%', ha='center')
    axes[2].legend(fontsize=8)
    fig.savefig(output / 'coverage_diagnosis.png', dpi=150)
    plt.close(fig)


def main():
    output = HERE / 'exports_r01'
    if output.exists():
        raise ValueError('do not overwrite recovered exports')
    path = HERE / 'extraction_r01/observations.json'
    j = json.loads(path.read_text())
    assert all(sha256(Path(p)) == value for p, value in j['source_sha256'].items())
    intake = json.loads((HERE / 'intake_summary.json').read_text())
    session = Path(intake['session'])
    original_rows = read_csv(session / 'detections.csv')
    reference_path = HERE / 'raw_samples/raw_f000472.png'
    reference = cv2.imread(str(reference_path))
    assert reference is not None
    manifest_reference = next(r for r in read_csv(HERE / 'raw_sample_manifest.csv') if r['frame'] == '472')
    assert sha256(reference_path) == manifest_reference['png_sha256']
    attempts = [dict(r, corners_native=json.dumps(r['corners_native'])) for r in j['attempts']]
    manifest = []
    for r in j['retained_views']:
        png = HERE / 'extraction_r01' / r['native_png']
        assert sha256(png) == r['png_sha256']
        image = cv2.imread(str(png))
        assert image.shape == (720, 1280, 3)
        assert hashlib.sha256(image.tobytes()).hexdigest() == r['decoded_bgr_sha256']
        manifest.append(dict(file=str(png.relative_to(HERE)), frame=r['frame'], time_sec=r['time_sec'],
                             session=session.name, png_sha256=r['png_sha256'],
                             decoded_bgr_sha256=r['decoded_bgr_sha256'], image_edited=False))
    assert len(attempts) == len(range(1, j['frames_decoded'] + 1, 5))
    train = coverage([np.asarray(j['retained_views'][i]['corners_native']) for i in j['train_indices']], FRONT_ROI)
    assert train == j['train_only_coverage']
    output.mkdir()
    write_csv(output / 'attempts.csv', attempts, fields=union_fields(attempts))
    write_csv(output / 'raw_frame_manifest.csv', manifest)
    cap = cv2.VideoCapture(str(session / 'raw.avi'))
    signal = []
    try:
        for i, row in enumerate(original_rows, 1):
            ok, image = cap.read()
            assert ok
            difference, matches = reference_match(image, reference)
            signal.append(dict(frame=i, time_sec=float(row['time_sec']), no_signal_reference_mae=difference,
                               matches_no_signal_reference=matches))
        assert not cap.read()[0]
    finally:
        cap.release()
    assert len(signal) == j['frames_decoded']
    write_csv(output / 'signal_audit.csv', signal)
    intervals = signal_intervals(signal)
    write_csv(output / 'no_signal_intervals.csv', intervals)
    plot_diagnostics(j, signal, output)
    assert all(sha256(Path(p)) == value for p, value in j['source_sha256'].items())
    summary = dict(status='EXPORTS_RECOVERED_NOT_CALIBRATION_APPROVAL', attempts=len(attempts),
                   retained_views=len(manifest), train_views=len(j['train_indices']),
                   validation_views=len(j['validation_indices']), counts=dict(Counter(r['reason'] for r in attempts)),
                   train_coverage=train, prefit_checks=j['prefit_checks'],
                   no_signal_reference_matched_frames=sum(r['matches_no_signal_reference'] for r in signal),
                   no_signal_intervals=intervals, source_files_verified=True,
                   original_partial_csv='extraction_r01/attempts.csv (incomplete; do not use)',
                   observation_json_sha256=sha256(path), recovery_script_sha256=sha256(Path(__file__)),
                   reference_png_sha256=sha256(reference_path),
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()},
                   original_images_edited=False, physical_output=False, usable_for_ffb=False)
    (output / 'recovery_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
