"""Bounded archive audit; no remote paths, model, camera, network or control.

Recompute CPU geometry from original pixels and submitted NEW detection boxes.
This validates their downstream use, NOT independent verification of CUDA boxes.
"""
import argparse
from collections import Counter
import copy
import csv
import hashlib
import json
import math
from pathlib import Path,PurePosixPath
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_replay_r01'))
import cuda_replay as replay
from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge


def require(condition,message):
    if not condition:raise ValueError(message)


def archive_payload(path, *, prefix='guarded_cuda_gpu_r01'):
    """Never extract links/special files or trust names as filesystem targets."""
    require(isinstance(prefix,str) and re.fullmatch(r'guarded_cuda_gpu_r[0-9]{2}',prefix),
        'explicit bounded archive root required')
    out={};seen=set();total=0
    with tarfile.open(path,'r:xz') as archive:
        for i,member in enumerate(archive):
            require(i<128,'too many archive entries')
            name=member.name.rstrip('/');p=PurePosixPath(name)
            require(name==str(p) and not p.is_absolute() and '..' not in p.parts
                and '\\' not in name and p.parts[0]==prefix,'unsafe archive path')
            require(name not in seen,'duplicate archive entry');seen.add(name)
            require(member.isdir() or member.isfile(),'links and special files rejected')
            if member.isdir():continue
            require(0<=member.size<=16*1024*1024,'oversized archive entry')
            total+=member.size;require(total<=64*1024*1024,'oversized expanded archive')
            payload=archive.extractfile(member).read(member.size+1)
            require(len(payload)==member.size,'incomplete archive member')
            out[str(p.relative_to(prefix))]=payload
    require('summary.json' in out,'summary required')
    return out


def rows(payload):
    require(not payload or payload.endswith(b'\n'),'incomplete JSONL')
    return [replay.parse_json(line) for line in payload.splitlines()]


def close(a,b,tolerance=1e-6):
    require(math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance,'timing mismatch')


def checked_primary(row,job,session,sequence,profile_sha):
    require(row['schema']=='cone_motion_range_v1' and row['session']==session
        and row['frame']==sequence and row['original_session']==job['session']
        and row['original_frame']==job['frame'],'primary identity mismatch')
    require(row['input_pixel_sha256']==job['pixel_sha256'] and row['profile_sha256']==profile_sha,
        'primary input/profile mismatch')
    require(row['inference_source']=='cuda_yolo_on_saved_native_png_NOT_live_camera'
        and row['input_source']=='preloaded_historical_native_png_NOT_camera_or_RTC'
        and row['source_time_kind']=='synthetic_monotonic_arrival_at_predictor_call','inference/input kind mismatch')
    require(all(row[k] is False for k in replay.FLAGS),'control/physical authority must remain false')
    for field in ('frame_age_ms','predict_ms','support_geometry_ms'):
        require(type(row[field]) in (int,float) and math.isfinite(row[field]) and row[field]>=0,'invalid primary timing')
    require(0<=row['completed_time_sec']-row['source_time_sec']<=.5,'stale primary row')
    close(row['frame_age_ms'],1000*(row['completed_time_sec']-row['source_time_sec']))
    close(row['frame_age_ms'],row['predict_ms']+row['support_geometry_ms'])
    for box in row['raw_detector_boxes']:
        require(box['image']==f'{session}:{sequence}','detector provenance mismatch')


def audit(payload,data):
    import cv2
    import numpy as np
    summary=replay.parse_json(payload['summary.json'])
    require(summary['state']=='complete' and summary['schema']=='guarded_cuda_saved_image_benchmark_v1'
        and summary['actual_cuda_inference'] is True and summary['execution_kind']=='actual_cuda',
        'complete real CUDA execution required')
    require(all(summary[k] is False for k in ('actual_camera','actual_vehicle_operation',
        'live_latency_verified','physical_metric_verified','usable_for_ffb','published_to_ros')),'invalid headline flags')
    require(summary['requested_fps']==30 and summary['warmup_excluded_calls']==8,'unexpected run options')
    require(len(summary['blocks'])==4,'four blocks required')
    # Known-path allowlist. Never open a remote path from summary.json.
    preflight=ROOT/'recordings/2026-11-11/guarded_cuda_preflight_r02/summary.json'
    original=replay.parse_json(preflight.read_bytes())
    local_by_name={Path(name).name:(Path(name),digest) for name,digest in original['input_sha256'].items()}
    require(len(local_by_name)==25,'25 known local inputs required')
    known={}
    for name,digest in summary['input_sha256'].items():
        path=PurePosixPath(name)
        require(path.is_absolute() and '..' not in path.parts,'invalid recorded input path')
        require(path.name not in known,'ambiguous recorded input');known[path.name]=digest
    require(set(known)==set(local_by_name)|{'cone_distance_v03.pt'},'unexpected recorded input list')
    for name,(path,digest) in local_by_name.items():
        require(known[name]==digest==replay.hash_regular(path,512*1024*1024),'original input SHA mismatch')
    require(known['cone_distance_v03.pt']==summary['weights_sha256']==data['settings']['weights_sha256'],
        'checkpoint SHA mismatch')
    source_hashes=dict(summary['source_sha256'])
    for block in summary['blocks']:
        if not block['comparison_enabled']:continue
        for name,digest in block['comparison_final_status']['source_sha256'].items():
            key='src/'+name
            require(key not in source_hashes or source_hashes[key]==digest,'inconsistent source SHA')
            source_hashes[key]=digest
    require(len(source_hashes)==24,'expected benchmark/dependency source hashes')
    for name,digest in source_hashes.items():
        p=PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and str(p)==name,'unsafe recorded source path')
        require((ROOT/name).resolve().is_relative_to(ROOT),'source escapes repository')
        require(replay.hash_regular(ROOT/name,512*1024)==digest,'source SHA mismatch: '+name)
    warmup=rows(payload['warmup.jsonl'])
    require(len(warmup)==8 and [r['call'] for r in warmup]==list(range(1,9)),'invalid warmup calls')
    require(all(r['excluded_from_measured_distributions'] is True for r in warmup),'warmup not excluded')
    recomputed_blocks=[];sessions=set();geometry_cache={};comparison_cache={};sample_rows=[]
    allowed={'summary.json','warmup.jsonl','model/ultralytics_config/matplotlib/fontlist-v390.json',
        'model/ultralytics_config/Ultralytics/Arial.ttf','model/ultralytics_config/Ultralytics/settings.json'}
    comparison_total=0;comparison_numeric=[];comparison_performance=[]
    for i,block in enumerate(summary['blocks']):
        enabled=i in (1,2);session=block['session'];label=f'block_{i:02d}_{"on" if enabled else "off"}'
        require(block['id']==i and block['comparison_enabled'] is enabled,'ABBA identity mismatch')
        require(re.fullmatch('[0-9a-f]{32}',session) and session not in sessions,'invalid/reused session');sessions.add(session)
        for name in ('primary_frames.jsonl','setup.jsonl'):allowed.add(label+'/'+name)
        setup_lines=payload[label+'/setup.jsonl'].splitlines(keepends=True)
        require(len(setup_lines)==1,'one setup row required')
        setup=replay.parse_json(setup_lines[0])
        ref_job=next(job for job in data['jobs'] if job['frame']==data['reference']['source_frame'])
        checked_primary(setup,ref_job,session,1,data['profile_sha'])
        primary=rows(payload[label+'/primary_frames.jsonl']);claims=block['records']
        require(len(primary)==len(claims)==160 and block['measured_frames']==160,'160 measured rows required')
        primary_by_frame={1:setup};last_source=setup['source_time_sec'];records=[]
        for n,(row,claim) in enumerate(zip(primary,claims)):
            job=data['jobs'][n%8];checked_primary(row,job,session,n+2,data['profile_sha'])
            require(row['source_time_sec']>last_source,'nonincreasing source time');last_source=row['source_time_sec']
            primary_by_frame[n+2]=row
            projection=replay.primary_signature(row)
            detector=replay.signature(replay.detector_values(row['raw_detector_boxes']))
            require(claim['block']==i and claim['comparison_enabled'] is enabled
                and claim['ordinal']==n and claim['cycle']==n//8 and claim['original_frame']==job['frame']
                and claim['replay_frame']==n+2 and claim['primary_signature']==projection
                and claim['detector_signature']==detector,'compact claim differs from primary log')
            for key,field in (('range_m','horizontal_camera_foot_range_m'),('distance_available','distance_available'),
                ('reason','reason'),('predict_ms','predict_ms'),('primary_ms','frame_age_ms'),('support_ms','support_geometry_ms')):
                require(claim[key]==row[field],'primary metric/claim mismatch: '+key)
            require(claim['period_overrun']==(row['frame_age_ms']>1000/30),'overrun count mismatch')
            require(claim['comparison_offer_accepted'] is (True if enabled else None),'comparison offer claim mismatch')
            if n:close(claim['start_interval_ms'],1000*(row['source_time_sec']-primary[n-1]['source_time_sec']))
            else:require(claim['start_interval_ms'] is None,'first interval must be absent')
            require(0<=claim['comparison_tap_ms']<=claim['primary_log_and_tap_ms']
                and claim['primary_log_and_tap_ms']>=row['frame_age_ms'],'invalid tap/log timing')
            key=(job['frame'],detector)
            if key not in geometry_cache:
                frame=replay.NativeFrame('a'*32,1,.1,1.,job['image'])
                engine=replay.MotionRangeEngine(data['settings'],data['camera'],data['profile'],data['profile_sha'],
                    acknowledged=True,target_roi=[270,0,350,720],observer=replay.observe_upper_completion)
                geometry_cache[key]=replay.primary_signature(engine.measure(frame,row['raw_detector_boxes'],1.01))
            require(geometry_cache[key]==projection,'CPU downstream baseline not reproduced')
            records.append(copy.deepcopy(claim))
            sample_rows.append(dict(block=i,comparison_enabled=enabled,ordinal=n,original_frame=job['frame'],
                predict_ms=row['predict_ms'],primary_ms=row['frame_age_ms'],support_ms=row['support_geometry_ms'],
                start_interval_ms=claim['start_interval_ms'],primary_log_and_tap_ms=claim['primary_log_and_tap_ms'],
                overrun=claim['period_overrun'],primary_reason=row['reason']))
        require(block['reason_counts']==dict(Counter(r['reason'] for r in primary)),'block reason counts')
        require(block['period_overruns']==sum(r['period_overrun'] for r in records),'block overrun count')
        for field in ('predict_ms','primary_ms'):
            require(block[field]==replay.distribution([r[field] for r in records]),'block distribution mismatch')
        require(block['measured_wall_sec']>=(primary[-1]['completed_time_sec']-primary[0]['source_time_sec']),
            'block elapsed time shorter than primary interval')
        if enabled:
            directory=label+'/comparison/';pin_name=f'decoded_{session}_f000001'
            for name in ('comparison_frames.jsonl','comparison_status.json','reference.json','request.json',pin_name+'.png',pin_name+'.json'):
                allowed.add(directory+name)
            final=replay.parse_json(payload[directory+'comparison_status.json']);pin=final['pin']
            ref=replay.parse_json(payload[directory+'reference.json']);png=payload[directory+pin_name+'.png']
            require(final==block['comparison_final_status'],'final status differs from summary')
            require(final['state']=='closed' and final['writer_done'] and final['shutdown_complete']
                and final['error'] is None and final['latest'] is None,'comparison did not close cleanly')
            require(final['offered']==final['processed']==161 and final['snapshots_saved']==1
                and final['latest_slot_overwrites']==final['tap_busy_drops']==0 and final['request_count']==2,
                'unexpected comparison accounting')
            require(block['comparison_shutdown']==dict(writer_stopped=True,shutdown_complete=True,error=None),'shutdown mismatch')
            require(all(final[k] is False for k in (*replay.FLAGS,'main_display_modified')),'invalid final authority')
            require(pin==replay.parse_json(payload[directory+pin_name+'.json']),'pin sidecar mismatch')
            require(pin['session']==session and pin['frame']==1 and pin['source_time_sec']==setup['source_time_sec']
                and pin['source_log_line_sha256']==replay.digest_bytes(setup_lines[0]),'pin/source binding mismatch')
            image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
            require(image.shape==(720,1280,3) and replay.digest_bytes(image.tobytes())==ref_job['pixel_sha256']
                ==pin['decoded_bgr_sha256'],'pin pixels differ from original native image')
            require(replay.digest_bytes(png)==pin['png_sha256']==ref['source_png_sha256'],'pin PNG SHA mismatch')
            expected_ref=copy.deepcopy(data['reference']);expected_ref.update(session=session,source_frame=1,
                source_png_sha256=pin['png_sha256'],offline_replay_binding_NOT_live_mount_evidence=True)
            require(ref==expected_ref,'reference is not exact historical-pixel replay binding')
            comparisons=rows(payload[directory+'comparison_frames.jsonl'])
            require(len(comparisons)==161 and [r['frame'] for r in comparisons]==list(range(1,162)),
                'comparison frames missing/duplicate')
            require(final['log_bytes']==len(payload[directory+'comparison_frames.jsonl']),'comparison log byte count')
            for row in comparisons:
                main=primary_by_frame[row['frame']]
                require(row['session']==session and row['source_time_sec']==main['source_time_sec']
                    and row['original_distance_available']==main['distance_available']
                    and row['original_range_m']==main['horizontal_camera_foot_range_m'],'comparison/main pairing')
                require(all(row[k] is False for k in (*replay.FLAGS,'main_display_modified','reference_used_posthoc')),
                    'comparison authority/posthoc mismatch')
                require(main['completed_time_sec']<=row['completed_time_sec']<=row['source_time_sec']+.5,
                    'comparison causality/freshness mismatch')
                comparison_performance.append(dict(block=i,frame=row['frame'],
                    service_ms=row['comparison_service_ms'],age_ms=1000*(row['completed_time_sec']-row['source_time_sec'])))
                if row['frame']==1:
                    require(not row['comparison_distance_available'] and not row['reference_scope_verified'],
                        'setup used future reference');continue
                require(row['reference_scope_verified'] and row['baseline_reproduced'] and row['reference_frame']==1
                    and row['reference_generation']==1,'comparison reference not valid')
                job=data['jobs'][(row['frame']-2)%8]
                key=(job['frame'],replay.signature(replay.detector_values(main['raw_detector_boxes'])))
                if key not in comparison_cache:
                    observed=compare_guarded_lower_edge(job['image'],main['selected_detector_boxes'][0],data['camera'],
                        data['reference'],session=job['session'],reference_matches=True)
                    engine=replay.MotionRangeEngine(data['settings'],data['camera'],data['profile'],data['profile_sha'],
                        acknowledged=True,target_roi=[270,0,350,720],observer=lambda *a:observed['proposed_observation'])
                    proposal=engine.measure(replay.NativeFrame('a'*32,1,.1,1.,job['image']),main['raw_detector_boxes'],1.01)
                    comparison_cache[key]=proposal
                proposal=comparison_cache[key]
                require(row['comparison_distance_available']==proposal['distance_available']
                    and row['comparison_range_m']==proposal['horizontal_camera_foot_range_m']
                    and row['comparison_support_pixel']==proposal['support_pixel'] and row['reason']==proposal['reason'],
                    'comparison CPU geometry does not reproduce')
                if row['comparison_distance_available']:
                    comparison_numeric.append(dict(block=i,original_frame=job['frame'],range_m=row['comparison_range_m']))
            require(block['comparison_rows']==161 and block['comparison_numeric_rows']==sum(r['comparison_distance_available'] for r in comparisons)
                and block['comparison_reference_rows']==sum(r['reference_scope_verified'] for r in comparisons)
                and block['comparison_reason_counts']==dict(Counter(r['reason'] for r in comparisons)),
                'comparison aggregation mismatch')
            comparison_total+=len(comparisons)
        recomputed_blocks.append(dict(block,records=records))
    require(set(payload)==allowed,'unexpected archive file set')
    computed=replay.summarize(recomputed_blocks,warmup,30.,'actual_cuda')
    for key in ('groups','pairs','paired_samples','primary_changed_pairs','detector_changed_pairs','warmup_predict_ms',
                'primary_reproducibility','block_order'):
        require(computed[key]==summary[key],'headline differs from independent aggregation: '+key)
    counts=Counter((r['original_frame'],r['range_m']) for r in comparison_numeric)
    report=dict(schema='guarded_cuda_gpu_archive_audit_v1',state='pass',
        actual_cuda_execution_supported_by_submitted_logs=True,local_cuda_inference_started=False,
        actual_camera=False,physical_metric_verified=False,usable_for_ffb=False,
        submitted_gpu=summary['gpu'],runtime_versions=summary['runtime_versions'],
        source_hashes_local_rehashed=len(source_hashes),original_inputs_local_rehashed=25,
        weights_sha_matches_config=True,weights_file_supplied=False,
        primary_rows_checked=640,setup_rows_checked=4,warmup_rows_checked=8,
        primary_equal_pairs=computed['paired_samples']-computed['primary_changed_pairs'],
        primary_changed_pairs=computed['primary_changed_pairs'],detector_changed_pairs=computed['detector_changed_pairs'],
        distinct_input_detection_cases_recomputed_on_cpu=len(geometry_cache),
        comparison_rows_checked=comparison_total,comparison_numeric_rows=len(comparison_numeric),
        comparison_numeric_cases=[dict(original_frame=f,range_m=d,rows=n) for (f,d),n in counts.items()],
        both_pin_pixels_match_original=True,both_comparison_workers_closed=True,
        groups=computed['groups'],comparison_service_ms=replay.distribution([r['service_ms'] for r in comparison_performance]),
        comparison_age_ms=replay.distribution([r['age_ms'] for r in comparison_performance]),
        blocks=[{k:b[k] for k in ('id','comparison_enabled','measured_wall_sec','period_overruns',
            'comparison_rows','comparison_numeric_rows','comparison_reason_counts')} for b in summary['blocks']],
        performance_decision='30fps_not_met_with_comparison_ON_in_this_saved_image_sample',
        cause='not_isolated_CPU_thread_GIL_memory_contention_or_duplicate_work_are_hypotheses',
        summary_completion_is_NOT_a_30fps_or_live_latency_pass=True,remote_paths_opened=False)
    return report,sample_rows,comparison_performance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    require(not args.intake_dir.exists() and not args.output_dir.exists(),'new intake/output directories required')
    payload=archive_payload(args.archive)
    base=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01'
    data=replay.load_inputs(base/'driver_motion_live_20261110_171250',base/'motion_withheld_20261110_171250')
    report,primary,comparison=audit(payload,data)
    report.update(archive_sha256=replay.hash_regular(args.archive,64*1024*1024),
        audit_source_sha256=replay.hash_regular(Path(__file__),512*1024),
        supplied_files_sha256={name:replay.digest_bytes(blob) for name,blob in sorted(payload.items())})
    for name,blob in payload.items():
        path=args.intake_dir/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(blob)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    for filename,records in (('primary_timing.csv',primary),('comparison_timing.csv',comparison)):
        with (args.output_dir/filename).open('x',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    print(json.dumps({k:report[k] for k in ('state','primary_rows_checked','primary_equal_pairs',
        'comparison_rows_checked','comparison_numeric_rows','performance_decision')},indent=2))


if __name__=='__main__':main()
