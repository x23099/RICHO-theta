"""Read-only-in-effect tracing of the frozen scene extractor and consensus."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent / 'scene_uniform_validation_r01'
OLD = ROOT / 'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0] = [str(ROOT / 'src'), str(OLD)]
from cone_dataset import read_csv, write_csv, sha256
from angular_fisheye_geometry import camera_from_candidate, unproject
from scene_geometry import infer_up, unit, angle_degrees, plane_from_pixels
from curve_geometry import extract_curve_planes


def select_representatives(samples):
    groups = defaultdict(list)
    for row in samples:
        groups[row['session'], row['role']].append(row)
    return [sorted(group, key=lambda r: int(r['frame']))[len(group) // 2]
            for _, group in sorted(groups.items())]


def trace_consensus(normals, prior):
    """Same ordering and operations as infer_up; never exports a rejected pose."""
    official = infer_up(normals, prior)  # Also validates the input contract.
    n = np.asarray(normals, float).reshape(-1, 3)
    prior = unit(prior)
    details = dict(plane_count=len(n), pairs=0, diverse_pairs=0, prior_compatible_pairs=0,
                   seed_inliers=0, refinement_1_inliers=None, refinement_2_inliers=None,
                   terminal_reason=official['reason'], accepted=official['accepted'],
                   inliers=official['inliers'], diagnostic_residuals_deg_json='',
                   diagnostic_inlier_indices_json='', usable_for_ffb=False)
    g = None
    inside = None
    if len(n) >= 6:
        best = None
        for i in range(len(n)):
            for j in range(i):
                details['pairs'] += 1
                spread = np.degrees(np.arccos(np.clip(abs(n[i] @ n[j]), -1, 1)))
                if spread < 8:
                    continue
                details['diverse_pairs'] += 1
                candidate = unit(np.cross(n[i], n[j]))
                candidate = candidate if candidate @ prior >= 0 else -candidate
                if angle_degrees(candidate, prior) > 20:
                    continue
                details['prior_compatible_pairs'] += 1
                residual = np.degrees(np.arcsin(np.clip(abs(n @ candidate), 0, 1)))
                members = residual <= 1
                score = (int(members.sum()), -float(np.median(residual[members])))
                if best is None or score > best[0]:
                    best = (score, candidate, members)
        if best is not None:
            _, g, inside = best
            details['seed_inliers'] = int(inside.sum())
            for iteration in range(2):
                if inside.sum() < 6:
                    break
                _, _, vt = np.linalg.svd(n[inside], full_matrices=False)
                g = vt[-1]
                g = g if g @ prior >= 0 else -g
                residual = np.degrees(np.arcsin(np.clip(abs(n @ g), 0, 1)))
                inside = residual <= 1
                details[f'refinement_{iteration + 1}_inliers'] = int(inside.sum())
            residual = np.degrees(np.arcsin(np.clip(abs(n @ g), 0, 1)))
            details['diagnostic_residuals_deg_json'] = json.dumps(residual.tolist())
            details['diagnostic_inlier_indices_json'] = json.dumps(np.flatnonzero(inside).tolist())
    # Equivalence asserts are part of every real-data replay, not just unit tests.
    if official['accepted']:
        np.testing.assert_allclose(g, official['up'], atol=1e-12, rtol=0)
        assert int(inside.sum()) == official['inliers']
    elif official['reason'] == 'insufficient_consensus':
        assert inside is not None and int(inside.sum()) == official['inliers'] < 6
    elif official['reason'] == 'fewer_than_six_distinct_planes':
        assert len(n) < 6 and g is None
    elif official['reason'] == 'no_diverse_plane_pair_within_prior':
        assert details['prior_compatible_pairs'] == 0
    elif official['reason'] == 'insufficient_final_consensus':
        assert int(inside.sum()) == official['inliers'] < 6
    elif official['reason'] == 'poor_geometry_or_prior':
        assert inside.sum() >= 6
    return official, details


def trace_extraction(image, camera):
    """Same native pixels and operations; retain formerly discarded pieces."""
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError('native uint8 BGR frame required')
    gray = cv2.cvtColor(image[:, :640], cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(cv2.Canny(gray, 60, 120))
    roi = (xs >= 40) & (xs <= 600) & (ys >= 60) & (ys <= 300)
    native = np.column_stack((xs, ys)).astype(float)[roi]
    rays, valid = unproject(native, camera, image_size=(1280, 720))
    valid &= rays[:, 2] >= np.cos(np.deg2rad(75))
    counts = dict(canny_front_edge_pixels=len(xs), roi_edge_pixels=len(native),
                  angular_valid_edge_pixels=int(valid.sum()),
                  roi_outside_edge_pixels=int((~roi).sum()), hough_candidates=0,
                  pieces=0, passed_shape=0, passed_plane=0, distinct_planes=0)
    native, rays = native[valid], rays[valid]
    points = 200 * rays[:, :2] / rays[:, 2, None]
    candidates = cv2.HoughLinesPointSet(
        points.astype(np.float32).reshape(-1, 1, 2), 200, 40, -1000, 1000, 1,
        0, np.pi, np.pi / 720) if len(points) else None
    rows = []
    for index, (votes, rho, theta) in enumerate(candidates.reshape(-1, 3) if candidates is not None else []):
        counts['hough_candidates'] += 1
        distance = abs(points @ np.array([np.cos(theta), np.sin(theta)]) - rho)
        ids = np.flatnonzero(distance <= 1)
        bins = np.floor(native[ids, 1] / 2).astype(int)
        chosen = []
        for bin_id in np.unique(bins):
            options = ids[bins == bin_id]
            chosen.append(options[np.argmin(distance[options])])
        observed = native[chosen]
        pieces = np.split(observed, np.flatnonzero(np.diff(observed[:, 1]) > 6) + 1)
        for part, actual in enumerate(pieces):
            counts['pieces'] += 1
            span = np.ptp(actual, axis=0) if len(actual) else np.zeros(2)
            row = dict(line_index=index, part=part, hough_votes=float(votes),
                       edge_points=len(actual), native_x_span=float(span[0]), native_y_span=float(span[1]),
                       first_native_json=json.dumps(actual[0].tolist()) if len(actual) else '',
                       last_native_json=json.dumps(actual[-1].tolist()) if len(actual) else '',
                       native_points_sha256=hashlib.sha256(actual.astype('<i4').tobytes()).hexdigest(),
                       actual_edge_pixels_json=json.dumps(actual.tolist()),
                       passes_shape=False, passes_plane=False, accepted=False,
                       reason='fewer_than_30_actual_edge_points', normal_json='',
                       plane_rms_deg=None, plane_max_deg=None,
                       duplicate_of_line_index=None, duplicate_of_part=None, usable_for_ffb=False)
            if len(actual) >= 30:
                if span[1] < 60:
                    row['reason'] = 'native_y_span_under_60'
                elif span[1] < 1.5 * span[0]:
                    row['reason'] = 'not_steep_enough_in_native_coordinates'
                else:
                    row['passes_shape'] = True
                    counts['passed_shape'] += 1
                    plane = plane_from_pixels(actual, camera)
                    row.update(reason=plane['reason'], accepted=plane['accepted'],
                               passes_plane=plane['accepted'],
                               normal_json=json.dumps(plane['normal']) if plane.get('normal') is not None else '',
                               plane_rms_deg=plane.get('plane_rms_deg'), plane_max_deg=plane.get('plane_max_deg'))
                    counts['passed_plane'] += int(plane['accepted'])
            rows.append(row)
    kept = []
    for row in sorted((r for r in rows if r['accepted']), key=lambda r: -r['native_y_span']):
        normal = np.array(json.loads(row['normal_json']))
        duplicate = next((r for r in kept if np.degrees(np.arccos(np.clip(
            abs(normal @ np.array(json.loads(r['normal_json']))), -1, 1))) < 2), None)
        if duplicate is not None:
            row.update(accepted=False, reason='duplicate_ray_plane',
                       duplicate_of_line_index=duplicate['line_index'], duplicate_of_part=duplicate['part'])
        else:
            kept.append(row)
    counts['distinct_planes'] = len(kept)
    # Full equality check against frozen code, including all emitted/rejected plane rows.
    official = extract_curve_planes(image, camera)
    old_by_key = {(r['line_index'], r['part']): r for r in official}
    traced_by_key = {(r['line_index'], r['part']): r for r in rows if r['passes_shape']}
    assert old_by_key.keys() == traced_by_key.keys()
    for key, old in old_by_key.items():
        traced = traced_by_key[key]
        assert old['accepted'] == traced['accepted'] and old['reason'] == traced['reason'], key
        assert old['actual_edge_pixels_json'] == json.loads(traced['actual_edge_pixels_json']), key
        if old.get('normal') is not None:
            np.testing.assert_array_equal(old['normal'], json.loads(traced['normal_json']))
    return rows, counts


def verify_previous():
    files = []
    for folder in ('intake_r01', 'scene_results_r01', 'pooled_results_r01'):
        path = PREVIOUS / folder / 'summary.json'
        summary = json.loads(path.read_text())
        for source, value in summary['source_sha256'].items():
            assert sha256(Path(source)) == value, source
        for name, value in summary['output_sha256'].items():
            target = path.parent / name
            assert sha256(target) == value, target
        files.append(path)
    return files


def main():
    output = HERE / 'results_r02'
    if output.exists():
        raise ValueError('completed or partial output is preserved; choose a new version')
    manifests = verify_previous()
    candidate = ROOT / 'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor = ROOT / 'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    camera = camera_from_candidate(json.loads(candidate.read_text()))
    tf = json.loads(floor.read_text())
    prior = np.array(tf['nominal_transform'])[:3, :3].T @ np.array([0., 0., 1.])
    source_files = manifests + [candidate, floor, Path(__file__), HERE / 'method.md',
                               OLD / 'scene_geometry.py', OLD / 'curve_geometry.py',
                               ROOT / 'src/angular_fisheye_geometry.py', ROOT / 'src/cone_dataset.py']
    samples = read_csv(PREVIOUS / 'intake_r01/native_sample_manifest.csv')
    frames = read_csv(PREVIOUS / 'scene_results_r01/image_diagnostics.csv')
    lines = read_csv(PREVIOUS / 'scene_results_r01/line_candidates.csv')
    pools = read_csv(PREVIOUS / 'pooled_results_r01/plane_clusters.csv')
    for path in (PREVIOUS / 'intake_r01/native_sample_manifest.csv',
                 PREVIOUS / 'scene_results_r01/image_diagnostics.csv',
                 PREVIOUS / 'scene_results_r01/line_candidates.csv',
                 PREVIOUS / 'pooled_results_r01/plane_clusters.csv',
                 PREVIOUS / 'pooled_results_r01/session_hypotheses.csv'):
        source_files.append(path)
    sources = {str(p): sha256(p) for p in source_files}
    groups = defaultdict(list)
    for row in lines:
        if row['accepted'] == 'True':
            groups[row['session'], int(row['frame'])].append(row)
    traced_frames, residual_rows = [], []
    for frame in frames:
        members = groups[frame['session'], int(frame['frame'])]
        normals = np.array([json.loads(r['normal_json']) for r in members]).reshape(-1, 3)
        pose, detail = trace_consensus(normals, prior)
        assert pose['accepted'] == (frame['accepted'] == 'True')
        assert pose['reason'] == frame['reason'] and pose['inliers'] == int(frame['inliers'])
        if pose['accepted']:
            np.testing.assert_array_equal(pose['up'], json.loads(frame['up_optical_json']))
        residuals = json.loads(detail['diagnostic_residuals_deg_json'] or '[]')
        for index, row in enumerate(members):
            residual_rows.append(dict(session=frame['session'], frame=frame['frame'], role=frame['role'],
                plane_index=index, line_index=row['line_index'], part=row['part'],
                first_native_json=row['first_native_json'], last_native_json=row['last_native_json'],
                normal_json=row['normal_json'], residual_to_diagnostic_direction_deg=residuals[index] if residuals else None,
                within_one_degree=bool(residuals[index] <= 1) if residuals else None,
                accepted_pose=pose['accepted'], physical_vertical_verified=False, usable_for_ffb=False))
        traced_frames.append(dict(session=frame['session'], frame=frame['frame'], role=frame['role'], **detail))
    traced_pools, pool_residuals = [], []
    pool_groups = defaultdict(list)
    for row in pools:
        if row['accepted'] == 'True':
            pool_groups[row['session'], row['role']].append(row)
    old_pool = read_csv(PREVIOUS / 'pooled_results_r01/session_hypotheses.csv')
    for old in old_pool:
        for role, prefix in (('estimate', 'training'), ('heldout', 'heldout')):
            members = pool_groups[old['session'], role]
            normals = np.array([json.loads(r['normal_json']) for r in members]).reshape(-1, 3)
            pose, detail = trace_consensus(normals, prior)
            assert pose['accepted'] == (old[prefix + '_accepted'] == 'True')
            assert pose['reason'] == old[prefix + '_reason']
            assert pose['inliers'] == int(old[prefix + '_inlier_planes'])
            residuals = json.loads(detail['diagnostic_residuals_deg_json'] or '[]')
            for index, row in enumerate(members):
                pool_residuals.append(dict(session=old['session'], role=role, cluster=row['cluster'],
                    different_frames=row['different_frames'], residual_to_diagnostic_direction_deg=residuals[index] if residuals else None,
                    within_one_degree=bool(residuals[index] <= 1) if residuals else None,
                    accepted_pose=pose['accepted'], usable_for_ffb=False))
            traced_pools.append(dict(session=old['session'], role=role, **detail))
    representatives = select_representatives(samples)
    # Selection persisted before any representative image processing.
    output.mkdir()
    (output / 'representative_plan.json').write_text(json.dumps(representatives, indent=2) + '\n')
    extraction_rows, stage_rows = [], []
    old_line_index = {(r['session'], int(r['frame']), int(r['line_index']), int(r['part'])): r for r in lines}
    for sample in representatives:
        path = Path(sample['source_native_png'])
        assert sha256(path) == sample['png_sha256']
        sources[str(path)] = sample['png_sha256']
        image = cv2.imread(str(path))
        rows, counts = trace_extraction(image, camera)
        for row in rows:
            key = (sample['session'], int(sample['frame']), row['line_index'], row['part'])
            if row['passes_shape']:
                old = old_line_index[key]
                assert old['native_points_sha256'] == row['native_points_sha256']
                assert old['reason'] == row['reason'] and (old['accepted'] == 'True') == row['accepted']
            extraction_rows.append(dict(session=sample['session'], frame=sample['frame'], role=sample['role'], **row))
        stage_rows.append(dict(session=sample['session'], frame=sample['frame'], role=sample['role'],
                               source_native_png=str(path), png_sha256=sample['png_sha256'], **counts))
        print(sample['session'], sample['role'], 'edges', counts['roi_edge_pixels'],
              'shape', counts['passed_shape'], 'planes', counts['distinct_planes'], flush=True)
    reason_rows = []
    for session in sorted({r['session'] for r in frames}):
        selected = [r for r in traced_frames if r['session'] == session]
        for role in ('estimate', 'heldout'):
            rows = [r for r in selected if r['role'] == role]
            for reason, count in sorted(Counter(r['terminal_reason'] for r in rows).items()):
                reason_rows.append(dict(session=session, role=role, reason=reason, images=count,
                                         role_total=len(rows), usable_for_ffb=False))
    for name, rows in [('all_frame_consensus.csv', traced_frames), ('all_frame_plane_residuals.csv', residual_rows),
                       ('pooled_consensus.csv', traced_pools), ('pooled_plane_residuals.csv', pool_residuals),
                       ('representative_stage_counts.csv', stage_rows), ('representative_all_pieces.csv', extraction_rows),
                       ('session_terminal_reasons.csv', reason_rows)]:
        write_csv(output / name, rows)
    assert all(sha256(Path(p)) == h for p, h in sources.items())
    report = dict(status='COMPLETED_FROZEN_RULE_REJECTION_AUDIT_NOT_POSE_RECOVERY', work_date='2026-10-22',
        sampled_images=len(frames), pooled_hypotheses=len(traced_pools), representative_images=len(representatives),
        traced_hough_pieces=len(extraction_rows), frozen_algorithm_mismatches=0,
        terminal_reasons=dict(Counter(r['terminal_reason'] for r in traced_frames)),
        source_sha256=sources, metric_labels_used=False, source_images_edited=False,
        production_settings_changed=False, physical_output=False, usable_for_ffb=False,
        output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
