"""Audit supplied GPU replay archive; never open recorded remote paths.

Primary logs are independently checked. Comparison rows/PNG were NOT supplied;
their reported result is checked for consistency, not called independently read.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from driver_motion_protocol import compact_result

VOLATILE={'session','frame','media_time_sec','source_time_sec','completed_time_sec',
          'frame_age_ms','predict_ms','support_geometry_ms'}
FRAMES=[6861,14203,14267,14297,14329,14382,14604,14922]


def sha(data):return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def normalized_inputs(values,source,evidence,repo):
    roots=[(PurePosixPath(source),'primary'),(PurePosixPath(evidence),'evidence'),
           (PurePosixPath(repo)/'src','implementation'),
           (PurePosixPath(repo)/'Experimental_results/2026-11-10/self_body_boundary_shadow_r01','reference')]
    out={}
    for name,digest in values.items():
        path=PurePosixPath(name)
        assert path.is_absolute() and '..' not in path.parts,name
        choices=[(role,path.relative_to(base)) for base,role in roots if path.is_relative_to(base)]
        assert len(choices)==1,name
        role,relative=choices[0]
        assert len(relative.parts)==1,name
        key=role+'/'+str(relative)
        assert key not in out,key
        out[key]=digest
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    prefix='guarded_gpu_cached_r01'
    files={'summary.json','off_manifest.json','on_manifest.json'}
    parts=('motion_worker_stderr.log','motion_bridge_events.jsonl','motion_engine_summary.json',
           'motion_profile_used.json','motion_distance_frames.jsonl','driver_motion_summary.json')
    files|={trial+'/'+name for trial in ('off','on') for name in parts}
    payload={}
    with tarfile.open(args.archive,'r:xz') as archive:
        members=archive.getmembers()
        assert len(members)==len(files)+3
        expected={prefix,prefix+'/off',prefix+'/on'}|{prefix+'/'+name for name in files}
        assert {member.name.rstrip('/') for member in members}==expected
        assert sum(member.size for member in members)<=2*1024*1024
        for member in members:
            assert not member.issym() and not member.islnk()
            if member.name.rstrip('/') in (prefix,prefix+'/off',prefix+'/on'):
                assert member.isdir()
            else:
                assert member.isfile() and 0<=member.size<=1024*1024
                name=str(PurePosixPath(member.name).relative_to(prefix))
                payload[name]=archive.extractfile(member).read()
    j=lambda name:json.loads(payload[name])
    submitted=j('summary.json')
    local_dir=ROOT/'Experimental_results/2026-11-11/guarded_async_comparison_r01/pipe_replay_r02'
    local=json.loads((local_dir/'summary.json').read_bytes())
    headline=('schema','state','primary_off_on_equal_images','primary_results_match_original_images',
        'comparison_numeric_rows','comparison_range_m','reference_before_activation_numeric_rows',
        'future_reference_rows_used','bad_session_load_rejected','snapshots_saved',
        'all_original_inputs_unchanged','actual_camera','actual_cuda_inference','actual_vehicle_operation',
        'live_latency_verified','physical_metric_verified','usable_for_ffb','evidence_verification')
    assert all(submitted[key]==local[key] for key in headline)
    assert submitted['state']=='pass'
    assert submitted['source_sha256']==local['source_sha256']
    assert submitted['comparison_final_status']['source_sha256']==local['comparison_final_status']['source_sha256']
    sources={**submitted['source_sha256'],**{'src/'+name:digest for name,digest in
        submitted['comparison_final_status']['source_sha256'].items()}}
    for name,digest in sources.items():
        path=ROOT/name
        assert path.resolve().is_relative_to(ROOT) and file_sha(path)==digest,name
    remote_repo='/home/hsr/yopi_ws/RICHO-theta'
    remote_source=remote_repo+'/Experimental_results/2026-11-10/driver_motion_live_20261110_171250'
    remote_evidence=remote_repo+'/recordings/2026-11-10/motion_withheld_20261110_171250'
    local_base=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01'
    local_inputs=normalized_inputs(local['input_sha256'],str(local_base/'driver_motion_live_20261110_171250'),
        str(local_base/'motion_withheld_20261110_171250'),str(ROOT))
    remote_inputs=normalized_inputs(submitted['input_sha256'],remote_source,remote_evidence,remote_repo)
    assert local_inputs==remote_inputs
    for name,digest in local['input_sha256'].items():
        path=Path(name);assert path.resolve().is_relative_to(ROOT) and file_sha(path)==digest,name
    canonical=lambda row:{key:value for key,value in row.items() if key not in VOLATILE}
    primary={};sessions={};checks=[]
    for enabled,label in ((False,'off'),(True,'on')):
        rows=[json.loads(line) for line in payload[label+'/motion_distance_frames.jsonl'].splitlines()]
        baseline=[json.loads(line) for line in (local_dir/label/'motion_distance_frames.jsonl').read_bytes().splitlines()]
        assert len(rows)==8 and [row['frame'] for row in rows]==list(range(1,9))
        assert len({row['session'] for row in rows})==1
        session=rows[0]['session'];assert re.fullmatch('[0-9a-f]{32}',session)
        sessions[label]=session
        for i,(row,old) in enumerate(zip(rows,baseline)):
            assert canonical(row)==canonical(old),(label,i)
            assert all(type(row[key]) in (int,float) and math.isfinite(row[key]) for key in
                       ('source_time_sec','completed_time_sec','media_time_sec','frame_age_ms'))
            assert 0<=row['completed_time_sec']-row['source_time_sec']<=.5
            assert abs(row['frame_age_ms']-1000*(row['completed_time_sec']-row['source_time_sec']))<1e-7
            if i:assert row['source_time_sec']>rows[i-1]['source_time_sec']
            checks.append(dict(trial=label,replay_frame=row['frame'],original_frame=FRAMES[i],
                baseline_geometry_and_flags_equal=True,primary_distance_available=row['distance_available'],
                primary_reason=row['reason']))
        events=[json.loads(line) for line in payload[label+'/motion_bridge_events.jsonl'].splitlines()]
        assert len(events)==8
        for event,row in zip(events,rows):
            assert event['accepted_current_session_and_age'] is True
            assert event['result']==compact_result(row)
        run=submitted['runs'][int(enabled)]
        assert run['enabled'] is enabled and len(run['primary_rows'])==8
        for i,(claim,row) in enumerate(zip(run['primary_rows'],rows)):
            assert claim['replay_session']==session and claim['replay_frame']==row['frame']
            assert claim['original_frame']==FRAMES[i] and claim['original_session']=='4c34c8c3d6d44949afb2e921e819e563'
            assert claim['baseline_equal'] is True and claim['primary_reason']==row['reason']
            assert claim['primary_range_m']==row['horizontal_camera_foot_range_m']
        shutdown=j(label+'/driver_motion_summary.json')
        assert run['shutdown']==shutdown
        assert shutdown['sent']==shutdown['returned']==8 and shutdown['retired_results']==0
        assert shutdown['shutdown_complete'] and shutdown['child_stopped'] and shutdown['io_thread_stopped']
        assert shutdown['worker_error'] is None and shutdown['shutdown_error'] is None
        assert not shutdown['forced_worker_kill'] and shutdown['guarded_comparison_requested'] is enabled
        assert shutdown['child_exitcode']==(0 if enabled else -15)
        assert payload[label+'/motion_worker_stderr.log']==b''
        profile=payload[label+'/motion_profile_used.json']
        assert sha(profile)==local_inputs['primary/motion_profile_used.json']
        engine=j(label+'/motion_engine_summary.json')
        assert engine['gpu']=={'name':'offline replay NOT CUDA'}
        assert engine['profile_sha256']==sha(profile)
        assert engine['config_sha256']==local_inputs['implementation/cone_distance_diagnostic_config.json']
        assert engine['guarded_comparison']['requested'] is enabled
        assert engine['guarded_comparison']['worker_started'] is enabled
        manifest=j(label+'_manifest.json')
        local_manifest=json.loads((local_dir/(label+'_manifest.json')).read_bytes())
        assert manifest['boxes']==local_manifest['boxes']
        primary[label]=rows
    assert sessions['off']!=sessions['on']
    assert [canonical(row) for row in primary['off']]==[canonical(row) for row in primary['on']]
    final=submitted['comparison_final_status'];pin=final['pin']
    assert final['state']=='closed' and final['writer_done'] and final['shutdown_complete']
    assert final['error'] is None and final['latest'] is None
    assert final['offered']==final['processed']==8 and final['snapshots_saved']==1
    assert final['request_count']==3 and final['latest_slot_overwrites']==final['tap_busy_drops']==0
    assert pin['session']==sessions['on'] and pin['frame']==7
    actual_line=payload['on/motion_distance_frames.jsonl'].splitlines(keepends=True)[6]
    assert pin['source_log_line_sha256']==sha(actual_line)
    assert pin['source_time_sec']==primary['on'][6]['source_time_sec']
    assert pin['png_sha256']==local['comparison_final_status']['pin']['png_sha256']
    assert pin['decoded_bgr_sha256']==local['comparison_final_status']['pin']['decoded_bgr_sha256']
    assert 'FileNotFoundError' in final['detail'] and 'decoded_'+('f'*32)+'_f000007.png' in final['detail']
    report=dict(schema='guarded_gpu_cached_archive_audit_v1',state='pass',archive_sha256=file_sha(args.archive),
        audit_source_sha256=file_sha(Path(__file__)),archive_regular_files=len(payload),
        supplied_files_sha256={name:sha(data) for name,data in sorted(payload.items())},
        primary_off_on_equal_images=8,primary_rows_independently_checked=16,bridge_events_checked=16,
        source_files_recorded_hashes_matched_and_local_rehashed=len(sources),
        original_inputs_recorded_hashes_matched_and_local_rehashed=len(local_inputs),
        main_geometry_and_flags_equal_to_local=True,primary_rows=checks,
        both_child_and_io_shutdown_complete=True,comparison_writer_reported_complete=True,
        comparison_numeric_rows_reported=1,comparison_range_m_reported=submitted['comparison_range_m'],
        comparison_rows_and_pin_png_supplied=False,comparison_rows_independently_read=False,
        comparison_report_consistent_with_verified_source=True,expected_bad_session_error=True,
        pin_source_log_line_sha256_matched=True,remote_files_opened=False,
        actual_camera=False,actual_cuda_inference=False,physical_metric_verified=False,usable_for_ffb=False)
    assert not args.intake_dir.exists() and not args.output_dir.exists()
    for name,data in payload.items():
        path=args.intake_dir/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('state','archive_regular_files',
        'primary_off_on_equal_images','primary_rows_independently_checked','bridge_events_checked',
        'source_files_recorded_hashes_matched_and_local_rehashed',
        'original_inputs_recorded_hashes_matched_and_local_rehashed','comparison_range_m_reported')},indent=2))


if __name__=='__main__':main()
