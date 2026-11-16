"""Recover conditional optical vectors from SHA-bound logs; no ROS/FFB I/O."""
import argparse
from collections import Counter
import csv
import hashlib
from itertools import zip_longest
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from angular_fisheye_geometry import camera_from_candidate, unproject
from cone_motion_range import checked_current_support, parse_motion_profile
from driver_motion_handoff import checked_sample
from driver_motion_spatial import camera_floor_offset

MOTION_KEYS = {'linear_x', 'linear_mps', 'angular_z', 'angular_radps', 'imu_yaw_rate',
               'odom', 'odometry', 'telemetry', 'twist', 'vehicle_width_m',
               'transform_base_from_optical', 'base_from_optical', 'header', 'stamp'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def json_rows(path):
    with path.open('rb') as stream:
        while True:
            line = stream.readline(4*1024*1024+1)
            if not line:
                break
            require(len(line) <= 4*1024*1024 and line.endswith(b'\n'), 'bounded complete JSONL line required')
            yield json.loads(line)


def key_paths(value, prefix=''):
    if isinstance(value, dict):
        for key, child in value.items():
            path = prefix+'.'+key if prefix else key
            yield key, path
            if isinstance(child, (dict, list)):
                yield from key_paths(child, path)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                yield from key_paths(child, prefix+'[]')


def run(args):
    intake, output, raw_output = (p.resolve() for p in (args.intake_dir, args.output_dir, args.raw_output_dir))
    require(not output.exists() and not raw_output.exists(), 'new output directories required')
    require(ROOT/'recordings' in raw_output.parents and ROOT/'Experimental_results' in output.parents,
            'raw vectors under recordings; audit under Experimental_results required')
    audit_path, handoff_path = args.audit.resolve(), args.handoff_audit.resolve()
    audit, handoff = (json.loads(p.read_bytes()) for p in (audit_path, handoff_path))
    require(audit['state'] == handoff['state'] == 'pass'
            and audit['schema'] == 'body_display_three_distance_closed_audit_v1'
            and handoff['schema'] == 'offline_motion_range_handoff_audit_v1', 'formal passed audits required')
    require(sha(audit_path) == handoff['input_and_code_sha256'][str(audit_path.relative_to(ROOT))],
            'handoff/closed audit binding mismatch')
    for name, digest in audit['source_code_sha256'].items():
        require(sha(ROOT/'src'/name) == digest, 'live source changed: '+name)
    supplied = audit['supplied_files_sha256']
    for name, digest in supplied.items():
        require(sha(intake/name) == digest, 'submitted file SHA mismatch: '+name)
    for name, digest in handoff['input_and_code_sha256'].items():
        require(sha(ROOT/name) == digest, 'handoff evidence/source changed: '+name)
    samples_path = ROOT/handoff['samples']['path']
    require(sha(samples_path) == handoff['samples']['sha256'], 'handoff samples SHA mismatch')
    config_path = ROOT/'src/cone_distance_diagnostic_config.json'
    settings = json.loads(config_path.read_bytes())
    camera_path = ROOT/settings['camera_candidate']
    profile_path = intake/'primary/motion_profile_used.json'
    require(sha(config_path) == audit['engine_metadata']['config_sha256']
            and sha(camera_path) == settings['camera_sha256'], 'config/camera SHA mismatch')
    profile, profile_sha = parse_motion_profile(profile_path.read_bytes(), settings)
    require(profile_sha == audit['engine_metadata']['profile_sha256']
            and profile['config_sha256'] == sha(config_path), 'profile binding mismatch')
    model = next(m for m in profile['models'] if m['id'] == profile['primary_model'])
    camera = camera_from_candidate(json.loads(camera_path.read_bytes()))
    rows, pixels, positions, counts = [], [], [], Counter()
    inventory = {}
    main_name = 'primary/motion_distance_frames.jsonl'
    paths = set()
    for raw, sample in zip_longest(json_rows(intake/main_name), json_rows(samples_path)):
        require(raw is not None and sample is not None, 'main/handoff length mismatch')
        checked_sample(sample)
        paths.update(key_paths(raw))
        require(raw['session'] == sample['session'] == audit['session'] == handoff['session']
                and raw['frame'] == sample['frame'] and raw['source_time_sec'] == sample['source_time_sec']
                and raw['primary_model'] == sample['primary_model'] == model['id']
                and raw['profile_sha256'] == profile_sha, 'same-frame geometry/handoff identity mismatch')
        row = dict(session=sample['session'], frame=sample['frame'], source_time_sec=sample['source_time_sec'],
            source_reason=sample['reason'], range_available=sample['range_available'],
            source_distance_m=sample['distance_m'], conditional_geometry=None,
            spatial_reason='source_range_withheld', vehicle_xy_m=None,
            measured_motion=None, steering_gradient_available=False, usable_for_ffb=False,
            published_to_ros=False, replay_only=True)
        if sample['range_available']:
            point, _ = checked_current_support(raw['support_observation'])
            require(raw['distance_available'] and point == raw['support_pixel']
                    and raw['horizontal_camera_foot_range_m'] == sample['distance_m'],
                    'display-permitted actual support required')
            positions.append(len(rows)); pixels.append(point)
        else:
            require(sample['distance_m'] is None, 'withheld distance must remain null')
        rows.append(row)
        counts['samples'] += 1
    inventory[main_name] = sorted(path for _, path in paths)
    # Inspect the other supplied structured records, not arbitrary school-PC files.
    for name in supplied:
        if name == main_name:
            continue
        if name.endswith('.jsonl'):
            paths = set()
            for value in json_rows(intake/name):
                paths.update(key_paths(value))
            inventory[name] = sorted(path for _, path in paths)
        elif name.endswith('.json'):
            inventory[name] = sorted({path for _, path in key_paths(json.loads((intake/name).read_bytes()))})
    hits = {name: [p for p in paths if p.rsplit('.', 1)[-1] in MOTION_KEYS]
            for name, paths in inventory.items()}
    require(not any(hits.values()), 'unexpected motion/extrinsic fields found; inspect before claiming missing')
    rays, valid = unproject(pixels, camera, image_size=(1280, 720))
    require(bool(valid.all()), 'permitted support outside declared camera domain')
    max_difference, max_plane_residual = 0., 0.
    anchors = {p['frame']: p for p in audit['reported_points']}
    points = []
    for pos, pixel, ray in zip(positions, pixels, rays):
        geometry = camera_floor_offset(ray, up_optical=model['up_optical'], height_m=model['height_m'])
        require(geometry is not None, 'permitted ray has no conditional floor intersection')
        row = rows[pos]
        difference = abs(geometry['horizontal_range_m']-row['source_distance_m'])
        residual = abs(geometry['plane_residual_m'])
        require(math.isclose(geometry['horizontal_range_m'], row['source_distance_m'], abs_tol=1e-12, rel_tol=0)
                and residual < 1e-12, 'optical plane vector does not reproduce original range')
        max_difference, max_plane_residual = max(max_difference, difference), max(max_plane_residual, residual)
        row.update(conditional_geometry=geometry, spatial_reason='conditional_optical_vector_only')
        counts['conditional_optical_vector'] += 1
        if row['frame'] in anchors:
            points.append(dict(frame=row['frame'], reported_measured_m=anchors[row['frame']]['reported_measured_m'],
                support_x=pixel[0], support_y=pixel[1], source_range_m=row['source_distance_m'],
                vector_length_m=geometry['horizontal_range_m'],
                optical_x_m=geometry['offset_optical_m'][0], optical_y_m=geometry['offset_optical_m'][1],
                optical_z_m=geometry['offset_optical_m'][2], vehicle_xy_available=False))
    counts['withheld_no_geometry'] = counts['samples']-counts['conditional_optical_vector']
    require(counts['samples'] == handoff['counts']['samples']
            and counts['conditional_optical_vector'] == handoff['counts']['numeric'] and len(points) == 3,
            'range handoff count or screenshot anchor coverage mismatch')
    # Every sample retains null vehicle/motion data. This is not a gradient replay.
    require(all(r['vehicle_xy_m'] is None and r['measured_motion'] is None
                and r['steering_gradient_available'] is False for r in rows), 'unsupported risk input appeared')
    raw_output.mkdir(parents=True)
    raw_path = raw_output/'conditional_optical_vectors.jsonl'
    with raw_path.open('x') as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=False, separators=(',', ':'))+'\n')
    code_paths = (Path(__file__), ROOT/'src/driver_motion_spatial.py', ROOT/'src/driver_motion_handoff.py',
                  ROOT/'src/cone_motion_range.py', ROOT/'src/angular_fisheye_geometry.py',
                  ROOT/'src/webrtc_stream.py', ROOT/'src/webrtc_receive_ui.py', ROOT/'src/collision_risk.py')
    result = dict(schema='offline_motion_spatial_input_audit_v1', state='pass',
        session=audit['session'], counts=dict(counts), points=points,
        max_vector_length_difference_from_source_m=max_difference,
        max_abs_floor_plane_residual_m=max_plane_residual, numerical_tolerance_m=1e-12,
        numerical_agreement_is_not_physical_accuracy=True,
        supplied_file_count=len(supplied), inspected_structured_fields=inventory,
        queried_motion_or_transform_keys=sorted(MOTION_KEYS), matching_field_paths=hits,
        submitted_timestamped_measured_motion_available=False,
        vehicle_transform_available=False, vehicle_width_supplied=False,
        next_join_missing=['current_mount_vehicle_from_optical_rotation_and_translation_with_evidence',
            'measured_motion_with_validity_original_sample_time_and_clock_mapping',
            'vehicle_width_and_obstacle_support_point_semantics'],
        physical_metric_verified=False, floor_contact_verified=False,
        real_gradient_evaluated=False, temporal_target_association_verified=False,
        published_to_ros=False, usable_for_ffb=False, g923_or_vehicle_started=False,
        source_audits={str(p.relative_to(ROOT)): sha(p) for p in (audit_path, handoff_path)},
        source_files_sha256=supplied, profile_sha256=profile_sha,
        camera_sha256=sha(camera_path), config_sha256=sha(config_path),
        input_handoff_samples_sha256=sha(samples_path),
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in code_paths},
        derived_samples=dict(path=str(raw_path.relative_to(ROOT)), sha256=sha(raw_path)))
    output.mkdir(parents=True)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    with (output/'point_vectors.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=points[0]); writer.writeheader(); writer.writerows(points)
    print(json.dumps(dict(state='pass', counts=dict(counts), points=points,
                         max_vector_length_difference_m=max_difference,
                         max_plane_residual_m=max_plane_residual), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('audit', 'handoff-audit', 'intake-dir', 'raw-output-dir', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    run(parser.parse_args())
