"""Fake ROS callback -> sender JSON -> actual fake RTC callback -> disk record."""
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
sys.path.insert(0, str(ROOT/'src'));sys.path.insert(0, str(ROOT/'tests'))
from driver_odometry_observation import OdometryObserver, checked_observation
from driver_telemetry_recording import TelemetryRecorder
from test_driver_motion_integration import FakeRequest, receiver_class
from test_driver_odometry_observation import message, sender_node


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def quiet(recorder):
    for _ in range(2000):
        s=recorder.snapshot()
        require(s['error'] is None, 'synthetic writer error')
        if s['state']=='recording' and s['pending']==s['in_flight']==0:
            return
        await asyncio.sleep(.001)
    raise ValueError('synthetic recorder drain timeout')


async def run(args):
    output,raw=args.output_dir.resolve(),args.raw_output_dir.resolve()
    require(not output.exists() and not raw.exists(), 'new output directories required')
    require(ROOT/'Experimental_results' in output.parents and ROOT/'recordings' in raw.parents,
            'scoped report/raw output directories required')
    node=sender_node();now=[10.]
    observer=OdometryObserver(clock=lambda:now[0]);node._odom_observer=observer
    recorder=TelemetryRecorder(raw,max_records=100,max_bytes=128*1024,queue_size=64)
    signals=NS(telemetry_received=NS(emit=Mock()),latency_updated=NS(emit=Mock()))
    server=receiver_class()(signals,telemetry_recorder=recorder)
    cases=[]
    recorder.start()
    try:
        await quiet(recorder);await server.handle_offer(FakeRequest(None));await quiet(recorder)
        handlers={}
        def on(event):
            def decorator(fn):handlers[event]=fn;return fn
            return decorator
        server.pc.handlers['datachannel'](NS(label='telemetry',on=on))
        async def send(name, expected_status, payload=None, expected_age=None):
            payload=node.get_telemetry_dict() if payload is None else payload
            payload['timestamp']=1794800000000+len(cases)*40
            wire=json.dumps(payload,allow_nan=False)
            handlers['message'](wire);await quiet(recorder)
            cases.append(dict(case=name,wire_payload=json.loads(wire),expected_stamp_status=expected_status,
                              expected_callback_age_sec=expected_age))
        await send('not_received','not_received')
        node.odom_callback(message());await send('received_zero','first',expected_age=0.)
        now[0]=10.1;node.odom_callback(message(sec=1001,v=.2,w=-.1));await send('forward','advanced')
        now[0]=10.2;node.odom_callback(message(sec=1002,v=-.2,w=.1));await send('reverse','advanced')
        now[0]=12.2;await send('no_callback_for_two_seconds','advanced',expected_age=2.)
        now[0]=13.;node.odom_callback(message(sec=1002,v=-.2,w=.1));await send('same_stamp_new_callback','repeated',expected_age=0.)
        now[0]=14.;node.odom_callback(message(sec=1000));await send('reversed_header_stamp','reversed')
        now[0]=15.;node.odom_callback(message(sec=0,nano=0));await send('unset_zero_header','missing')
        with observer.lock:
            busy=node.get_telemetry_dict()
        await send('observer_busy','observer_busy',busy)
        now[0]=float('nan');await send('invalid_sender_monotonic','clock_invalid');now[0]=16.
        legacy=node.get_telemetry_dict();legacy.pop('odometry_observation')
        await send('legacy_sender_no_metadata',None,legacy)
        unknown=node.get_telemetry_dict();unknown['odometry_observation']={'schema':'future'}
        await send('unknown_schema',None,unknown)
        invalid=node.get_telemetry_dict();invalid['odometry_observation']=None
        await send('invalid_metadata',None,invalid)
        with patch.object(observer,'observe',side_effect=RuntimeError('synthetic optional observer failure')):
            node.odom_callback(message(v=.3,w=-.2))
        await send('observer_exception_legacy_values_continue',None)
        server.pc.connectionState='closed';await server.pc.handlers['connectionstatechange']();await quiet(recorder)
        control=NS(label='control');server.pc.handlers['datachannel'](control)
        require(server.control_channel is control,'control channel changed')
    finally:
        status=recorder.close()
    require(status['state']=='closed' and status['shutdown_complete'] and status['error'] is None,
            'normal closed writer required')
    rows=[json.loads(line) for line in (raw/'received_telemetry.jsonl').read_bytes().splitlines()]
    telemetry=[r for r in rows if r['event_kind']=='telemetry']
    require(len(telemetry)==len(cases)==signals.telemetry_received.emit.call_count==14, 'case/message count mismatch')
    require(status['queued']==status['written']==len(rows) and status['queue_drops']==status['busy_drops']==0,
            'synthetic evidence dropped')
    results=[]
    for case,row in zip(cases,telemetry):
        payload=case['wire_payload']
        require(row['linear_mps']==payload['linear_x'] and row['angular_radps']==payload['angular_z'],
                'legacy telemetry value changed')
        require(row['measurement_valid'] is None and row['source_freshness_verified'] is False
                and row['published_to_ros'] is False and row['usable_for_ffb'] is False,
                'metadata granted unsupported authority')
        observed=row.get('odometry_observation')
        if case['expected_stamp_status'] is not None:
            checked_observation(observed)
            require(observed==payload['odometry_observation'] and observed['stamp_status']==case['expected_stamp_status'],
                    'source observation changed across transport/recording')
            if case['expected_callback_age_sec'] is not None:
                require(abs(observed['callback_age_sec']-case['expected_callback_age_sec'])<1e-9,'callback age changed')
        else:
            require(observed is None,'unknown/legacy/error acquired an observation')
        results.append(dict(case=case['case'],record_schema=row['schema'],
            metadata_state=row.get('odometry_metadata_state','legacy_sender'),
            stamp_status=None if observed is None else observed['stamp_status'],
            callback_received=None if observed is None else observed['callback_received'],
            sample_fields_valid=None if observed is None else observed['sample_fields_valid'],passed=True))
    require(telemetry[0]['linear_mps']==telemetry[1]['linear_mps']==0.
            and telemetry[0]['odometry_observation']['callback_received'] is False
            and telemetry[1]['odometry_observation']['callback_received'] is True,
            'initial zero and received zero not distinguishable')
    metadata=json.loads((raw/'telemetry_recording_metadata.json').read_bytes())
    require(all(sha(ROOT/'src'/name)==digest for name,digest in metadata['source_sha256'].items()),
            'receiver runtime provenance mismatch')
    source_paths=(ROOT/'src/webrtc_stream.py',ROOT/'src/driver_odometry_observation.py',
        ROOT/'src/driver_telemetry_recording.py',ROOT/'src/webrtc_receive_ui.py',Path(__file__),
        ROOT/'tests/test_driver_odometry_observation.py',ROOT/'tests/test_driver_motion_integration.py')
    prior=json.loads((ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    require(all(sha(ROOT/'src'/name)==digest for name,digest in prior['source_code_sha256'].items()),
            'old measurement/display computation changed')
    output.mkdir(parents=True)
    with (output/'cases.json').open('x') as stream:
        json.dump(dict(synthetic_only=True,cases=results),stream,indent=2);stream.write('\n')
    result=dict(schema='odometry_metadata_fake_pipeline_audit_v1',state='pass',synthetic_only=True,
        actual_sender_and_receiver_callback_bodies_executed=True,cases=len(cases),passed=len(results),
        record_schema_counts=dict(Counter(r['schema'] for r in telemetry)),
        source_stamp_status_counts=dict(Counter(r['odometry_observation']['stamp_status']
            for r in telemetry if r.get('odometry_observation') is not None)),
        metadata_state_counts=dict(Counter(r.get('odometry_metadata_state','legacy_sender') for r in telemetry)),
        original_UI_telemetry_and_control_preserved=True,initial_vs_received_zero_distinguished=True,
        repeated_stamp_not_renewed_by_callback=True,summary=status,receiver_metadata=metadata,
        code_sha256={str(p.relative_to(ROOT)):sha(p) for p in source_paths},
        artifacts_sha256={str(p.relative_to(ROOT)):sha(p) for p in raw.iterdir() if p.is_file()},
        old_measurement_computation_files_unchanged=len(prior['source_code_sha256']),
        actual_deployment_or_real_ROS_verified=False,header_clock_relation_verified=False,
        exposure_or_range_motion_alignment_verified=False,physical_metric_verified=False,
        usable_for_ffb=False,published_to_ros=False,G923_or_vehicle_started=False)
    with (output/'audit.json').open('x') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('code_sha256','artifacts_sha256','receiver_metadata')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--raw-output-dir',type=Path,required=True)
    asyncio.run(run(parser.parse_args()))
