"""Recompute local load summaries from CSV, not from expected performance."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from bench import ROOT, describe, sha


def key(row):
    return row['workload'], int(row['packet_hz']), int(row['repetition'])


def equal(left, right):
    if left is None or right is None:
        return left is right
    return abs(left-right) <= 1e-6*max(1.,abs(left),abs(right))


def same_stats(expected, values):
    actual=describe(values)
    if set(expected) != set(actual) or any(not equal(expected[k],actual[k]) for k in actual):
        raise ValueError('recorded summary differs from CSV statistics')


def event_counts(events):
    offered, completed = {}, {}
    for event in events:
        membership=event['in_measurement_window']
        if type(membership) is not bool and membership not in ('True','False'):
            raise ValueError('explicit measurement-window membership required')
        if event['in_measurement_window'] in (False,'False'):
            continue
        seq,at,admitted=int(event['sequence']),float(event['local_time_sec']),float(event['admitted_at_sec'])
        if (event['event'] not in ('offered','send_complete') or seq<=0
                or not math.isfinite(at) or not math.isfinite(admitted) or admitted<0 or at<admitted):
            raise ValueError('unknown event or reversed local time')
        target=offered if event['event']=='offered' else completed
        if seq in target:
            raise ValueError('duplicate source event')
        target[seq]=(at,admitted)
    if set(completed)-set(offered):
        raise ValueError('send completion without source offer')
    for seq,(at,admitted) in completed.items():
        if offered[seq] != (admitted,admitted) or at-admitted > .201:
            raise ValueError('changed source admission or extended sender deadline')
    return offered,completed


def recompute(audit,samples,events):
    if (audit['real_network_or_camera_or_ROS_or_G923_started'] is not False
            or audit['usable_for_ffb'] is not False or audit['source_images_or_pixels_modified'] is not False):
        raise ValueError('offline non-controlling experiment required')
    grouped, event_groups = defaultdict(list),defaultdict(list)
    for row in samples:
        if row['kind'] not in ('video','packet'):
            raise ValueError('unknown encoder record')
        start,finish,captured=(float(row[k]) for k in ('started_at_sec','finished_at_sec','captured_at_sec'))
        if not captured <= start <= finish:
            raise ValueError('reversed encoder timing')
        if (not equal(float(row['encode_ms']),(finish-start)*1000)
                or not equal(float(row['admission_to_finish_ms']),(finish-captured)*1000)):
            raise ValueError('timing equation differs from source CSV')
        grouped[key(row)].append(row)
    for event in events:
        event_groups[key(event)].append(event)
    expected={(workload,rate,rep) for workload in ('static_repeat','discontinuous_cycle')
              for rate in (0,5,10,30) for rep in (1,2)}
    seen=set()
    for trial in audit['trials']:
        scope=key(trial)
        if scope in seen or scope not in expected:
            raise ValueError('duplicate/unexpected trial')
        seen.add(scope)
        video=[r for r in grouped[scope] if r['kind']=='video']
        packet=[r for r in grouped[scope] if r['kind']=='packet']
        offered,completed=event_counts(event_groups[scope])
        packet_identity={int(r['sequence']):float(r['captured_at_sec']) for r in packet}
        if (len(packet_identity)!=len(packet) or set(packet_identity)-set(offered)
                or set(completed)-set(packet_identity)
                or any(packet_identity[seq]!=offered[seq][1] for seq in packet_identity)):
            raise ValueError('encode/offer/send source identity differs')
        if (trial['video_encoded'] != sum(int(r['messages'])>0 for r in video)
                or trial['video_codec_empty'] != sum(int(r['messages'])==0 for r in video)
                or trial['packet_encoded'] != len(packet) or trial['packet_offered'] != len(offered)
                or trial['packet_completed'] != len(completed)
                or trial['packet_missing_sequences'] != sorted(set(offered)-set(completed))
                or not trial['all_workers_stopped'] or trial['packet_worker_counts']['peak_queued']>1):
            raise ValueError('counts/queue/termination differ from source records')
        for field,values in (
                ('video_encode_ms',[float(r['encode_ms']) for r in video]),
                ('video_admission_to_finish_ms',[float(r['admission_to_finish_ms']) for r in video]),
                ('packet_encode_ms',[float(r['encode_ms']) for r in packet]),
                ('packet_wire_bytes',[int(r['payload_bytes']) for r in packet]),
                ('packet_admission_to_fake_send_ms',[(at-admitted)*1000 for at,admitted in completed.values()])):
            same_stats(trial[field],values)
        for field,records in (('video_payload_mbps',video),('packet_encoded_mbps',packet)):
            if not equal(trial[field],sum(int(r['payload_bytes']) for r in records)*8/trial['duration_sec']/1e6):
                raise ValueError('generated bytes/rate differs from source records')
        if not equal(trial['process_cpu_cores'],trial['process_cpu_sec']/trial['measured_cpu_window_wall_sec']):
            raise ValueError('CPU equation mismatch')
    if seen != expected or set(grouped)-expected or set(event_groups)-expected:
        raise ValueError('complete 16-condition record required')
    profiles=[]
    for workload in ('static_repeat','discontinuous_cycle'):
        for rate in (0,5,10,30):
            trials=[t for t in audit['trials'] if t['workload']==workload and t['packet_hz']==rate]
            vrows=[r for rep in (1,2) for r in grouped[(workload,rate,rep)] if r['kind']=='video']
            prows=[r for rep in (1,2) for r in grouped[(workload,rate,rep)] if r['kind']=='packet']
            latency,gaps=[],[]
            for rep in (1,2):
                _,done=event_counts(event_groups[(workload,rate,rep)])
                latency.extend((at-admitted)*1000 for at,admitted in done.values())
                completed_times=sorted(at for at,_ in done.values())
                gaps.extend((b-a)*1000 for a,b in zip(completed_times,completed_times[1:]))
            duration=sum(t['duration_sec'] for t in trials)
            profiles.append(dict(workload=workload,packet_hz=rate,repetitions=2,
                video_encoded=sum(t['video_encoded'] for t in trials),
                video_encode_ms=describe([float(r['encode_ms']) for r in vrows]),
                video_admission_to_finish_ms=describe([float(r['admission_to_finish_ms']) for r in vrows]),
                packet_offered=sum(t['packet_offered'] for t in trials),
                packet_completed=sum(t['packet_completed'] for t in trials),
                packet_missing=sum(len(t['packet_missing_sequences']) for t in trials),
                packet_encode_ms=describe([float(r['encode_ms']) for r in prows]),
                packet_admission_to_fake_send_ms=describe(latency),
                packet_completion_gap_ms=describe(gaps),
                video_payload_mbps=sum(int(r['payload_bytes']) for r in vrows)*8/duration/1e6,
                packet_encoded_mbps=sum(int(r['payload_bytes']) for r in prows)*8/duration/1e6,
                process_cpu_cores=sum(t['process_cpu_sec'] for t in trials)/sum(t['measured_cpu_window_wall_sec'] for t in trials),
                timer_ticks_skipped=sum(t['timer_ticks_skipped_including_warmup'] for t in trials),
                video_pending_replaced=sum(t['video_pending_replaced'] for t in trials),
                video_expired_before_encode=sum(t['video_expired_before_encode'] for t in trials)))
    return profiles


def run(source,output):
    source,output=source.resolve(),output.resolve()
    base=ROOT/'Experimental_results/2026-11-18/frame_packet_load_r01'
    if base not in source.parents or base not in output.parents or output.exists():
        raise ValueError('existing experiment input and unused analysis output required')
    audit=json.loads((source/'audit.json').read_bytes())
    for group in ('packet_and_runtime_sources_unchanged','source_code_sha256'):
        if any(sha(ROOT/name)!=digest for name,digest in audit[group].items()):
            raise ValueError('benchmark sources differ from run')
    for value in audit['source_images']:
        if sha(ROOT/value['path'])!=value['sha256']:
            raise ValueError('original camera source changed')
    with (source/'samples.csv').open() as file:
        samples=list(csv.DictReader(file))
    with (source/'events.csv').open() as file:
        events=list(csv.DictReader(file))
    profiles=recompute(audit,samples,events)
    result=dict(schema='frame_packet_load_csv_recheck_v1',state='pass',
        executed_utc=datetime.now(timezone.utc).isoformat(),
        source_files_sha256={str((source/name).relative_to(ROOT)):sha(source/name)
                             for name in ('audit.json','samples.csv','events.csv','trial_progress.jsonl')},
        source_code_sha256={str(Path(__file__).resolve().relative_to(ROOT)):sha(Path(__file__))},
        trials=16,sample_rows=len(samples),event_rows=len(events),profiles=profiles,
        source_images_unchanged=4,actual_network_measured=False,live_transport_adopted=False,
        source_freshness_verified=False,physical_metric_verified=False,usable_for_ffb=False,published_to_ros=False)
    output.mkdir(parents=True,exist_ok=False)
    with (output/'audit.json').open('x') as file:
        json.dump(result,file,ensure_ascii=False,indent=2,allow_nan=False);file.write('\n')
    columns=['workload','packet_hz','video_encoded','packet_offered','packet_completed','packet_missing',
             'process_cpu_cores','video_payload_mbps','packet_encoded_mbps']
    with (output/'profiles.csv').open('x',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns,extrasaction='ignore',lineterminator='\n')
        writer.writeheader();writer.writerows(profiles)
    print(json.dumps(dict(state='pass',trials=16,sample_rows=len(samples),event_rows=len(events)),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    run(args.input_dir,args.output_dir)
