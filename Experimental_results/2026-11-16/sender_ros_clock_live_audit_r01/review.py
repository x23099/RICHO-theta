"""Strict offline v3 clock/odometry submission audit. No live output."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_sender_clock_observation import SCHEMA as CLOCK_SCHEMA, checked_clock_observation

spec = importlib.util.spec_from_file_location('clock_live_v2_validator', ROOT/
    'Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/review.py')
v2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v2)
base = v2.base
PREFIX = 'received_sender_clock_r01/'


def checked_archive(path):
    result, names = {}, set()
    with tarfile.open(path, 'r:xz') as archive:
        members = archive.getmembers()
        base.require(len(members) == 4, 'exact directory plus three files required')
        for m in members:
            base.require(m.name not in names, 'duplicate archive member')
            names.add(m.name)
            if m.isdir():
                base.require(m.name.rstrip('/') == PREFIX.rstrip('/'), 'unexpected directory')
                continue
            base.require(m.isfile() and m.name in {PREFIX+n for n in base.FILES}, 'unexpected member/link/path')
            limit = 64*1024*1024 if m.name.endswith('.jsonl') else 64*1024
            base.require(0 < m.size <= limit, 'bounded nonempty member required')
            with archive.extractfile(m) as stream:
                payload = stream.read(limit+1)
            base.require(len(payload) == m.size, 'archive member length mismatch')
            result[m.name[len(PREFIX):]] = payload
    base.require(set(result) == set(base.FILES), 'three expected files required')
    return result


def analyze(files, expected_source_sha256):
    metadata, summary = (base.strict_json(files[n]) for n in base.FILES[1:])
    base.require(metadata['supported_sender_clock_schema'] == CLOCK_SCHEMA
        and metadata['record_schemas'] == ['driver_received_telemetry_v1',
            'driver_received_telemetry_v2', 'driver_received_telemetry_v3'], 'clock schema declaration required')
    base.require(len(files[base.FILES[0]]) == summary['log_bytes'], 'original byte count mismatch')
    projected, clocks, odom = [], [], []
    for line in files[base.FILES[0]].splitlines(keepends=True):
        base.require(line.endswith(b'\n') and len(line) <= 16384, 'complete bounded JSONL line required')
        row = base.strict_json(line)
        if row['event_kind'] == 'telemetry':
            base.require(row['schema'] == 'driver_received_telemetry_v3'
                and row['sender_clock_metadata_state'] == 'versioned_sender_clock_observation',
                'valid v3 sender clock observation required')
            clock = checked_clock_observation(row['sender_clock_observation'])
            observation = v2.checked_observation(row['odometry_observation'])
            base.require(clock['sender_id'] == observation['sender_id']
                and clock['sender_monotonic_clock_id'] == observation['sender_monotonic_clock_id'],
                'sender clock and odometry identity mismatch')
            if clock['status'] == 'sampled' and observation['snapshot_mono_sec'] is not None:
                base.require(observation['snapshot_mono_sec'] <= clock['mono_before_ns']/1e9+1e-9,
                    'sender clock read precedes same-message odometry snapshot')
            clocks.append(clock); odom.append(observation)
            row = dict(row); del row['sender_clock_metadata_state'], row['sender_clock_observation']
            row['schema'] = 'driver_received_telemetry_v2'
        projected.append(row)
    # Reuse v2 and legacy validators on copies only. Validate original bytes above.
    wire = b''.join(json.dumps(r, allow_nan=False).encode()+b'\n' for r in projected)
    projected_files = {base.FILES[0]:wire,
        base.FILES[1]:json.dumps(dict(metadata, record_schemas=[
            'driver_received_telemetry_v1', 'driver_received_telemetry_v2'])).encode(),
        base.FILES[2]:json.dumps(dict(summary, log_bytes=len(wire))).encode()}
    common = v2.analyze(projected_files, expected_source_sha256)
    groups = {}
    for clock in clocks:
        if clock['status'] == 'sampled':
            groups.setdefault(clock['sender_id'], []).append(clock)
    for group in groups.values():
        for a, b in zip(group, group[1:]):
            base.require(a['sample_sequence'] < b['sample_sequence']
                and a['clock_generation'] <= b['clock_generation']
                and a['mono_after_ns'] <= b['mono_before_ns'], 'clock sample sequence/generation/time reversed')
            if a['clock_generation'] == b['clock_generation']:
                base.require(a['ros_now_ns'] <= b['ros_now_ns'], 'ROS reversal without generation change')
    sampled = [c for c in clocks if c['status'] == 'sampled']
    stats = lambda values:base.stats(values) if values else None
    result = dict(schema='sender_ros_clock_live_audit_v1', state='recording_verified',
        compatibility_projection_for_common_envelope_only=True,
        original_metadata=metadata, original_summary=summary,
        telemetry_records=len(clocks), recorded_events=common['recorded_events'],
        event_counts=common['event_counts'], sessions=common['sessions'],
        telemetry_observation_span_sec=common['telemetry_observation_span_sec'],
        average_telemetry_hz=common['average_telemetry_hz'],
        receive_interval_ms=common['receive_interval_ms'],
        receive_to_writer_timestamp_ms=common['receive_to_writer_timestamp_ms'],
        recorded_sequence_bounds=common['recorded_sequence_bounds'],
        internal_sequence_gaps=common['internal_sequence_gaps'],
        trailing_unrecorded_offer_count=common['trailing_unrecorded_offer_count'],
        rejection_cause_established=False, writer_timestamp_is_not_disk_completion_or_network_latency=True,
        clock_status_counts=dict(Counter(c['status'] for c in clocks)),
        ros_time_status_counts=dict(Counter(c['ros_time_status'] for c in clocks)),
        clock_generation_counts=dict(Counter(str(c['clock_generation']) for c in clocks)),
        configuration_change_observations=sum(c['configuration_changed'] is True for c in clocks),
        clock_configurations=sorted({str((c['clock_type'], c['use_sim_time'], c['ros_time_active'])) for c in sampled}),
        sender_ids=sorted({c['sender_id'] for c in clocks}),
        sender_clock_ids=sorted({c['sender_monotonic_clock_id'] for c in clocks}),
        sampled_clock_records=len(sampled), sender_scope_matches=len(clocks),
        sampled_clock_after_odom_snapshot_order_checked=True,
        clock_sample_sequence_bounds=[min(c['sample_sequence'] for c in sampled),
                                     max(c['sample_sequence'] for c in sampled)] if sampled else None,
        bracket_width_us=stats([c['bracket_width_ns']/1000 for c in sampled]),
        odometry_callback_received_counts=common['callback_received_counts'],
        odometry_stamp_status_counts=common['stamp_status_counts'],
        sampled_header_stamp_steps=common['sampled_header_stamp_steps'],
        motion_frame_pairs=common['observed_frame_pairs'],
        observed_linear_mps=common['observed_linear_mps'], observed_angular_radps=common['observed_angular_radps'],
        sender_callback_age_sec=common['sender_callback_age_sec'],
        ROS_now_minus_header_numeric_difference_ms_NOT_proven_transport_delay=stats([
            (c['ros_now_ns']-o['header_stamp_ns'])/1e6 for c, o in zip(clocks, odom)
            if c['status'] == 'sampled' and o['header_stamp_ns'] is not None]),
        conditional_constant_offset_intersections_by_sender={},
        driver_header_clock_independently_matched=False, receiver_clock_binding_verified=False,
        source_freshness_verified=False, exposure_alignment_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    for sender, group in groups.items():
        for generation in sorted({c['clock_generation'] for c in group}):
            same = [c for c in group if c['clock_generation'] == generation]
            low = max(c['ros_minus_mono_lower_ns'] for c in same)
            high = min(c['ros_minus_mono_upper_ns'] for c in same)
            result['conditional_constant_offset_intersections_by_sender'][sender+'/'+str(generation)] = dict(
                lower_ns=low, upper_ns=high, nonempty=low <= high,
                constant_relative_rate_assumed_NOT_verified=True, adopted_binding=False)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'raw-output-dir', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    raw, output = args.raw_output_dir.resolve(), args.output_dir.resolve()
    base.require(not raw.exists() and not output.exists() and ROOT/'recordings' in raw.parents
        and ROOT/'Experimental_results' in output.parents, 'unused scoped output paths required')
    files = checked_archive(args.archive)
    names = ('driver_telemetry_recording.py', 'webrtc_receive_ui.py',
             'driver_odometry_observation.py', 'driver_sender_clock_observation.py')
    result = analyze(files, {n:base.sha((ROOT/'src'/n).read_bytes()) for n in names})
    result.update(archive_sha256=base.sha(args.archive.read_bytes()),
        supplied_files_sha256={n:base.sha(b) for n, b in files.items()},
        review_code_sha256=base.sha(Path(__file__).read_bytes()), raw_intake=str(raw.relative_to(ROOT)),
        validation_dependency_sha256={str(p.relative_to(ROOT)):base.sha(p.read_bytes()) for p in (
            ROOT/'Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/review.py',
            ROOT/'Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/review.py',
            ROOT/'src/driver_sender_clock_observation.py', ROOT/'src/driver_odometry_observation.py')})
    raw.mkdir(parents=True); output.mkdir(parents=True)
    for name, payload in files.items():
        with (raw/name).open('xb') as stream:
            stream.write(payload)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps({k:result[k] for k in ('state', 'telemetry_records', 'clock_status_counts',
        'clock_configurations', 'bracket_width_us', 'receiver_clock_binding_verified')}, indent=2))
