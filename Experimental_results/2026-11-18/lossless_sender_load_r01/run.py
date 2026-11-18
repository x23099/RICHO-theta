"""Offline PNG continuous-load scenarios using frozen source images and costs."""
import argparse
import csv
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import statistics
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SPEC=importlib.util.spec_from_file_location('load_previous',HERE.parent/'lossless_frame_packet_r01/run.py')
previous=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(previous)
probe=previous.probe
sys.path.insert(0,str(HERE))
import model


def templates_and_evidence():
    cases,inputs=previous.previous.load_cases()
    evidence=HERE.parent/'lossless_frame_packet_r01'
    audit_path=evidence/'results_r02/audit.json'
    rows_path=evidence/'results_r02/trials.jsonl'
    check_path=evidence/'verification_r01/audit.json'
    audit=json.loads(audit_path.read_bytes());check=json.loads(check_path.read_bytes())
    for name,sha in {**audit['source_code_sha256'],**check['source_code_sha256'],**check['unchanged_runtime_source_sha256']}.items():
        if probe.digest(ROOT/name)!=sha:raise ValueError('previous code changed: '+name)
    if (probe.digest(rows_path)!=audit['trials_sha256']
            or probe.digest(audit_path)!=check['result_audit_sha256']):
        raise ValueError('frozen packet evidence changed')
    for path in (audit_path,rows_path,check_path):inputs[str(path.relative_to(ROOT))]=probe.digest(path)
    rows=[json.loads(line) for line in rows_path.read_bytes().splitlines()]
    templates=[];costs=[]
    for index,case in enumerate(cases,1):
        name=Path(case['job']['path']).name
        saved=[r for r in rows if r['image']==name]
        if len(saved)!=5 or any(r['pixel_sha256']!=case['job']['pixel_sha256'] for r in saved):
            raise ValueError('five exact original input cost samples required')
        # Previous stage includes source pre-first validation and receiver
        # assembly. Subtract the measured first-arrival-to-take interval, then
        # add back decode-only work to isolate pre-first sender validation.
        pre_first=[r['fragmentation_reassembly_validate_ms']-
            (r['local_first_fragment_to_take_ms']-r['decode_validate_copy_ms']) for r in saved]
        if any(v<0 for v in pre_first):raise ValueError('invalid previous timing scope')
        encoding=statistics.median(r['encode_validate_ms'] for r in saved)
        preparation=statistics.median(pre_first)
        receiving=statistics.median(r['local_first_fragment_to_take_ms'] for r in saved)
        wire=previous.packet.encode_packet(case['job']['image'],previous.metadata(index))
        header,payload=previous.packet.unpack_packet(wire)
        if header['bgr_sha256']!=case['job']['pixel_sha256']:raise ValueError('template source pixel mismatch')
        templates.append(model.Template(name,header,payload,encoding+preparation,receiving))
        costs.append(dict(image=name,pixel_sha256=header['bgr_sha256'],PNG_payload_bytes=len(payload),
            median_encode_validate_ms=encoding,derived_median_pre_first_validation_ms=preparation,
            sender_model_service_ms=encoding+preparation,receiver_model_service_ms=receiving,
            timing_scope='frozen_analysis_PC_CPU_samples_NOT_GPUPC_or_robot',
            new_continuous_encoding_measured=False))
    return cases,inputs,templates,costs,check


def scenarios():
    output=[dict(name=f'base_{rate}Mbps_{hz}Hz',hz=hz,rate_mbps=rate)
        for hz in (5,10) for rate in (15,30,100)]
    output.extend([
        dict(name='stall_100Mbps_10Hz',hz=10,rate_mbps=100,stall=(1.,1.6)),
        dict(name='loss_100Mbps_10Hz',hz=10,rate_mbps=100,loss_every=127),
        dict(name='slow_receiver_100Mbps_10Hz',hz=10,rate_mbps=100,receiver_scale=2.5),
        dict(name='slow_sender_100Mbps_10Hz',hz=10,rate_mbps=100,sender_scale=2.),
        dict(name='delayed_first_100Mbps_10Hz',hz=10,rate_mbps=100,transit_delay_sec=.5)])
    return output


def run(output):
    output=Path(output).resolve()
    if output.exists() or HERE not in output.parents:raise ValueError('unused experiment output required')
    cases,inputs,templates,costs,old_check=templates_and_evidence()
    paths=[Path(__file__),HERE/'model.py',ROOT/'src/driver_lossless_frame_sender.py']
    sources={str(p.relative_to(ROOT)):probe.digest(p) for p in paths}
    summaries=[];trace=[]
    for options in scenarios():
        summary,rows=model.simulate(templates,**options)
        summaries.append(summary);trace.extend(rows)
        print(json.dumps(dict(scenario=options['name'],consumed=summary['counts']['consumed'],
            captured=summary['counts']['captured'],sender_expired=summary['sender']['expired'],
            max_receiver_ms=summary['max_receiver_local_first_to_take_ms'],
            oracle_max_capture_to_take_ms=summary['oracle_max_capture_to_take_ms'])),flush=True)
    probe.assert_originals([c['job'] for c in cases])
    frozen={**old_check['source_code_sha256'],**old_check['unchanged_runtime_source_sha256']}
    if any(probe.digest(ROOT/n)!=sha for n,sha in {**sources,**inputs,**frozen}.items()):
        raise ValueError('code/input changed during load model')
    output.mkdir(parents=True,exist_ok=False)
    for name,values in (('scenarios.jsonl',summaries),('consumed.jsonl',trace)):
        with (output/name).open('xb') as target:
            for row in values:target.write(probe.json_bytes(row))
    fields=('scenario','Hz','ideal_Mbps','captured','consumed','consumed_fraction','sender_expired',
        'raw_pending_replaced','decode_pending_replaced','max_receiver_local_ms','oracle_max_capture_to_take_ms')
    with (output/'summary.csv').open('x') as target:
        writer=csv.DictWriter(target,fieldnames=fields);writer.writeheader()
        for s in summaries:
            writer.writerow(dict(scenario=s['name'],Hz=s['hz'],ideal_Mbps=s['ideal_rate_Mbps'],
                captured=s['counts']['captured'],consumed=s['counts']['consumed'],consumed_fraction=s['consumed_fraction'],
                sender_expired=s['sender']['expired'],raw_pending_replaced=s['counts']['raw_pending_replaced'],
                decode_pending_replaced=s['counts']['decode_pending_replaced'],max_receiver_local_ms=s['max_receiver_local_first_to_take_ms'],
                oracle_max_capture_to_take_ms=s['oracle_max_capture_to_take_ms']))
    audit=dict(schema='offline_lossless_sender_load_v1',state='pass',work_date='2026-11-18',
        executed_utc=datetime.now(timezone.utc).isoformat(),scenario_count=len(summaries),
        captured_total=sum(s['counts']['captured'] for s in summaries),
        consumed_total=len(trace),templates=costs,model_tick_sec=model.TICK_SEC,
        channel_buffer_bound_bytes=model.BUFFER_BYTES,model_flight_bound_bytes=model.FLIGHT_CAP,
        capture_or_decode_waiting_policy='one_active_plus_one_latest_pending',
        source_candidate_scope='synthetic_capture_fixture_NO_recorded_odometry',
        source_code_sha256=sources,input_sha256=inputs,unchanged_previous_source_sha256=frozen,
        artifact_sha256={n:probe.digest(output/n) for n in ('scenarios.jsonl','consumed.jsonl','summary.csv')},
        source_freshness_verified=False,real_clock_alignment_used=False,
        real_network_or_continuous_encoding_measured=False,new_GPU_inference=False,
        live_runtime_connected=False,source_images_modified=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(audit))
    return audit


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
