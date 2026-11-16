"""Bounded offline evidence analysis, not clock fitting or live calibration."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagnostics import one_way_examples, four_stamp_interval, conditional_body_geometry

spec = importlib.util.spec_from_file_location('spacetime_base_review', ROOT/
    'Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/review.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load(relative):
    return base.strict_json((ROOT/relative).read_bytes())


def run(output):
    output = output.resolve()
    base.require(ROOT/'Experimental_results' in output.parents and not output.exists(),
                 'unused scoped report output required')
    received_path = 'Experimental_results/2026-11-16/odometry_metadata_received_audit_r01/results_r01/audit.json'
    received = load(received_path)
    base.require(received['state'] == 'recording_verified', 'verified received observation audit required')
    raw = (ROOT/received['raw_intake']).resolve()
    base.require(ROOT/'recordings' in raw.parents, 'scoped raw input required')
    for name in base.FILES:
        base.require(sha(raw/name) == received['supplied_files_sha256'][name], 'raw SHA mismatch')
    base.require((raw/'received_telemetry.jsonl').stat().st_size <= 64*1024*1024, 'bounded raw log required')
    observations, receiver = [], []
    with (raw/'received_telemetry.jsonl').open('rb') as stream:
        while True:
            line = stream.readline(16385)
            if not line:
                break
            base.require(line.endswith(b'\n') and len(line) <= 16384, 'complete bounded raw line required')
            row = base.strict_json(line)
            if row['event_kind'] == 'telemetry':
                observations.append(row['odometry_observation']); receiver.append(row['received_at_sec'])
                base.require(len(observations) <= 100000, 'bounded telemetry count required')
    base.require(len(observations) == received['telemetry_records'] and len(observations) > 1
                 and all(o['callback_received'] is True for o in observations), 'received observation scope required')
    sender = [o['snapshot_mono_sec'] for o in observations]
    callbacks = [o['callback_received_mono_sec'] for o in observations]
    stamps = [o['header_stamp_ns'] for o in observations]
    # Subtract integer epoch stamps before converting differences to seconds.
    source_elapsed = [(t-stamps[0])/1e9 for t in stamps]
    callback_elapsed = [t-callbacks[0] for t in callbacks]
    sender_elapsed = [t-sender[0] for t in sender]
    receiver_elapsed = [t-receiver[0] for t in receiver]
    clock = dict(samples=len(observations),
        source_elapsed_sec=source_elapsed[-1], sender_callback_elapsed_sec=callback_elapsed[-1],
        sender_snapshot_elapsed_sec=sender_elapsed[-1], receiver_elapsed_sec=receiver_elapsed[-1],
        source_minus_callback_elapsed_difference_ms=base.stats(
            [1000*(a-b) for a, b in zip(source_elapsed, callback_elapsed)]),
        receiver_minus_sender_elapsed_difference_ms=base.stats(
            [1000*(a-b) for a, b in zip(receiver_elapsed, sender_elapsed)]),
        one_way_nonidentifiability=one_way_examples(sender, receiver, alternative_shift_sec=.1),
        example_shift_sec_is_not_adopted_latency_bound=True,
        offset_or_drift_fitted=False, ROS_clock_type_identified=False,
        source_to_receiver_binding_generated=False, exposure_alignment_verified=False)
    spatial_path = 'Experimental_results/2026-11-16/motion_spatial_inputs_r01/results_r01/audit.json'
    spatial = load(spatial_path)
    base.require(spatial['state'] == 'pass' and sha(ROOT/spatial['derived_samples']['path'])
                 == spatial['derived_samples']['sha256'], 'conditional spatial evidence SHA mismatch')
    old_paths = [
        'Experimental_results/2026-10-19/fisheye_tf_preparation_r01/results_r01/diagnostic_transforms.json',
        'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json',
        'Experimental_results/2026-11-09/wide_floor_geometry_r01/same_frame_pose_r01/summary.json']
    old = [load(p) for p in old_paths]
    base.require(all(v['measured_extrinsics'] is False and v['base_link_transform'] is False
                     for v in old[0].values())
                 and old[1]['physical_transform_independently_measured'] is False
                 and old[2]['selected_solution'] is None, 'historical evidence status changed')
    R = [[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]]
    yawR = [[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]]
    synthetic = dict(synthetic_only=True,
        asymmetric_exchange=four_stamp_interval(100., 10.02, 10.025, 100.055),
        translated_mount=conditional_body_geometry([.3, 0., 1.], [0., -1., 0.], .59, R, [.2, .1, .59]),
        same_normal_forward=conditional_body_geometry([0., 0., 1.], [0., -1., 0.], .59, R, [0., 0., .59]),
        same_normal_left=conditional_body_geometry([0., 0., 1.], [0., -1., 0.], .59, yawR, [0., 0., .59]))
    evidence = [received_path, spatial_path, *old_paths]
    code = [Path(__file__).resolve(), Path(__file__).with_name('diagnostics.py').resolve(),
            ROOT/'tests/test_spacetime_evidence.py']
    result = dict(schema='offline_spacetime_evidence_audit_v1', state='analysis_complete_NOT_real_alignment',
        clock_observations=clock, synthetic_examples=synthetic,
        prior_spatial_counts_reused_after_SHA_check=spatial['counts'],
        prior_spatial_session=spatial['session'], motion_session=received['sessions'][0],
        actual_body_transform=None, actual_clock_binding=None, real_vehicle_points_generated=0,
        real_range_motion_pairs_generated=0,
        historical_transform_rejections=[
            dict(path=old_paths[0], reason='diagnostic_only_no_measured_extrinsics_or_base_transform'),
            dict(path=old_paths[1], reason='conditional_paper_frame_NOT_independently_measured_body_transform'),
            dict(path=old_paths[2], reason='different_session_handedness_withheld_no_selected_solution')],
        evidence_sha256={p:sha(ROOT/p) for p in evidence},
        source_raw_sha256=received['supplied_files_sha256'],
        conditional_spatial_raw_sha256=spatial['derived_samples'],
        code_sha256={str(p.relative_to(ROOT)):sha(p) for p in code},
        required_before_real_pairing=['explicit_ROS_clock_origin_and_validity',
            'ROS_to_sender_monotonic_bracket_with_error_bound',
            'sender_to_receiver_clock_exchange_or_external_binding_with_drift_bound',
            'same_session_range_and_motion_recording_scope',
            'current_body_from_optical_transform_and_vehicle_origin',
            'vehicle_width_and_obstacle_point_semantics'],
        runtime_changed=False, robot_or_ROS_or_camera_or_G923_started=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(dict(state=result['state'], clock_observations=clock,
                         actual_body_transform=None, actual_clock_binding=None), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args().output_dir)
