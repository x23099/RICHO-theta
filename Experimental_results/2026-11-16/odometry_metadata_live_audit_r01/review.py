"""Offline v2 submission review. No ROS, network, actuation or runtime changes."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_odometry_observation import SCHEMA, checked_observation

spec = importlib.util.spec_from_file_location('legacy_transport_review', ROOT/
    'Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/review.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def checked_archive(path, prefix='received_telemetry_odom_r02/'):
    base.require(isinstance(prefix, str) and re.fullmatch(r'received_telemetry_odom_r[0-9]{2,4}/', prefix),
                 'explicit bounded recording directory required')
    result, names = {}, set()
    with tarfile.open(path, 'r:xz') as archive:
        members = archive.getmembers()
        base.require(len(members) == 4, 'exact directory plus three files required')
        for m in members:
            base.require(m.name not in names, 'duplicate member')
            names.add(m.name)
            if m.isdir():
                base.require(m.name.rstrip('/') == prefix.rstrip('/'), 'unexpected directory')
                continue
            base.require(m.isfile() and m.name in {prefix+n for n in base.FILES}, 'unexpected member/link/path')
            limit = 64*1024*1024 if m.name.endswith('.jsonl') else 64*1024
            base.require(0 < m.size <= limit, 'bounded nonempty member required')
            with archive.extractfile(m) as stream:
                payload = stream.read(limit+1)
            base.require(len(payload) == m.size, 'member length mismatch')
            result[m.name[len(prefix):]] = payload
    base.require(set(result) == set(base.FILES), 'three files required')
    return result


def analyze(files, expected_source_sha256):
    md, summary = (base.strict_json(files[n]) for n in base.FILES[1:])
    base.require(md['source_sha256'] == expected_source_sha256, 'runtime source SHA mismatch')
    base.require(md['versioned_source_motion_metadata_supported'] is True
        and md['supported_odometry_schema'] == SCHEMA
        and md['record_schemas'] == ['driver_received_telemetry_v1', 'driver_received_telemetry_v2'],
        'versioned metadata declaration required')
    lines = files[base.FILES[0]].splitlines(keepends=True)
    base.require(len(files[base.FILES[0]]) == summary['log_bytes'], 'original byte count mismatch')
    projected, observations, telemetry = [], [], []
    for line in lines:
        base.require(line.endswith(b'\n') and len(line) <= 16384, 'complete bounded line required')
        row = base.strict_json(line)
        if row['event_kind'] == 'telemetry':
            base.require(row['schema'] == 'driver_received_telemetry_v2'
                and row.get('odometry_metadata_state') == 'versioned_odometry_observation',
                'valid v2 observation required for this review')
            observations.append(checked_observation(row['odometry_observation']))
            telemetry.append(row)
            # Validate unchanged common envelope using the historical v1 validator.
            # These copies are only for validation; original raw bytes remain untouched.
            row = dict(row)
            del row['odometry_metadata_state'], row['odometry_observation']
            row['schema'] = 'driver_received_telemetry_v1'
        projected.append(row)
    projected_md = dict(md, versioned_source_motion_metadata_supported=False)
    wire = b''.join(json.dumps(r, allow_nan=False).encode()+b'\n' for r in projected)
    projected_files = {base.FILES[0]: wire, base.FILES[1]: json.dumps(projected_md).encode(),
        base.FILES[2]: json.dumps(dict(summary, log_bytes=len(wire))).encode()}
    transport = base.analyze(projected_files, expected_source_sha256=expected_source_sha256)
    sender_groups = {}
    for o in observations:
        group = sender_groups.setdefault(o['sender_id'], [])
        group.append(o)
    for group in sender_groups.values():
        times = [o['snapshot_mono_sec'] for o in group if o['snapshot_mono_sec'] is not None]
        base.require(all(a <= b for a, b in zip(times, times[1:])), 'sender snapshot time reversed')
    sequences = [o['callback_sequence'] for o in observations if o['callback_sequence'] is not None]
    stamp_steps, sequence_steps = Counter(), Counter()
    for group in sender_groups.values():
        received = [o for o in group if o['callback_received'] is True]
        for a, b in zip(received, received[1:]):
            delta = b['callback_sequence']-a['callback_sequence']
            sequence_steps['advanced' if delta > 0 else 'repeated' if delta == 0 else 'reversed'] += 1
            if a['header_stamp_ns'] is not None and b['header_stamp_ns'] is not None:
                delta = b['header_stamp_ns']-a['header_stamp_ns']
                stamp_steps['advanced' if delta > 0 else 'repeated' if delta == 0 else 'reversed'] += 1
    def observation_stats(key):
        values = [o[key] for o in observations if o[key] is not None]
        return base.stats(values) if values else None
    result = dict(schema='odometry_metadata_live_audit_v1', state='recording_verified',
        compatibility_projection_for_common_envelope_validation_only=True,
        original_summary=summary, original_metadata=md,
        telemetry_records=len(telemetry), event_counts=transport['event_counts'],
        recorded_events=transport['recorded_events'], sessions=transport['sessions'],
        telemetry_observation_span_sec=transport['telemetry_observation_span_sec'],
        average_telemetry_hz=transport['average_telemetry_hz'],
        receive_interval_ms=transport['receive_interval_ms'],
        receive_to_writer_timestamp_ms=transport['receive_to_writer_timestamp_ms'],
        writer_timestamp_is_not_disk_completion_or_network_latency=True,
        numeric_fields=transport['numeric_fields'],
        internal_sequence_gaps=transport['internal_sequence_gaps'],
        recorded_sequence_bounds=transport['recorded_sequence_bounds'],
        trailing_unrecorded_offer_count=transport['trailing_unrecorded_offer_count'],
        rejection_cause_established=False,
        callback_received_counts=dict(Counter(str(o['callback_received']) for o in observations)),
        stamp_status_counts=dict(Counter(o['stamp_status'] for o in observations)),
        sample_fields_valid_counts=dict(Counter(str(o['sample_fields_valid']) for o in observations)),
        observed_sender_ids=sorted(sender_groups),
        observed_frame_pairs=sorted({str((o['motion_frame_id'], o['pose_frame_id'])) for o in observations}),
        callback_sequence_bounds=[min(sequences), max(sequences)] if sequences else None,
        observed_callback_records=sum(o['callback_received'] is True for o in observations),
        positive_header_stamp_records=sum(o['header_stamp_ns'] is not None for o in observations),
        observation_dropped_callbacks_max=max(o['dropped_callbacks'] for o in observations),
        sampled_callback_sequence_steps=dict(sequence_steps), sampled_header_stamp_steps=dict(stamp_steps),
        unique_sampled_callback_sequences=len({(o['sender_id'], o['callback_sequence']) for o in observations
            if o['callback_received'] is True}),
        unique_sampled_header_stamps=len({(o['sender_id'], o['header_stamp_ns']) for o in observations
            if o['header_stamp_ns'] is not None}),
        sender_callback_age_sec=observation_stats('callback_age_sec'),
        sender_stamp_progress_age_sec=observation_stats('stamp_progress_age_sec'),
        observed_linear_mps=observation_stats('linear_mps'),
        observed_angular_radps=observation_stats('angular_radps'),
        all_sender_callbacks_observed_in_telemetry=False,
        sender_runtime_source_SHA_verified=False,
        source_freshness_verified=False, distance_motion_pairing_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    if all(o['callback_received'] is False for o in observations):
        result['odometry_finding'] = 'no_callback_observed_by_sender_metadata_NOT_measured_stationary_zero'
    elif result['observed_callback_records']:
        result['odometry_finding'] = 'callback_observed_NOT_physical_or_clock_verification'
    else:
        result['odometry_finding'] = 'callback_state_unknown'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'raw-output-dir', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--archive-prefix', default='received_telemetry_odom_r02/')
    args = parser.parse_args()
    raw, output = args.raw_output_dir.resolve(), args.output_dir.resolve()
    base.require(not raw.exists() and not output.exists(), 'unused output paths required')
    base.require(ROOT/'recordings' in raw.parents and ROOT/'Experimental_results' in output.parents,
                 'scoped raw/report directories required')
    files = checked_archive(args.archive, args.archive_prefix)
    sources = {n:base.sha((ROOT/'src'/n).read_bytes()) for n in
        ('driver_telemetry_recording.py', 'webrtc_receive_ui.py', 'driver_odometry_observation.py')}
    result = analyze(files, sources)
    result.update(archive_sha256=base.sha(args.archive.read_bytes()),
        archive_prefix=args.archive_prefix,
        supplied_files_sha256={n:base.sha(b) for n, b in files.items()},
        review_code_sha256=base.sha(Path(__file__).read_bytes()), raw_intake=str(raw.relative_to(ROOT)))
    raw.mkdir(parents=True); output.mkdir(parents=True)
    for name, payload in files.items():
        with (raw/name).open('xb') as stream:
            stream.write(payload)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps({k:result[k] for k in ('state', 'telemetry_records', 'recorded_events',
        'callback_received_counts', 'stamp_status_counts', 'odometry_finding', 'archive_sha256')}, indent=2))
