"""Execute actual receiver callbacks with fake peers. No socket/ROS/Qt/GPU."""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from driver_telemetry_recording import TelemetryRecorder
from driver_motion_protocol import PROFILE
from test_driver_motion_integration import FakeRequest, receiver_class


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def quiet(recorder):
    for _ in range(2000):
        status = recorder.snapshot()
        require(status['error'] is None, 'synthetic writer failed')
        if status['state'] == 'recording' and status['pending'] == status['in_flight'] == 0:
            return
        await asyncio.sleep(.001)
    raise ValueError('bounded synthetic drain wait exceeded')


def message_handler(server, peer):
    handlers = {}
    def on(event):
        def decorator(function):
            handlers[event] = function
            return function
        return decorator
    peer.handlers['datachannel'](SimpleNamespace(label='telemetry', on=on))
    return handlers['message']


async def run(args):
    output, raw = args.output_dir.resolve(), args.raw_output_dir.resolve()
    require(not output.exists() and not raw.exists(), 'new output directories required')
    require(ROOT/'Experimental_results' in output.parents and ROOT/'recordings' in raw.parents,
            'scoped report/raw output directories required')
    recorder = TelemetryRecorder(raw, max_records=100, max_bytes=128*1024, queue_size=64)
    signals = SimpleNamespace(telemetry_received=SimpleNamespace(emit=Mock()),
                              latency_updated=SimpleNamespace(emit=Mock()))
    motion = SimpleNamespace(begin=Mock(), end=Mock())
    server = receiver_class()(signals, motion=motion, telemetry_recorder=recorder)
    recorder.start()
    try:
        await quiet(recorder)
        await server.handle_offer(FakeRequest(dict(PROFILE)))
        first, first_peer = motion.begin.call_args[0][0], server.pc
        first_handler = message_handler(server, first_peer)
        await quiet(recorder)
        for v in (.2, 0., -.2)*4:
            first_handler(json.dumps(dict(linear_x=v, angular_z=-.1, speed_mps=abs(v),
                                          timestamp=1794800000000)))
            await quiet(recorder)
        await server.handle_offer(FakeRequest(dict(PROFILE)))
        second, second_peer = motion.begin.call_args[0][0], server.pc
        second_handler = message_handler(server, second_peer)
        await quiet(recorder)
        for v in (.3, 0., -.3)*4:
            second_handler(json.dumps(dict(linear_x=v, angular_z=.1, speed_mps=abs(v),
                                           timestamp=1794800000040)))
            await quiet(recorder)
        first_handler('{"linear_x":0.123,"angular_z":-0.05}')  # old peer, not relabelled
        await quiet(recorder)
        first_peer.connectionState='closed'; await first_peer.handlers['connectionstatechange']()
        await quiet(recorder)
        second_peer.connectionState='closed'; await second_peer.handlers['connectionstatechange']()
        await quiet(recorder)
        control = SimpleNamespace(label='control'); second_peer.handlers['datachannel'](control)
        require(server.control_channel is control, 'control channel changed')
    finally:
        status = recorder.close()
    require(status['shutdown_complete'] and status['error'] is None and status['state'] == 'closed',
            'synthetic recorder shutdown incomplete')
    rows = [json.loads(line) for line in (raw/'received_telemetry.jsonl').read_bytes().splitlines()]
    telemetry = [r for r in rows if r['event_kind']=='telemetry']
    require(len(rows) == status['written'] == 29 and len(telemetry) == signals.telemetry_received.emit.call_count == 25,
            'fake callback recording/count mismatch')
    require(first != second and {r['session'] for r in rows} == {first, second}, 'session association lost')
    require(telemetry[-1]['session'] == first and telemetry[-1]['linear_mps'] == .123,
            'old peer assigned to newer session')
    require(all(r['received_at_sec'] <= r['logged_at_sec'] and r['measurement_valid'] is None
                and r['source_stamp_ns'] is None and r['source_clock_id'] is None
                and r['usable_for_ffb'] is False and r['published_to_ros'] is False for r in rows),
            'missing time/validity falsely granted')
    require(status['queued'] == status['written'] and status['queue_drops'] == status['busy_drops'] == 0,
            'quiet synthetic scenario dropped evidence')
    metadata = json.loads((raw/'telemetry_recording_metadata.json').read_bytes())
    require(metadata['source_sha256'] == {p: sha(ROOT/'src'/p) for p in metadata['source_sha256']},
            'runtime source provenance mismatch')
    require(status == json.loads((raw/'telemetry_recording_summary.json').read_bytes()), 'final summary mismatch')
    closed_audit = json.loads((ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    require(all(sha(ROOT/'src'/p) == digest for p, digest in closed_audit['source_code_sha256'].items()),
            'original measurement/display-computation source changed')
    files = [Path(__file__), ROOT/'src/driver_telemetry_recording.py', ROOT/'src/webrtc_receive_ui.py',
             ROOT/'src/webrtc_stream.py', ROOT/'tests/test_driver_telemetry_recording.py',
             ROOT/'tests/test_driver_motion_integration.py']
    result = dict(schema='receiver_telemetry_recording_fake_peer_audit_v1', state='pass',
        actual_receiving_callback_executed_with_fake_peer=True, synthetic_only=True,
        received_telemetry_messages=25, recorded_total_events=len(rows), recorded_telemetry_events=len(telemetry),
        event_counts=dict(Counter(r['event_kind'] for r in rows)), session_count=2,
        old_peer_not_relabelled=True, ui_notifications_preserved=True, control_channel_preserved=True,
        measurement_computation_code_files_unchanged=len(closed_audit['source_code_sha256']),
        summary=status, metadata=metadata,
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in files},
        evidence_sha256={str(p.relative_to(ROOT)):sha(p) for p in raw.iterdir() if p.is_file()},
        ROS_telemetry_or_robot_started=False, real_camera_or_GPU_started=False,
        real_receive_recording_verified=False, real_exposure_or_motion_alignment_verified=False,
        distance_used_for_control=False, physical_metric_verified=False, published_to_ros=False, usable_for_ffb=False)
    output.mkdir(parents=True)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(dict(state='pass', messages=25, events=len(rows), summary=status), indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--raw-output-dir', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
