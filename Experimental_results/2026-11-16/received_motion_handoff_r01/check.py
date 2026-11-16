"""Transfer SHA-bound received facts; never pair different experiment sessions."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from adapter import transfer, base
from driver_motion_time_join import MotionLog, read_motion_records


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    audit_path = args.source_audit.resolve()
    audit = base.strict_json(audit_path.read_bytes())
    base.require(audit['schema'] == 'odometry_metadata_live_audit_v1'
                 and audit['state'] == 'recording_verified', 'successful received observation audit required')
    intake = (ROOT/audit['raw_intake']).resolve()
    base.require(ROOT/'recordings' in intake.parents, 'scoped raw input required')
    for name in base.FILES:
        base.require(sha(intake/name) == audit['supplied_files_sha256'][name], 'raw SHA mismatch: '+name)
    md, summary = (base.strict_json((intake/name).read_bytes()) for name in base.FILES[1:])
    for name, digest in md['source_sha256'].items():
        base.require(name in ('driver_telemetry_recording.py', 'webrtc_receive_ui.py',
                              'driver_odometry_observation.py') and sha(ROOT/'src'/name) == digest,
                     'receiver recording source mismatch')
    base.require(len(audit['sessions']) == 1, 'single explicit input session required')
    session, clock = audit['sessions'][0], md['receiver_clock_id']
    old_path = ROOT/'Experimental_results/2026-11-16/motion_range_handoff_r01/results_r02/audit.json'
    old = base.strict_json(old_path.read_bytes())
    base.require(old['state'] == 'pass' and old['schema'] == 'offline_motion_range_handoff_audit_v1',
                 'successful historical range audit required')
    base.require(old['session'] != session, 'this experiment verifies separate sessions only')
    output, raw = args.output_dir.resolve(), args.raw_output_dir.resolve()
    base.require(ROOT/'Experimental_results' in output.parents and ROOT/'recordings' in raw.parents
                 and not output.exists() and not raw.exists(), 'unused scoped output directories required')
    input_path = intake/'received_telemetry.jsonl'
    base.require(input_path.stat().st_size <= 64*1024*1024, 'bounded raw input required')
    output.mkdir(parents=True); raw.mkdir(parents=True)
    motions, reasons, events = [], Counter(), 0
    motion_path, detail_path = raw/'normalized_motion.jsonl', raw/'handoff.jsonl'
    with MotionLog(motion_path, session=session, receiver_clock_id=clock,
                   max_records=100000, max_bytes=64*1024*1024) as log, detail_path.open('x') as details:
        with input_path.open('rb') as stream:
            while True:
                line = stream.readline(16*1024+1)
                if not line:
                    break
                base.require(len(line) <= 16*1024 and line.endswith(b'\n'), 'complete bounded input line required')
                events += 1
                base.require(events <= 100000, 'bounded input event count required')
                row = base.strict_json(line)
                if row['event_kind'] != 'telemetry':
                    base.checked_row(row, clock)
                    continue
                value = transfer(row, session=session, receiver_clock_id=clock)
                value['received_record_line_sha256'] = hashlib.sha256(line).hexdigest()
                base.require(not value['pairing_eligible'], 'unexpected pairing authority')
                log.write(value['motion_record']); motions.append(value['motion_record'])
                reasons.update(value['hold_reasons'])
                details.write(json.dumps(value, allow_nan=False, separators=(',', ':'))+'\n')
    restored = list(read_motion_records(motion_path, max_records=100000, max_bytes=64*1024*1024))
    base.require(restored == motions and len(motions) == audit['telemetry_records']
                 and events == summary['written'], 'received-to-motion roundtrip/count mismatch')
    base.require(all(m['measurement_valid'] is None and m['source_clock_id'] is None
                     and not m['usable_for_ffb'] and not m['published_to_ros'] for m in restored),
                 'observations acquired unsupported validity/clock/output authority')
    code = [Path(__file__).resolve(), Path(__file__).with_name('adapter.py').resolve(),
            ROOT/'src/driver_motion_time_join.py', ROOT/'tests/test_received_motion_handoff.py']
    result = dict(schema='offline_received_motion_handoff_audit_v1', state='pass',
        source_received_audit=str(audit_path.relative_to(ROOT)), source_received_audit_sha256=sha(audit_path),
        input_raw_sha256=audit['supplied_files_sha256'], received_session=session, receiver_clock_id=clock,
        source_archive_sha256=audit['archive_sha256'], input_events=events,
        normalized_motion_records=len(restored), roundtrip_equal=True, hold_reason_counts=dict(reasons),
        observed_values_preserved=True, source_integer_stamp_preserved=True, frame_preserved=True,
        measurement_validity_inferred=False, source_clock_identity_inferred=False,
        observed_zero_records=sum(m['linear_mps'] == 0. and m['angular_radps'] == 0. for m in motions),
        historical_range_session=old['session'], historical_range_records=old['counts']['samples'],
        historical_range_audit_sha256=sha(old_path), real_range_motion_join_attempts=0,
        real_range_motion_pairs=0, separate_session_reason='different_recorded_sessions_NOT_joined',
        code_sha256={str(p.relative_to(ROOT)):sha(p) for p in code},
        derived_raw_sha256={str(p.relative_to(ROOT)):sha(p) for p in (motion_path, detail_path)},
        runtime_changed=False, runtime_or_ROS_or_G923_started=False,
        clock_alignment_verified=False, vehicle_transform_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-audit', 'output-dir', 'raw-output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    run(parser.parse_args())
