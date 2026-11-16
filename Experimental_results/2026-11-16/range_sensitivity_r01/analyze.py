"""One-factor counterfactuals on three verified supports; no live/ROS/CUDA I/O."""
import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from angular_fisheye_geometry import camera_from_candidate, unproject
from cone_motion_range import checked_current_support, horizontal_range, parse_motion_profile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def tilt_toward_ray(model, ray, angle_deg):
    """Positive angle reduces downward incidence; NOT a vehicle pose estimate."""
    require(type(angle_deg) in (int, float) and math.isfinite(angle_deg) and abs(angle_deg) <= 5,
            'finite small explicit angle required')
    up, ray = np.asarray(model['up_optical'], float), np.asarray(ray, float)
    require(up.shape == ray.shape == (3,) and np.isfinite(up).all() and np.isfinite(ray).all()
            and np.isclose(np.linalg.norm(up), 1, atol=1e-10, rtol=0)
            and np.isclose(np.linalg.norm(ray), 1, atol=1e-10, rtol=0), 'unit vectors required')
    axis = np.cross(up, ray)
    require(np.linalg.norm(axis) > 1e-12, 'ray/normal plane undefined')
    axis = axis / np.linalg.norm(axis)
    theta = math.radians(angle_deg)
    rotated = up*math.cos(theta) + np.cross(axis, up)*math.sin(theta)
    rotated += axis*float(axis @ up)*(1-math.cos(theta))
    output = copy.deepcopy(model)
    output['up_optical'] = (rotated/np.linalg.norm(rotated)).tolist()
    return output


def range_at(point, camera, model):
    rays, valid = unproject([point], camera, image_size=(1280, 720))
    return horizontal_range(rays[0], model) if valid[0] else None


def scenarios(point, camera, model):
    ray, valid = unproject([point], camera, image_size=(1280, 720))
    require(bool(valid[0]), 'baseline support outside camera domain')
    baseline = horizontal_range(ray[0], model)
    require(baseline is not None, 'baseline grazing ray')
    variants = [('baseline', list(point), copy.deepcopy(model), 0, 0, 0., 0.)]
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        variants.append((f'pixel_dx{dx:+d}_dy{dy:+d}', [point[0]+dx, point[1]+dy],
                         copy.deepcopy(model), dx, dy, 0., 0.))
    for dh in (-.01, .01):
        changed = copy.deepcopy(model)
        changed['height_m'] += dh
        require(changed['height_m'] > 0, 'hypothetical height must remain positive')
        variants.append((f'height_{dh:+.2f}m', list(point), changed, 0, 0, dh, 0.))
    for angle in (-1., 1.):
        variants.append((f'normal_toward_ray_{angle:+.0f}deg', list(point),
                         tilt_toward_ray(model, ray[0], angle), 0, 0, 0., angle))
    result = []
    for label, pixel, changed, dx, dy, dh, angle in variants:
        value = range_at(pixel, camera, changed)
        result.append(dict(case=label, x_native=pixel[0], y_native=pixel[1],
            dx_px=dx, dy_px=dy, height_change_m=dh, normal_toward_ray_change_deg=angle,
            scenario_height_m=changed['height_m'], range_m=value,
            delta_from_baseline_m=value-baseline if value is not None else None,
            range_available=value is not None, counterfactual_only=label != 'baseline'))
    return result


def verified_rows(path, expected_sha, session, wanted):
    found, line_hashes, digest = {}, {}, hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            line = stream.readline(4*1024*1024+1)
            if not line:
                break
            require(len(line) <= 4*1024*1024 and line.endswith(b'\n'), 'bounded complete main line required')
            digest.update(line)
            row = json.loads(line)
            if row.get('frame') in wanted:
                require(row.get('session') == session and row['frame'] not in found, 'ambiguous target frame')
                found[row['frame']] = row
                line_hashes[row['frame']] = hashlib.sha256(line).hexdigest()
    require(digest.hexdigest() == expected_sha, 'full main log SHA mismatch')
    require(set(found) == set(wanted), 'missing exact target frame')
    return found, line_hashes


def checked_baseline(recomputed, logged, audited):
    # CPU/GPU NumPy implementations may differ by a few floating-point ULPs.
    # The two recorded values must match exactly; geometry is checked at 1pm.
    require(logged == audited and math.isclose(recomputed, logged, abs_tol=1e-12, rel_tol=0),
            'baseline does not reproduce verified log')
    return recomputed - logged


def run(args):
    audit_path, intake, output = args.audit.resolve(), args.intake_dir.resolve(), args.output_dir.resolve()
    require(not output.exists(), 'new output directory required')
    audit = json.loads(audit_path.read_bytes())
    require(audit['state'] == 'pass' and audit['schema'] == 'body_display_three_distance_closed_audit_v1',
            'verified closed-run audit required')
    config_path = ROOT/'src/cone_distance_diagnostic_config.json'
    settings = json.loads(config_path.read_bytes())
    camera_path = ROOT/settings['camera_candidate']
    require(sha(config_path) == audit['engine_metadata']['config_sha256']
            and sha(camera_path) == settings['camera_sha256'], 'config/camera binding mismatch')
    profile_path = intake/'primary/motion_profile_used.json'
    require(sha(profile_path) == audit['engine_metadata']['profile_sha256']
            == audit['supplied_files_sha256']['primary/motion_profile_used.json'], 'profile binding mismatch')
    camera = camera_from_candidate(json.loads(camera_path.read_bytes()))
    profile, _ = parse_motion_profile(profile_path.read_bytes(), settings)
    model = next(m for m in profile['models'] if m['id'] == profile['primary_model'])
    points = audit['reported_points']
    require(len(points) == 3 and len({p['frame'] for p in points}) == 3, 'three distinct verified points required')
    main_path = intake/'primary/motion_distance_frames.jsonl'
    actual, line_hashes = verified_rows(main_path, audit['supplied_files_sha256']['primary/motion_distance_frames.jsonl'],
                                        audit['session'], {p['frame'] for p in points})
    all_rows, summaries = [], []
    for anchor in points:
        main = actual[anchor['frame']]
        point, _ = checked_current_support(main['support_observation'])
        require(main['distance_available'] is True and point == main['support_pixel']
                and main['profile_sha256'] == sha(profile_path), 'valid recorded current support required')
        variants = scenarios(point, camera, model)
        baseline = variants[0]['range_m']
        numerical_difference = checked_baseline(baseline, main['horizontal_camera_foot_range_m'],
                                                anchor['logged_raw_range_m'])
        for case in variants:
            all_rows.append(dict(session=main['session'], frame=main['frame'],
                reported_measured_m=anchor['reported_measured_m'], **case))
        max_change = lambda predicate: max(abs(c['delta_from_baseline_m']) for c in variants
                                         if predicate(c) and c['range_available'])
        summaries.append(dict(frame=main['frame'], support_pixel=point,
            reported_measured_m=anchor['reported_measured_m'], baseline_range_m=baseline,
            baseline_reproduces_log_abs_tolerance_m=1e-12,
            baseline_numerical_difference_m=numerical_difference,
            baseline_exact_primary_line_sha256=line_hashes[main['frame']],
            max_abs_x_one_pixel_effect_m=max_change(lambda c: c['dx_px'] != 0),
            max_abs_y_one_pixel_effect_m=max_change(lambda c: c['dy_px'] != 0),
            max_abs_height_one_cm_effect_m=max_change(lambda c: c['height_change_m'] != 0),
            max_abs_normal_one_deg_effect_m=max_change(lambda c: c['normal_toward_ray_change_deg'] != 0),
            hypothetical_effects_not_measurement_uncertainties=True))
    # No profile, image, reference or live threshold is modified.
    paths = (Path(__file__), audit_path, config_path, camera_path, profile_path,
             ROOT/'src/cone_motion_range.py', ROOT/'src/angular_fisheye_geometry.py')
    result = dict(schema='offline_rigid_range_sensitivity_v1', state='pass', session=audit['session'],
        primary_model=model, points=summaries, scenario_count=len(all_rows),
        input_and_code_sha256={str(p.relative_to(ROOT)): sha(p) for p in paths},
        full_main_sha256=sha(main_path), scenarios_are_one_factor_counterfactuals=True,
        normal_rotation_is_per_target_ray_plane_NOT_vehicle_pitch_or_roll=True,
        actual_mount_height_or_tilt_error_measured=False, correction_fitted=False,
        runtime_or_profile_changed=False, independent_accuracy_certified=False,
        local_camera_cuda_ros_or_vehicle_started=False, usable_for_ffb=False)
    require(result['full_main_sha256'] == audit['supplied_files_sha256']['primary/motion_distance_frames.jsonl'],
            'main log changed during analysis')
    output.mkdir(parents=True)
    with (output/'scenarios.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=all_rows[0])
        writer.writeheader()
        writer.writerows(all_rows)
    result['scenarios_sha256'] = sha(output/'scenarios.csv')
    with (output/'sensitivity.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(state=result['state'], scenario_count=len(all_rows), points=summaries), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--intake-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
