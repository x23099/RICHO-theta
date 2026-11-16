"""Fake sender clock -> sender JSON -> actual fake receiver callback -> disk."""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src')); sys.path.insert(0, str(ROOT/'tests'))
from driver_odometry_observation import OdometryObserver
from driver_sender_clock_observation import SenderClockObserver, checked_clock_observation
from driver_telemetry_recording import TelemetryRecorder
from test_driver_motion_integration import FakeRequest, receiver_class
from test_driver_odometry_observation import sender_node, message


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def quiet(recorder):
    for _ in range(2000):
        status = recorder.snapshot()
        require(status['error'] is None, 'fake writer failed')
        if status['state'] == 'recording' and status['pending'] == status['in_flight'] == 0:
            return
        await asyncio.sleep(.001)
    raise ValueError('fake recorder drain timeout')


async def run(args):
    output, raw = args.output_dir.resolve(), args.raw_output_dir.resolve()
    require(not output.exists() and not raw.exists() and ROOT/'Experimental_results' in output.parents
            and ROOT/'recordings' in raw.parents, 'unused scoped outputs required')
    state = dict(mono=10_000_000_000, ros=1794822450209981778, sim=False)
    def mono():
        value = state['mono']; state['mono'] += 1000
        return value
    node = sender_node()
    node.get_clock = lambda:NS(clock_type=NS(name='ROS_TIME'), ros_time_is_active=state['sim'],
                              now=lambda:NS(nanoseconds=state['ros']))
    node.get_parameter = lambda name:NS(value=state['sim'])
    node._odom_observer = OdometryObserver(clock=lambda:state['mono']/1e9)
    observer = SenderClockObserver(sender_id=node._odom_observer.sender_id,
                                   read_clock=node._read_sender_clock, monotonic_ns=mono)
    node._sender_clock_observer = observer
    recorder = TelemetryRecorder(raw, max_bytes=256*1024, max_records=100, queue_size=64)
    signals = NS(telemetry_received=NS(emit=Mock()), latency_updated=NS(emit=Mock()))
    server = receiver_class()(signals, telemetry_recorder=recorder)
    cases = []
    recorder.start()
    try:
        await quiet(recorder); await server.handle_offer(FakeRequest(None)); await quiet(recorder)
        handlers = {}
        def on(event):
            def decorator(fn):
                handlers[event] = fn; return fn
            return decorator
        server.pc.handlers['datachannel'](NS(label='telemetry', on=on))
        async def send(name, status=None, payload=None, metadata_state='versioned_sender_clock_observation'):
            payload = node.get_telemetry_dict() if payload is None else payload
            wire = json.dumps(payload, allow_nan=False)
            handlers['message'](wire); await quiet(recorder)
            cases.append(dict(case=name, payload=json.loads(wire), expected_clock_status=status,
                              expected_metadata_state=metadata_state))
        await send('initial_odom_unreceived_clock_sampled', 'sampled')
        node.odom_callback(message()); state['ros'] += 1
        await send('received_stop', 'sampled')
        state['ros'] += 1; node.odom_callback(message(sec=1001, v=.2, w=-.1))
        await send('forward', 'sampled')
        node.odom_callback(message(sec=1002, v=-.2, w=.1))
        await send('reverse_and_repeated_ros_now', 'sampled')
        state['ros'] -= 100; await send('ROS_reversal', 'sampled')
        state['ros'] = 0; await send('uninitialized_ROS_zero', 'sampled')
        state['ros'] = 1000; state['sim'] = True
        await send('clock_configuration_change', 'sampled')
        with patch.object(node, 'get_clock', side_effect=RuntimeError('fake reader failure')):
            await send('reader_failure_no_cached_clock', 'sampling_error')
        state['sim'] = False; state['ros'] = 1794822450209982778
        await send('recovery_new_generation', 'sampled')
        with observer.lock:
            busy = node.get_telemetry_dict()
        await send('clock_observer_busy', 'observer_busy', busy)
        with patch.object(observer, 'monotonic_ns', side_effect=iter([5, 4])):
            await send('reversed_monotonic', 'monotonic_invalid')
        state['mono'] += 1000; await send('post_invalid_recovery', 'sampled')
        invalid = node.get_telemetry_dict(); invalid['sender_clock_observation'] = None
        await send('invalid_clock_metadata', payload=invalid, metadata_state='invalid_sender_clock_metadata')
        unknown = node.get_telemetry_dict(); unknown['sender_clock_observation'] = {'schema':'future'}
        await send('unknown_clock_schema', payload=unknown, metadata_state='unsupported_sender_clock_schema')
        foreign = node.get_telemetry_dict()
        foreign['sender_clock_observation'].update(sender_id='c'*32, sender_monotonic_clock_id='sender-process/'+'c'*32)
        await send('foreign_sender_clock', payload=foreign, metadata_state='sender_clock_scope_mismatch')
        v2 = node.get_telemetry_dict(); del v2['sender_clock_observation']
        await send('legacy_v2_without_clock', payload=v2, metadata_state=None)
        v1 = dict(v2); del v1['odometry_observation']
        await send('legacy_v1_without_odometry', payload=v1, metadata_state=None)
        server.pc.connectionState = 'closed'; await server.pc.handlers['connectionstatechange'](); await quiet(recorder)
        control = NS(label='control'); server.pc.handlers['datachannel'](control)
        require(server.control_channel is control, 'control channel changed')
    finally:
        summary = recorder.close()
    require(summary['state'] == 'closed' and summary['error'] is None and summary['shutdown_complete'],
            'complete fake recording required')
    rows = [json.loads(line) for line in (raw/'received_telemetry.jsonl').read_bytes().splitlines()]
    telemetry = [r for r in rows if r['event_kind'] == 'telemetry']
    require(len(telemetry) == len(cases) == signals.telemetry_received.emit.call_count == 17,
            'case/UI/record count mismatch')
    results = []
    for case, row in zip(cases, telemetry):
        require(row['sender_clock_metadata_state'] == case['expected_metadata_state']
                if 'sender_clock_metadata_state' in row else case['expected_metadata_state'] is None,
                'clock decode state mismatch')
        original = case['payload']
        require(row['linear_mps'] == original['linear_x'] and row['angular_radps'] == original['angular_z'],
                'legacy telemetry values changed')
        clock = row.get('sender_clock_observation')
        if case['expected_clock_status'] is not None:
            checked_clock_observation(clock)
            require(clock == original['sender_clock_observation'] and clock['status'] == case['expected_clock_status'],
                    'source clock observation changed')
        else:
            require(clock is None, 'unavailable clock acquired a value')
        require(row['measurement_valid'] is None and row['source_clock_id'] is None
                and row['source_freshness_verified'] is False and row['usable_for_ffb'] is False
                and row['published_to_ros'] is False, 'record acquired unsupported authority')
        results.append(dict(case=case['case'], schema=row['schema'], status=None if clock is None else clock['status'],
            ros_time_status=None if clock is None else clock['ros_time_status'],
            clock_generation=None if clock is None else clock['clock_generation'], passed=True))
    require(summary['offered'] == summary['queued'] == summary['written'] == 19
            and summary['queue_drops'] == summary['busy_drops'] == summary['rejected'] == 0,
            'fake recording dropped records')
    metadata = json.loads((raw/'telemetry_recording_metadata.json').read_bytes())
    require(all(sha(ROOT/'src'/n) == h for n, h in metadata['source_sha256'].items()), 'recorded code SHA mismatch')
    previous = json.loads((ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    require(all(sha(ROOT/'src'/n) == h for n, h in previous['source_code_sha256'].items()),
            'existing distance/display computation changed')
    code = [ROOT/'src/webrtc_stream.py', ROOT/'src/driver_sender_clock_observation.py',
        ROOT/'src/driver_telemetry_recording.py', ROOT/'src/driver_odometry_observation.py',
        ROOT/'src/webrtc_receive_ui.py', Path(__file__).resolve(),
        ROOT/'tests/test_driver_sender_clock_observation.py', ROOT/'tests/test_driver_motion_integration.py']
    result = dict(schema='sender_ros_clock_bracket_fake_pipeline_audit_v1', state='pass', synthetic_only=True,
        cases=17, passed=17, schema_counts=dict(Counter(r['schema'] for r in telemetry)),
        actual_sender_and_receiver_callback_executed=True, legacy_UI_and_control_values_preserved=True,
        summary=summary, receiver_metadata=metadata,
        old_distance_display_sources_unchanged=len(previous['source_code_sha256']),
        code_sha256={str(p.relative_to(ROOT)):sha(p) for p in code},
        raw_sha256={str(p.relative_to(ROOT)):sha(p) for p in raw.iterdir() if p.is_file()},
        header_clock_relation_verified=False, receiver_clock_binding_verified=False,
        source_freshness_verified=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False, deployed_or_real_ROS_verified=False)
    output.mkdir(parents=True)
    for name, data in (('audit.json', result), ('cases.json', results)):
        with (output/name).open('x') as stream:
            json.dump(data, stream, indent=2); stream.write('\n')
    print(json.dumps(dict(state='pass', cases=17, schema_counts=result['schema_counts'],
                         written=summary['written'], synthetic_only=True), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output-dir', 'raw-output-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
