"""Generate graphs/CSV only; existing and new raw PNGs remain unedited."""
import csv
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/theta-box-contact-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO / "src"))
from diagnose_ground_contact_quality import box_iou
from evaluate_raw_velocity_confidence_replay import sha256
from evaluate_velocity_confidence_replay import flag, number, write_csv
from compare_offline_box_contacts import VARIANTS


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


rows = read(ROOT / "frame_results.csv")
labels = read(ROOT / "coarse_image_labels.csv")
lookup = {(r['session'], r['variant'], int(r['frame'])): r for r in rows}
evaluated = []
manifest = []
provenance = json.loads((ROOT / 'provenance.json').read_text())
sources = {s['session']: s for s in provenance['sources']}
for label in labels:
    # Verify every label links to a whole, unedited, exact decoded frame.
    idx = int(label['frame'])
    source = Path(sources[label['session']]['path'])
    cap = cv2.VideoCapture(str(source / 'raw.avi'))
    for _ in range(idx):
        ok, decoded = cap.read()
        if not ok:
            raise ValueError('label outside video')
    cap.release()
    png = ROOT / label['raw_png']
    if not png.exists():
        if not cv2.imwrite(str(png), decoded):
            raise ValueError('cannot save raw PNG')
    if not np.array_equal(cv2.imread(str(png)), decoded):
        raise AssertionError('raw PNG differs from source frame')
    manifest.append({'session': label['session'], 'frame': idx, 'raw_png': label['raw_png'],
                     'source_video_sha256': sources[label['session']]['sha256']['raw.avi'],
                     'raw_png_sha256': sha256(png), 'width': decoded.shape[1], 'height': decoded.shape[0],
                     'png_pixels_equal_decoded_frame': True})
    for variant in VARIANTS:
        r = lookup[(label['session'], variant, idx)]
        detected = flag(r, 'detected')
        x, y = number(r, 'contact_pixel_x'), number(r, 'contact_pixel_y')
        base = number(label, 'visible_base_y_px') if flag(label, 'base_visible') else None
        iou = None
        if detected:
            ref = (int(label['bbox_x_min']), int(label['bbox_y_min']),
                   int(label['bbox_x_max']) - int(label['bbox_x_min']) + 1,
                   int(label['bbox_y_max']) - int(label['bbox_y_min']) + 1)
            actual = tuple(int(r[k]) for k in ('bbox_x', 'bbox_y', 'bbox_width', 'bbox_height'))
            iou = box_iou(ref, actual)
        evaluated.append({'session': label['session'], 'variant': variant, 'frame': idx, 'detected': int(detected),
                          'contact_pixel_x': x, 'contact_pixel_y': y, 'visible_base_y_px': base,
                          'base_uncertainty_px': label['base_uncertainty_px'],
                          'contact_y_error_px': abs(y - base) if detected and base is not None else None,
                          'contact_x_inside_coarse_box': int(int(label['bbox_x_min']) <= x <= int(label['bbox_x_max'])) if detected else None,
                          'bbox_iou_coarse': iou, 'raw_contact_z_m': number(r, 'raw_contact_z_m')})
write_csv(ROOT / 'coarse_label_comparison.csv', evaluated)
write_csv(ROOT / 'raw_assets_manifest.csv', manifest)

integrity = []
old = REPO / 'Experimental_results/2026-10-06/raw_velocity_confidence_candidate'
for source in provenance['sources']:
    session = source['session']
    recorded = json.loads((Path(source['path']) / 'metadata.json').read_text())['parameters']
    overrides_changed = any(recorded.get(k) != v for k, v in provenance['detector_overrides'].items())
    candidates = [old / session / 'recomputed_inputs.csv', old / 'controls' / session / 'recomputed_inputs.csv',
                  old / 'motion_controls' / session / 'recomputed_inputs.csv']
    if overrides_changed:
        # The old no-box video replay used its historical unrestricted aspect
        # setting. Compare to the prior quality diagnosis with EXACTLY today's
        # segmentation settings instead; do not silently call 853 mismatches OK.
        quality = REPO / 'Experimental_results/2026-10-06/ground_contact_quality_diagnosis'
        qp = json.loads((quality / 'provenance.json').read_text())
        qsource = next((s for s in qp['sources'] if s['session'] == session), None)
        if qsource is None or qsource['parameters'] != source['parameters'] or qsource['sha256'] != source['sha256']:
            raise ValueError('no equivalent-settings baseline reference')
        reference = quality / 'frame_quality.csv'
        previous = [r for r in read(reference) if r['session'] == session]
        old_detected_key, old_z_key, new_z_key = 'video_detected', 'contact_z_m', 'raw_contact_z_m'
    else:
        reference = next((p for p in candidates if p.exists()), None)
        if reference is None:
            raise ValueError('missing baseline reference')
        previous = read(reference)
        old_detected_key, old_z_key, new_z_key = 'detected', 'z_m', 'z_m'
    current = [r for r in rows if r['session'] == session and r['variant'] == 'baseline']
    if len(previous) != len(current):
        raise AssertionError('baseline frame count changed')
    mismatch = sum(flag(a, old_detected_key) != flag(b, 'detected') for a, b in zip(previous, current))
    deltas = [abs(number(a, old_z_key) - number(b, new_z_key)) for a, b in zip(previous, current)
              if flag(a, old_detected_key) and flag(b, 'detected')]
    if mismatch or any(d > 1e-10 for d in deltas):
        raise AssertionError('baseline geometry changed')
    integrity.append({'session': session, 'reference': str(reference.relative_to(REPO)),
                      'same_segmentation_settings': True, 'frames': len(current), 'detected_flag_mismatches': mismatch,
                      'max_baseline_z_delta_m': max(deltas) if deltas else None})
write_csv(ROOT / 'baseline_integrity.csv', integrity)

colors = dict(zip(VARIANTS, ('black', '#d98a00', '#3076c8', '#b245bc', '#16a397', '#ce3240')))
fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
r03 = next(s for s in sources if 'hardware_r03' in s)
for variant in VARIANTS:
    group = [r for r in rows if r['session'] == r03 and r['variant'] == variant]
    times = [float(r['time_sec']) for r in group]
    zs = [number(r, 'raw_contact_z_m') if flag(r, 'detected') else np.nan for r in group]
    ys = [number(r, 'contact_pixel_y') if flag(r, 'detected') else np.nan for r in group]
    axes[0].plot(times, zs, label=variant, color=colors[variant], linewidth=1)
    axes[1].plot(times, ys, color=colors[variant], linewidth=1)
    axes[2].plot(times, [number(r, 'adjacent_motion_residual_m') or 0 for r in group], color=colors[variant], linewidth=1)
axes[0].set_ylabel('Raw contact z (m)')
axes[1].set_ylabel('Contact pixel y')
axes[2].set_ylabel('Adjacent motion residual (m)')
axes[2].set_xlabel('Recorded elapsed time (s)')
# Missing pairs are not zero residuals: hide those samples entirely.
for line, variant in zip(axes[2].lines, VARIANTS):
    group = [r for r in rows if r['session'] == r03 and r['variant'] == variant]
    line.set_ydata([number(r, 'adjacent_motion_residual_m') if number(r, 'adjacent_motion_residual_m') is not None else np.nan for r in group])
for label in labels:
    if label['session'] == r03 and flag(label, 'base_visible'):
        t = float(lookup[(r03, 'baseline', int(label['frame']))]['time_sec'])
        axes[1].errorbar([t], [float(label['visible_base_y_px'])], yerr=float(label['base_uncertainty_px']),
                         fmt='o', color='#149346', capsize=3)
axes[0].legend(fontsize=9, loc='upper left')
for ax in axes:
    ax.grid(alpha=.25)
fig.suptitle('r03 offline contact candidates: stability is not absolute distance accuracy\nGreen points: coarse visible-base labels (+/-5 px); no runtime change')
fig.tight_layout()
fig.savefig(ROOT / 'r03_contact_candidate_timeline.png', dpi=140)
plt.close(fig)

fig, ax = plt.subplots(figsize=(11, 5))
for i, variant in enumerate(VARIANTS):
    points = [r for r in evaluated if r['variant'] == variant and r['visible_base_y_px'] is not None]
    x = np.arange(len(points)) + (i - 2.5) * .12
    y = [r['contact_y_error_px'] if r['contact_y_error_px'] is not None else np.nan for r in points]
    ax.scatter(x, y, label=variant, color=colors[variant])
ax.axhline(5, color='#149346', linestyle='--', label='coarse label uncertainty: 5 px')
ax.set_xticks(np.arange(6), ['r01:396', 'r03:100', 'r03:206', 'r03:306', 'r03:307', 'r03:350'])
ax.set_ylabel('Absolute contact pixel-y discrepancy (px)')
ax.set_title('Exploratory visible-base comparison (6 labelled frames)\nMissing detections omitted, not counted as zero error; not metric ground truth')
ax.grid(alpha=.25)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(ROOT / 'coarse_base_label_comparison.png', dpi=140)
plt.close(fig)

for name, expected in provenance['implementation_sha256'].items():
    if sha256(REPO / 'src' / name) != expected:
        raise AssertionError(f'implementation changed since analysis: {name}')
(ROOT / 'validation.json').write_text(json.dumps({'sessions': len(sources), 'video_frames': len(rows) // len(VARIANTS),
    'variant_frame_rows': len(rows), 'baseline_geometry_matches_prior_replay': True,
    'implementation_hash_matches': True, 'raw_png_pixels_equal_decoded_video': True,
    'coarse_label_frames': len(labels), 'labelled_visible_bases': sum(flag(r, 'base_visible') for r in labels),
    'labels_used_by_candidate': False, 'production_changed': False, 'hardware_approved': False}, indent=2) + '\n')
print('Assets and baseline integrity checks completed.')
