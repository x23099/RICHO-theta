"""Predeclared one-variable ROI probe; no metric consumers or physical output."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

from audit import HERE, ROOT, PREVIOUS, OLD, verify_previous, trace_consensus
from cone_dataset import read_csv, write_csv, sha256
from angular_fisheye_geometry import camera_from_candidate
from curve_geometry import extract_curve_planes
from roi_geometry import extract_with_roi
sys.path.insert(0, str(PREVIOUS))
from analyze_scenes import summarize_directions


def main():
    output = HERE / 'roi_probe_results_r01'
    if (output / 'summary.json').exists():
        raise ValueError('completed output is frozen')
    sources = verify_previous()
    candidate = ROOT / 'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor = ROOT / 'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    sources += [candidate, floor, Path(__file__), HERE / 'roi_geometry.py', HERE / 'roi_probe_method.md',
                HERE / 'audit.py', HERE / 'results_r02/summary.json', HERE / 'results_r02/representative_plan.json',
                OLD / 'curve_geometry.py', OLD / 'scene_geometry.py', PREVIOUS / 'analyze_scenes.py',
                ROOT / 'src/angular_fisheye_geometry.py']
    source_hashes = {str(p): sha256(p) for p in sources}
    camera = camera_from_candidate(json.loads(candidate.read_text()))
    tf = json.loads(floor.read_text())
    T = np.array(tf['transform_target_from_source'])
    prior = np.array(tf['nominal_transform'])[:3, :3].T @ np.array([0., 0., 1.])
    samples = read_csv(PREVIOUS / 'intake_r01/native_sample_manifest.csv')
    reps = json.loads((HERE / 'results_r02/representative_plan.json').read_text())
    rep_keys = {(r['session'], int(r['frame'])) for r in reps}
    spec = dict(work_date='2026-10-22', source_sha256=source_hashes, roi_xyxy=[40, 60, 600, 430],
                metric_labels_used=False, physical_output=False)
    if output.exists():
        assert json.loads((output / 'run_spec.json').read_text()) == spec
    else:
        output.mkdir()
        (output / 'run_spec.json').write_text(json.dumps(spec, indent=2) + '\n')
    groups = defaultdict(list)
    for row in samples:
        groups[row['session']].append(row)
    checkpoint = output / 'sessions'
    checkpoint.mkdir(exist_ok=True)
    all_frames, all_lines, sessions = [], [], []
    checked_baseline = 0
    for session, group in sorted(groups.items()):
        folder = checkpoint / session
        if (folder / 'complete.json').exists():
            done = json.loads((folder / 'complete.json').read_text())
            assert done['run_spec_sha256'] == sha256(output / 'run_spec.json')
            assert done['data_sha256'] == sha256(folder / 'data.json')
            for r in group:
                assert sha256(Path(r['source_native_png'])) == r['png_sha256']
            data = json.loads((folder / 'data.json').read_text())
            print('resumed', session, flush=True)
        else:
            if folder.exists():
                raise ValueError('incomplete checkpoint preserved; choose a new output version')
            frame_rows, line_rows, baseline_count = [], [], 0
            for sample in group:
                path = Path(sample['source_native_png'])
                assert sha256(path) == sample['png_sha256']
                image = cv2.imread(str(path))
                if (session, int(sample['frame'])) in rep_keys:
                    assert extract_with_roi(image, camera, y_max=300) == extract_curve_planes(image, camera)
                    baseline_count += 1
                curves = extract_with_roi(image, camera, y_max=430)
                accepted = [r for r in curves if r['accepted']]
                normals = np.array([r['normal'] for r in accepted]).reshape(-1, 3)
                pose, trace = trace_consensus(normals, prior)
                frame_rows.append(dict(session=session, frame=int(sample['frame']), time_sec=float(sample['time_sec']),
                    role=sample['role'], source_native_png=str(path), png_sha256=sample['png_sha256'],
                    accepted=pose['accepted'], reason=pose['reason'], distinct_ray_planes=len(normals),
                    inliers=pose['inliers'], up_optical=pose['up'], seed_inliers=trace['seed_inliers'],
                    median_residual_deg=pose['median_residual_deg'], normal_span_deg=pose['normal_span_deg'],
                    rank_gap_ratio=pose['rank_gap_ratio'], usable_for_ffb=False))
                residuals = json.loads(trace['diagnostic_residuals_deg_json'] or '[]')
                accepted_index = {(r['line_index'], r['part']): i for i, r in enumerate(accepted)}
                for curve in curves:
                    pixels = np.array(curve['actual_edge_pixels_json'])
                    index = accepted_index.get((curve['line_index'], curve['part']))
                    line_rows.append(dict(session=session, frame=int(sample['frame']), role=sample['role'],
                        line_index=curve['line_index'], part=curve['part'], accepted=curve['accepted'], reason=curve['reason'],
                        first_native_json=json.dumps(pixels[0].tolist()), last_native_json=json.dumps(pixels[-1].tolist()),
                        native_points_sha256=hashlib.sha256(pixels.astype('<i4').tobytes()).hexdigest(),
                        edge_points=len(pixels), normal_json=json.dumps(curve.get('normal')),
                        residual_to_diagnostic_direction_deg=residuals[index] if index is not None and residuals else None,
                        uses_pixels_below_old_roi=bool(np.any(pixels[:, 1] > 300)),
                        architectural_vertical_independently_verified=False, usable_for_ffb=False))
            summary = dict(session=session, **summarize_directions(frame_rows, T))
            # Stored transforms are omitted: this probe does not create a metric-consumable model.
            summary.pop('conditional_transform')
            data = dict(frames=frame_rows, lines=line_rows, session=summary, baseline_equivalence_images=baseline_count)
            folder.mkdir()
            (folder / 'data.json').write_text(json.dumps(data, indent=2) + '\n')
            (folder / 'complete.json').write_text(json.dumps(dict(data_sha256=sha256(folder / 'data.json'),
                run_spec_sha256=sha256(output / 'run_spec.json')), indent=2) + '\n')
            print('finished', session, summary['usable_estimate_frames'], summary['usable_heldout_frames'],
                  summary['temporal_validation'], summary['reason'], flush=True)
        all_frames.extend(data['frames'])
        all_lines.extend(data['lines'])
        sessions.append(data['session'])
        checked_baseline += data['baseline_equivalence_images']
    baseline = read_csv(PREVIOUS / 'scene_results_r01/image_diagnostics.csv')
    base_index = {(r['session'], int(r['frame'])): r for r in baseline}
    comparisons = []
    for row in all_frames:
        base = base_index[row['session'], row['frame']]
        comparisons.append(dict(session=row['session'], frame=row['frame'], role=row['role'],
            baseline_accepted=base['accepted'], baseline_reason=base['reason'], baseline_inliers=base['inliers'],
            probe_accepted=row['accepted'], probe_reason=row['reason'], probe_inliers=row['inliers'], usable_for_ffb=False))
    frame_csv = [{k + '_json' if k == 'up_optical' else k: json.dumps(v) if k == 'up_optical' else v
                  for k, v in row.items()} for row in all_frames]
    session_csv = [{k + '_json' if k == 'up_optical' else k: json.dumps(v) if k == 'up_optical' else v
                    for k, v in row.items()} for row in sessions]
    for name, rows in [('image_diagnostics.csv', frame_csv), ('line_candidates.csv', all_lines),
                       ('session_hypotheses.csv', session_csv), ('paired_comparison.csv', comparisons)]:
        write_csv(output / name, rows)
    assert all(sha256(Path(p)) == h for p, h in source_hashes.items())
    report = dict(status='COMPLETED_ONE_ROI_ABLATION_NOT_PHYSICAL_VERTICAL_OR_DISTANCE_VALIDATION',
        work_date='2026-10-22', sampled_images=len(samples), accepted_image_hypotheses=sum(r['accepted'] for r in all_frames),
        temporally_checked_models=sum(r['metric_eligible'] for r in sessions),
        baseline_equivalence_images=checked_baseline, roi_xyxy=[40, 60, 600, 430],
        source_sha256=source_hashes, metric_labels_used=False, source_images_edited=False,
        production_settings_changed=False, physical_output=False, usable_for_ffb=False,
        output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
