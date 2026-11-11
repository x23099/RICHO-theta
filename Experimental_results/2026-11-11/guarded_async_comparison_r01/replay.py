"""Real local child/pipe/async worker, historical native pixels + saved boxes.

Explicit verifier mode ONLY substitutes YOLO. No camera, CUDA, RTC, ROS or
vehicle operation. Replay identities are new, never evidence of a new mount.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cached_worker(manifest):
    import cone_distance_worker
    from driver_motion_process import main
    spec=json.loads(manifest.read_text())
    class CachedPredictor:
        inference_source='saved_same_frame_boxes_NOT_new_YOLO_NOT_GPU'
        def __init__(self,*args):
            self.weights_sha256='verifier_saved_boxes_NOT_live_weights'
            self.gpu=dict(name='offline replay NOT CUDA')
        def __call__(self,frame):
            return spec['boxes'][hashlib.sha256(frame.image.tobytes()).hexdigest()]
    cone_distance_worker.YoloConePredictor=CachedPredictor
    args=['--weights',str(manifest),'--profile',spec['profile'],'--output-dir',spec['output'],
          '--experimental-rigid-mount','--target-roi','270','0','350','720']
    if spec['comparison'] is not None:
        args.extend(['--comparison-dir',spec['comparison']])
    return main(args)


def wait(predicate,bridge,timeout=8.):
    deadline=time.monotonic()+timeout
    while not predicate():
        if bridge.error:
            raise RuntimeError(bridge.error)
        if time.monotonic()>=deadline:
            raise TimeoutError('bounded replay wait expired; inspect worker stderr/status')
        time.sleep(.005)


def run(args):
    import cv2
    from cone_distance_core import DEFAULT_CONFIG
    from driver_motion_bridge import DriverMotionBridge
    from driver_motion_protocol import PROFILE
    from driver_guarded_comparison import comparison_path
    from manage_guarded_comparison import issue
    from verify_driver_withheld_evidence import verify,read_regular,parse_json
    source,evidence,output=(p.resolve() for p in (args.input_dir,args.evidence_dir,args.output_dir))
    comparison=comparison_path(args.comparison_dir)
    if output.exists():
        raise ValueError('new replay output required')
    verification=verify(evidence,source/'motion_distance_frames.jsonl')
    assert verification['verified_pairs']==8 and verification['capture_shutdown_complete']
    index=[parse_json(line) for line in read_regular(evidence/'evidence_index.jsonl',256*1024).splitlines()]
    index.sort(key=lambda item:item['frame'])
    assert [item['frame'] for item in index]==[6861,14203,14267,14297,14329,14382,14604,14922]
    profile=source/'motion_profile_used.json'
    prior=ROOT/'Experimental_results/2026-11-10/self_body_boundary_shadow_r01/reference.json'
    original_ref=parse_json(read_regular(prior,32768))
    inputs={str(path):digest(path) for path in (source/'motion_distance_frames.jsonl',profile,
        source/'motion_engine_summary.json',evidence/'evidence_index.jsonl',evidence/'evidence_status.json',
        prior,DEFAULT_CONFIG)}
    metadata=parse_json(read_regular(source/'motion_engine_summary.json',256*1024))
    assert metadata['config_sha256']==digest(DEFAULT_CONFIG)
    assert metadata['profile_sha256']==digest(profile)
    jobs,boxes=[],{}
    for entry in index:
        png_path,meta_path=evidence/entry['image_file'],evidence/entry['sidecar_file']
        inputs[str(png_path)],inputs[str(meta_path)]=digest(png_path),digest(meta_path)
        assert inputs[str(png_path)]==entry['png_sha256'] and inputs[str(meta_path)]==entry['sidecar_sha256']
        meta=parse_json(read_regular(meta_path,1024*1024+16384))
        image=cv2.imread(str(png_path));image.flags.writeable=False
        sha=hashlib.sha256(image.tobytes()).hexdigest()
        assert sha==meta['decoded_bgr_sha256']
        boxes[sha]=meta['measurement']['selected_detector_boxes']
        jobs.append((image,meta['measurement']))
    output.mkdir(parents=True)
    run_results=[]
    for enabled in (False,True):
        label='on' if enabled else 'off'
        manifest=output/(label+'_manifest.json')
        child_dir=output/label
        manifest.write_text(json.dumps(dict(profile=str(profile),boxes=boxes,output=str(child_dir),
            comparison=str(comparison) if enabled else None),indent=2)+'\n')
        bridge=DriverMotionBridge([sys.executable,'-u',str(Path(__file__).resolve()),
            '--cached-worker','--manifest',str(manifest)],child_dir,
            comparison_dir=comparison if enabled else None)
        def comparison_status():
            return parse_json(read_regular(comparison/'comparison_status.json',16384))
        def comparisons():
            path=comparison/'comparison_frames.jsonl'
            if not path.exists():return []
            data=path.read_bytes()
            if data and not data.endswith(b'\n'):return []
            return [parse_json(line) for line in data.splitlines()]
        rows=[]
        try:
            bridge.start();wait(lambda:bridge.ready.is_set(),bridge)
            replay_session=uuid.uuid4().hex
            bridge.begin(replay_session,dict(PROFILE))
            if enabled:wait(lambda:(comparison/'comparison_status.json').exists(),bridge)
            last_publish=0.
            for sequence,(image,original) in enumerate(jobs,1):
                if enabled and original['frame']==original_ref['source_frame']:
                    issue(comparison,'pin')
                    wait(lambda:comparison_status()['state']=='pin_pending',bridge)
                wait(lambda:time.monotonic()-last_publish>=.075,bridge)
                before=bridge.returned;last_publish=time.monotonic()
                assert bridge.publish(replay_session,image,sequence/30.,last_publish)
                wait(lambda:bridge.returned>before,bridge)
                value=bridge.snapshot().get('result')
                assert value is not None
                for field in ('distance_available','horizontal_camera_foot_range_m','reason','primary_model'):
                    assert value[field]==original[field],(enabled,sequence,field)
                rows.append(dict(original_session=original['session'],original_frame=original['frame'],
                    replay_session=replay_session,replay_frame=sequence,baseline_equal=True,
                    primary_range_m=value['horizontal_camera_foot_range_m'],primary_reason=value['reason']))
                if enabled:
                    wait(lambda:any(row['frame']==sequence for row in comparisons()),bridge)
                    if original['frame']==original_ref['source_frame']:
                        pin=comparison_status()['pin']
                        assert pin['session']==replay_session and pin['frame']==sequence
                        pinned=cv2.imread(str(comparison/pin['image_file']))
                        assert hashlib.sha256(pinned.tobytes()).hexdigest()==hashlib.sha256(image.tobytes()).hexdigest()
                        # Replay-only NEW reference from byte-identical original pixels.
                        # This is NOT authorizing old geometry for a new real session.
                        ref=copy.deepcopy(original_ref)
                        ref.update(session=replay_session,source_frame=sequence,
                            source_png_sha256=pin['png_sha256'],offline_replay_binding_NOT_live_mount_evidence=True)
                        (comparison/'reference.json').write_text(json.dumps(ref)+'\n')
                        issue(comparison,'load')
                        wait(lambda:comparison_status()['state'] in ('active','load_rejected'),bridge)
                        assert comparison_status()['state']=='active',comparison_status()
            if enabled:
                compared=comparisons()
                assert len(compared)==8 and sum(row['comparison_distance_available'] for row in compared)==1
                assert compared[-1]['comparison_support_pixel']==[312,407]
                assert compared[-1]['comparison_range_m']==1.142471541888944
                assert all(not row['reference_used_posthoc'] for row in compared)
                # Bad-session load; no more images are needed for this failure probe.
                bad=copy.deepcopy(ref);bad['session']='f'*32
                (comparison/'reference.json').write_text(json.dumps(bad)+'\n')
                issue(comparison,'load')
                wait(lambda:comparison_status()['state']=='load_rejected',bridge)
                assert comparison_status()['latest'] is None
        finally:
            shutdown=bridge.close()
        assert shutdown['shutdown_complete'] and not shutdown['worker_error'],shutdown
        if enabled:
            final=comparison_status()
            assert final['writer_done'] and final['shutdown_complete'],final
            assert final['snapshots_saved']==1
        run_results.append(dict(enabled=enabled,primary_rows=rows,shutdown=shutdown))
    assert [r['primary_reason'] for r in run_results[0]['primary_rows']]==[r['primary_reason'] for r in run_results[1]['primary_rows']]
    for name,sha in inputs.items():assert digest(Path(name))==sha,name
    sources=[Path(__file__),*[ROOT/'src'/name for name in ('driver_guarded_comparison.py',
        'manage_guarded_comparison.py','cone_guarded_stream_comparison.py','driver_motion_bridge.py',
        'driver_motion_process.py','driver_motion_protocol.py')]]
    summary=dict(schema='guarded_async_pipe_replay_v1',state='pass',
        primary_off_on_equal_images=8,primary_results_match_original_images=8,
        comparison_numeric_rows=1,comparison_range_m=1.142471541888944,
        reference_before_activation_numeric_rows=0,future_reference_rows_used=0,
        bad_session_load_rejected=True,snapshots_saved=1,all_original_inputs_unchanged=True,
        actual_camera=False,actual_cuda_inference=False,actual_vehicle_operation=False,
        live_latency_verified=False,physical_metric_verified=False,usable_for_ffb=False,
        evidence_verification=verification,comparison_final_status=final,runs=run_results,
        input_sha256=inputs,source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sources})
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({key:summary[key] for key in ('state','primary_off_on_equal_images',
        'comparison_numeric_rows','comparison_range_m','bad_session_load_rejected')},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path)
    parser.add_argument('--evidence-dir',type=Path)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--comparison-dir',type=Path)
    parser.add_argument('--cached-worker',action='store_true')
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    if args.cached_worker:
        if args.manifest is None:raise ValueError('explicit verifier manifest required')
        raise SystemExit(cached_worker(args.manifest))
    if any(getattr(args,key) is None for key in ('input_dir','evidence_dir','output_dir','comparison_dir')):
        raise ValueError('explicit source/evidence/new output/new comparison directories required')
    run(args)


if __name__=='__main__':
    main()
