"""Synthetic motion transport plus missing-motion replay of the saved range run."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_handoff import FALSE_FLAGS, SCHEMA as RANGE_SCHEMA
from driver_motion_time_join import MotionLog, OfflineMotionJoiner, motion_record, read_motion_records

SESSION, CLOCK, SOURCE = 'a'*32, 'synthetic/receiver', 'synthetic/source'
PNG, ANCHOR = 'b'*64, 1_800_000_000_000_000_000
POLICY = dict(max_skew_sec=.05, max_motion_age_sec=.1, max_clock_error_sec=.005)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def synthetic_range(**changes):
    value = dict(schema=RANGE_SCHEMA, session=SESSION, frame=20, source_time_sec=10.02,
        review_completed_time_sec=10.03, evaluated_time_sec=10.03,
        clock_basis='recorded_receiver_monotonic_NOT_ROS_or_wall_time', max_age_sec=.5,
        metric='horizontal_camera_foot_range_m_NOT_base_link_or_contact', input_verified=True,
        range_available=True, distance_m=1.2, reason='synthetic_only', primary_model='ippe_0',
        reference_generation=1, reference_frame=5, reference_png_sha256=PNG,
        vehicle_xy_m=None, object_id=None, replay_only=True, **{k: False for k in FALSE_FLAGS})
    value.update(changes)
    return value


def synthetic_binding(**changes):
    value = dict(schema='offline_motion_clock_binding_v1', session=SESSION,
        receiver_clock_id=CLOCK, source_clock_id=SOURCE, source_anchor_ns=ANCHOR,
        receiver_anchor_sec=10., valid_from_ns=ANCHOR-1_000_000_000,
        valid_to_ns=ANCHOR+1_000_000_000, error_bound_sec=.001,
        evidence_kind='synthetic_fixture_only', evidence_id='synthetic/clock-fixture')
    value.update(changes)
    return value


def synthetic_cases(output):
    # Independent scenarios, NOT one continuous or physically measured stream.
    cases = [
        ('forward', {}, {}, {}, True, 'offline_receiver_time_pair_only'),
        ('reverse', dict(linear_mps=-.2, angular_radps=.1), {}, {}, True, 'offline_receiver_time_pair_only'),
        ('measured_stop', dict(linear_mps=0., angular_radps=0.), {}, {}, True, 'offline_receiver_time_pair_only'),
        ('not_received', dict(received_at_sec=None), {}, {}, False, 'motion_not_received'),
        ('command', dict(source_kind='command'), {}, {}, False, 'motion_not_measured_odometry'),
        ('legacy_values', dict(source_kind='legacy_telemetry'), {}, {}, False, 'motion_not_measured_odometry'),
        ('measurement_invalid', dict(measurement_valid=False), {}, {}, False, 'motion_measurement_invalid_or_missing'),
        ('unknown_velocity', dict(linear_mps=None), {}, {}, False, 'motion_measurement_invalid_or_missing'),
        ('missing_original_stamp', dict(source_stamp_ns=None), {}, {}, False, 'motion_clock_mapping_missing'),
        ('missing_clock_binding', {}, dict(clock_binding=None), {}, False, 'motion_clock_mapping_missing'),
        ('wrong_clock', dict(source_clock_id='synthetic/other'), {}, {}, False, 'motion_source_clock_mismatch'),
        ('wrong_frame', dict(motion_frame_id='map'), {}, {}, False, 'motion_frame_mismatch'),
        ('outside_binding', dict(source_stamp_ns=ANCHOR-2_000_000_000), {}, {}, False, 'motion_clock_binding_out_of_scope'),
        ('old_original_measurement', dict(source_stamp_ns=ANCHOR-200_000_000), {}, {}, False, 'motion_measurement_stale'),
        ('future_to_receive', {}, dict(clock_binding=synthetic_binding(error_bound_sec=.006),
            max_clock_error_sec=.006), {}, False, 'motion_measurement_interval_after_reception'),
        ('future_to_video', dict(source_stamp_ns=ANCHOR+4_000_000, received_at_sec=10.006), {},
            dict(source_time_sec=10.002, review_completed_time_sec=10.012), False, 'motion_not_entirely_past_video_receive'),
        ('worst_case_skew', {}, dict(max_skew_sec=.02), {}, False, 'motion_video_receive_skew_too_large'),
        ('clock_error', {}, dict(clock_binding=synthetic_binding(error_bound_sec=.006)), {}, False, 'motion_clock_error_too_large'),
        ('range_veto', {}, {}, dict(range_available=False, distance_m=None, reason='possible_self_body_occlusion'),
            False, 'range_withheld'),
        ('foreign_motion_session', dict(session='c'*32), {}, {}, False, 'motion_session_or_clock_mismatch'),
    ]
    log_path = output/'synthetic_motion_records.jsonl'
    records = []
    with MotionLog(log_path, session=SESSION, receiver_clock_id=CLOCK, max_records=100, max_bytes=128*1024) as log:
        for index, (name, changes, _, _, _, _) in enumerate(cases, 1):
            facts = dict(session=SESSION, receiver_clock_id=CLOCK, sequence=index, logged_at_sec=10.01,
                received_at_sec=10.005, source_kind='measured_odometry', motion_frame_id='base_link',
                source_clock_id=SOURCE, source_stamp_ns=ANCHOR, measurement_valid=True,
                linear_mps=.2, angular_radps=-.1)
            facts.update(changes)
            record = motion_record(**facts)
            records.append(record)
            # Foreign scope must be refused by a bound log too; retain it in
            # case input JSON, not smuggled into this bound synthetic log.
            if record['session'] == SESSION:
                log.write(record)
    roundtrip = list(read_motion_records(log_path))
    require(roundtrip == [r for r in records if r['session'] == SESSION], 'motion log roundtrip changed original facts')
    results = []
    with (output/'synthetic_cases.jsonl').open('x') as stream:
        for case, record in zip(cases, records):
            name, _, options, range_changes, expected, expected_reason = case
            options = dict(POLICY, **options)
            clock = options.pop('clock_binding', synthetic_binding())
            engine = OfflineMotionJoiner(session=SESSION, receiver_clock_id=CLOCK, motion_frame_id='base_link',
                range_reference=dict(reference_frame=5, reference_png_sha256=PNG), clock_binding=clock, **options)
            restored = json.loads(json.dumps(record, allow_nan=False))
            engine.push_motion(restored, now_sec=10.01)
            packet = synthetic_range(**range_changes)
            value = engine.join(packet, now_sec=10.03)
            require(value['pair_available'] == expected and value['reason'] == expected_reason, 'failed synthetic case: '+name)
            if expected:
                require(value['measured_motion']['linear_mps'] == record['linear_mps']
                        and value['measured_motion']['angular_radps'] == record['angular_radps'], 'signed motion changed')
            else:
                require(value['measured_motion'] is None, 'unavailable case retained a motion value')
            stream.write(json.dumps(dict(case=name, motion_record=record, clock_binding=clock,
                policy=options, range_packet=packet, evaluation_time_sec=10.03, result=value), allow_nan=False)+'\n')
            results.append(dict(case=name, expected_pair=expected, pair_available=value['pair_available'],
                reason=value['reason'], passed=True))
    with (output/'synthetic_cases.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=results[0]); writer.writeheader(); writer.writerows(results)
    return results, log_path


def run(args):
    source_audit_path, intake = args.handoff_audit.resolve(), args.intake_dir.resolve()
    output, raw_output = args.output_dir.resolve(), args.raw_output_dir.resolve()
    require(not output.exists() and not raw_output.exists(), 'unused output directories required')
    require(ROOT/'recordings' in raw_output.parents and ROOT/'Experimental_results' in output.parents,
            'scoped raw/results directories required')
    source = json.loads(source_audit_path.read_bytes())
    require(source['schema'] == 'offline_motion_range_handoff_audit_v1' and source['state'] == 'pass',
            'formal handoff r02 audit required')
    for name, digest in source['input_and_code_sha256'].items():
        require(sha(ROOT/name) == digest, 'handoff evidence changed: '+name)
    sample_path = ROOT/source['samples']['path']
    require(sha(sample_path) == source['samples']['sha256'], 'handoff samples SHA mismatch')
    prior = ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json'
    closed = json.loads(prior.read_bytes())
    for name, digest in closed['source_code_sha256'].items():
        require(sha(ROOT/'src'/name) == digest, 'live source changed: '+name)
    reference_path = intake/'comparison/reference.json'
    require(sha(reference_path) == closed['supplied_files_sha256']['comparison/reference.json'], 'reference SHA mismatch')
    reference = json.loads(reference_path.read_bytes())
    # This logical label asserts no physical boot-clock evidence. There are no
    # motion records or clock mapping in this real-input test.
    engine = OfflineMotionJoiner(session=source['session'], receiver_clock_id='audit/logical-receiver-scope',
        motion_frame_id='base_link', range_reference=dict(reference_frame=reference['source_frame'],
        reference_png_sha256=reference['source_png_sha256']), clock_binding=None, **POLICY)
    counts, reasons = Counter(), Counter()
    output.mkdir(parents=True); raw_output.mkdir(parents=True)
    synthetic, synthetic_log = synthetic_cases(output)
    target = raw_output/'missing_motion_pairs.jsonl'
    points = {p['frame']: p for p in source['matched_screenshot_points']}
    matched = []
    with sample_path.open('rb') as stream, target.open('x') as sink:
        while True:
            line = stream.readline(16*1024+1)
            if not line:
                break
            require(len(line) <= 16*1024 and line.endswith(b'\n'), 'complete bounded range sample required')
            packet = json.loads(line)
            value = engine.join(packet, now_sec=packet['evaluated_time_sec'])
            wire = json.dumps(value, allow_nan=False, separators=(',', ':'))
            require(json.loads(wire) == value, 'pair output JSON changed values')
            require(value['pair_available'] is False and value['measured_motion'] is None
                    and value['range_sample']['range_available'] == packet['range_available']
                    and value['range_sample']['distance_m'] == packet['distance_m'], 'real missing motion invented or distance changed')
            sink.write(wire+'\n')
            counts['samples'] += 1
            counts['range_numeric'] += value['range_sample']['range_available']
            counts['range_withheld'] += not value['range_sample']['range_available']
            counts['paired'] += value['pair_available']
            reasons[value['reason']] += 1
            if packet['frame'] in points:
                matched.append(dict(frame=packet['frame'], distance_m=value['range_sample']['distance_m'],
                    before_m=points[packet['frame']]['after_m'], measured_motion=None, pair_available=False))
    require(counts['samples'] == source['counts']['samples']
            and counts['range_numeric'] == source['counts']['numeric']
            and all(p['distance_m'] == p['before_m'] for p in matched) and len(matched) == 3,
            'real range count or screenshot preservation mismatch')
    paths = (Path(__file__), ROOT/'src/driver_motion_time_join.py', ROOT/'src/driver_motion_handoff.py',
             ROOT/'src/webrtc_stream.py', ROOT/'src/webrtc_receive_ui.py')
    result = dict(schema='offline_motion_time_join_audit_v1', state='pass', work_date='2026-11-16',
        real_input=dict(session=source['session'], counts=dict(counts), reasons=dict(reasons),
            motion_records_supplied=0, clock_binding_supplied=False, matched_screenshot_points=matched),
        synthetic=dict(cases=len(synthetic), passed=sum(r['passed'] for r in synthetic),
            available_pairs=sum(r['pair_available'] for r in synthetic), motion_log_records=19,
            scenarios_are_independent=True, clock_evidence_kind='synthetic_fixture_only'),
        policy=POLICY, policy_is_test_only_NOT_adopted_FFB_timing=True,
        source_audit=dict(path=str(source_audit_path.relative_to(ROOT)), sha256=sha(source_audit_path)),
        source_samples_sha256=sha(sample_path), reference_sha256=sha(reference_path),
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in paths},
        artifacts_sha256={str(p.relative_to(ROOT)): sha(p) for p in
            (synthetic_log, output/'synthetic_cases.jsonl', output/'synthetic_cases.csv', target)},
        live_sources_unchanged=True, exposure_time_alignment_verified=False,
        real_motion_time_alignment_verified=False, clock_alignment_independently_verified=False,
        vehicle_xy_generated=False, gradient_computed=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False, G923_or_vehicle_started=False)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(dict(state='pass', real_input=result['real_input'], synthetic=result['synthetic']), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('handoff-audit', 'intake-dir', 'raw-output-dir', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    run(parser.parse_args())
