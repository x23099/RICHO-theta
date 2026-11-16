"""Bounded, byte-preserving review of the submitted passive telemetry log."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_telemetry_recording import FALSE_FLAGS, LIFECYCLE, NUMBERS, finite

FILES = ('received_telemetry.jsonl', 'telemetry_recording_metadata.json', 'telemetry_recording_summary.json')
PREFIX = 'received_telemetry_r01/'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('nonfinite JSON value')
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid)


def checked_archive(path):
    result = {}
    with tarfile.open(path, 'r:xz') as archive:
        members = archive.getmembers()
        require(len(members) == 4, 'exact directory plus three members required')
        names = set()
        for member in members:
            require(member.name not in names, 'duplicate tar member')
            names.add(member.name)
            if member.isdir():
                require(member.name.rstrip('/') == PREFIX.rstrip('/'), 'unexpected archive directory')
                continue
            require(member.isfile() and member.name in {PREFIX+n for n in FILES},
                    'only exact expected regular files allowed; no links/path traversal')
            limit = 64*1024*1024 if member.name.endswith('.jsonl') else 64*1024
            require(0 < member.size <= limit, 'bounded nonempty member required')
            with archive.extractfile(member) as stream:
                payload = stream.read(limit+1)
            require(len(payload) == member.size and len(payload) <= limit, 'member length mismatch')
            result[member.name[len(PREFIX):]] = payload
    require(set(result) == set(FILES), 'three files required')
    return result


def checked_row(row, clock_id):
    fields = {'schema', 'session', 'sequence', 'receiver_clock_id', 'received_at_sec', 'logged_at_sec',
        'event_kind', 'source_kind', 'source_clock_id', 'source_stamp_ns', 'motion_frame_id',
        'measurement_valid', 'source_freshness_verified', 'invalid_fields', *NUMBERS.values(), *FALSE_FLAGS}
    require(isinstance(row, dict) and set(row) == fields and row['schema'] == 'driver_received_telemetry_v1',
            'exact received telemetry schema required')
    require(isinstance(row['session'], str) and re.fullmatch('[0-9a-f]{32}', row['session'])
            and type(row['sequence']) is int and row['sequence'] > 0
            and row['receiver_clock_id'] == clock_id, 'record session/sequence/clock mismatch')
    require(all(finite(row[k]) and row[k] >= 0 for k in ('received_at_sec', 'logged_at_sec'))
            and row['logged_at_sec'] >= row['received_at_sec'], 'causal finite receiver times required')
    require(row['event_kind'] in LIFECYCLE|{'telemetry'}
            and row['source_kind'] == ('legacy_telemetry' if row['event_kind']=='telemetry' else None)
            and all(row[k] is None for k in ('source_clock_id', 'source_stamp_ns', 'motion_frame_id', 'measurement_valid'))
            and row['source_freshness_verified'] is False
            and all(row[k] is v for k, v in FALSE_FLAGS.items()), 'legacy data acquired unsupported authority')
    invalid = row['invalid_fields']
    require(type(invalid) is list and all(type(k) is str and k in NUMBERS for k in invalid)
            and len(invalid) == len(set(invalid)), 'bounded invalid-field list required')
    for source, target in NUMBERS.items():
        value = row[target]
        require(value is None or finite(value), 'numeric field must be finite or null')
        require(source not in invalid or value is None, 'invalid field contains a numeric value')
    require(row['sender_wall_time_ms'] is None or row['sender_wall_time_ms'] >= 0, 'negative sender wall time')
    if row['event_kind'] != 'telemetry':
        require(not invalid and all(row[k] is None for k in NUMBERS.values()), 'lifecycle contains motion values')
    return row


def stats(values):
    ordered = sorted(values)
    require(bool(ordered), 'statistics need samples')
    position = .95*(len(ordered)-1)
    lo, hi = math.floor(position), math.ceil(position)
    return dict(count=len(ordered), minimum=min(ordered), median=statistics.median(ordered),
        mean=statistics.mean(ordered), p95=ordered[lo]+(ordered[hi]-ordered[lo])*(position-lo), maximum=max(ordered))


def analyze(files, *, expected_source_sha256):
    metadata, summary = (strict_json(files[n]) for n in FILES[1:])
    require(metadata['schema'] == 'driver_telemetry_recording_metadata_v1'
            and summary['schema'] == 'driver_telemetry_recording_summary_v1', 'metadata/summary schema mismatch')
    clock_id = metadata['receiver_clock_id']
    require(isinstance(clock_id, str) and re.fullmatch('receiver-process/[0-9a-f]{32}', clock_id)
            and summary['receiver_clock_id'] == clock_id, 'shared receiver process clock required')
    require(metadata['source_sha256'] == expected_source_sha256, 'submitted runtime code SHA mismatch')
    require(metadata['clock_basis'] == 'time.monotonic_in_receiver_process_shared_with_native_video_receive'
            and metadata['source_time_basis'] == 'unknown_NOT_sender_wall_timestamp'
            and metadata['versioned_source_motion_metadata_supported'] is False
            and metadata['values_are_received_not_verified_measurements'] is True
            and metadata['image_or_arbitrary_message_saved'] is False, 'unexpected clock/measurement declaration')
    for record in (metadata, summary):
        require(all(record[k] is v for k, v in FALSE_FLAGS.items()), 'noncontrolling attributes required')
    require(summary['state'] == 'closed' and summary['error'] is None
            and all(summary[k] is True for k in ('stop_requested', 'writer_done', 'shutdown_complete')),
            'normal closed writer required')
    count_keys = ('offered', 'queued', 'queue_drops', 'busy_drops', 'rejected', 'written', 'log_bytes',
                  'discarded_pending', 'pending', 'in_flight', 'max_records', 'max_bytes', 'queue_capacity')
    require(all(type(summary[k]) is int and summary[k] >= 0 for k in count_keys), 'nonnegative integer counters required')
    require(summary['offered'] == summary['queued']+summary['queue_drops']+summary['rejected']
            and summary['queued'] == summary['written']+summary['discarded_pending']
            and summary['pending'] == summary['in_flight'] == 0
            and summary['written'] <= summary['max_records'] and summary['log_bytes'] <= summary['max_bytes'],
            'closed recorder count/limit conservation failed')
    require(finite(summary['max_offer_ms']) and summary['max_offer_ms'] >= 0
            and all(summary[k] is False for k in ('source_time_or_validity_inferred',
                    'control_channel_modified', 'distance_computation_modified')), 'bad recording summary facts')
    lines = files[FILES[0]].splitlines(keepends=True)
    require(len(lines) == summary['written'] and len(files[FILES[0]]) == summary['log_bytes'], 'log length differs from summary')
    rows = []
    for line in lines:
        require(len(line) <= 16*1024 and line.endswith(b'\n'), 'complete bounded JSONL line required')
        rows.append(checked_row(strict_json(line), clock_id))
    require(len(rows) > 1, 'actual telemetry evidence required')
    for a, b in zip(rows, rows[1:]):
        require(a['sequence'] < b['sequence'] and a['received_at_sec'] <= b['received_at_sec']
                and a['logged_at_sec'] <= b['logged_at_sec'], 'record order reversed')
    telemetry = [r for r in rows if r['event_kind']=='telemetry']
    require(len(telemetry) > 1, 'multiple actual telemetry messages required')
    intervals = [b['received_at_sec']-a['received_at_sec'] for a, b in zip(telemetry, telemetry[1:])]
    require(sum(intervals) > 0, 'positive telemetry observation span required')
    gaps = [dict(before=a['sequence'], after=b['sequence']) for a, b in zip(rows, rows[1:])
            if b['sequence'] != a['sequence']+1]
    return dict(schema='receiver_telemetry_live_audit_v1', state='pass',
        required_files_complete=True, runtime_source_sha256_match=True, receiver_clock_id=clock_id,
        event_counts=dict(Counter(r['event_kind'] for r in rows)), recorded_events=len(rows),
        telemetry_records=len(telemetry), sessions=sorted({r['session'] for r in rows}),
        telemetry_observation_span_sec=sum(intervals), average_telemetry_hz=(len(telemetry)-1)/sum(intervals),
        receive_interval_ms=stats([1000*x for x in intervals]),
        receive_to_writer_timestamp_ms=stats([1000*(r['logged_at_sec']-r['received_at_sec']) for r in rows]),
        writer_timestamp_is_not_disk_completion_or_network_latency=True,
        recorder_max_offer_ms=summary['max_offer_ms'],
        numeric_fields={k:dict(present=sum(r[k] is not None for r in telemetry),
            nulls=sum(r[k] is None for r in telemetry),
            unique_values=sorted({r[k] for r in telemetry if r[k] is not None})) for k in NUMBERS.values()},
        invalid_field_counts=dict(Counter(k for r in rows for k in r['invalid_fields'])),
        recorded_sequence_bounds=[rows[0]['sequence'], rows[-1]['sequence']], internal_sequence_gaps=gaps,
        trailing_unrecorded_offer_count=summary['offered']-rows[-1]['sequence'],
        summary=summary, metadata=metadata,
        rejection_reason_recorded=False, rejection_cause_established=False,
        sender_sample_time_and_validity_known=False, zero_values_prove_valid_stationary_odometry=False,
        exposure_time_alignment_verified=False, distance_motion_pairing_verified=False,
        GPU_inference_coexecution_performance_verified=False, video_smoothness_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'raw-output-dir', 'output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    raw, output = args.raw_output_dir.resolve(), args.output_dir.resolve()
    require(not raw.exists() and not output.exists(), 'unused intake/results directories required')
    require(ROOT/'recordings' in raw.parents and ROOT/'Experimental_results' in output.parents,
            'scoped intake/report directories required')
    files = checked_archive(args.archive)
    runtime = {name:sha((ROOT/'src'/name).read_bytes())
               for name in ('driver_telemetry_recording.py', 'webrtc_receive_ui.py')}
    result = analyze(files, expected_source_sha256=runtime)
    result['archive_sha256'] = sha(args.archive.read_bytes())
    result['supplied_files_sha256'] = {n:sha(payload) for n, payload in files.items()}
    result['review_code_sha256'] = sha(Path(__file__).read_bytes())
    result['intake_directory'] = str(raw.relative_to(ROOT))
    raw.mkdir(parents=True); output.mkdir(parents=True)
    for name, payload in files.items():
        with (raw/name).open('xb') as stream:
            stream.write(payload)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    compact = {k:v for k, v in result.items() if k not in ('numeric_fields', 'metadata', 'summary')}
    print(json.dumps(compact, indent=2))
