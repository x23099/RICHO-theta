"""CPU-only saved-pixel correctness and ABBA profile; never starts CUDA."""
import argparse
import copy
import cProfile
import csv
import hashlib
import json
from pathlib import Path
import pstats
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from compute import evaluate_offline_frame
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_replay_r01'))
import cuda_replay as replay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=8)
    args=parser.parse_args()
    if not 1<=args.cycles<=32:raise ValueError('bounded cycles required')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    base=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01'
    data=replay.load_inputs(base/'driver_motion_live_20261110_171250',base/'motion_withheld_20261110_171250')
    incoming=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r01'
    rows=[replay.parse_json(line) for line in (incoming/'block_00_off/primary_frames.jsonl').read_bytes().splitlines()]
    cases=[]
    for job,row in zip(data['jobs'],rows[:8]):
        ref=copy.deepcopy(data['reference']);ref['session']=row['session']
        # Explicit offline binding to identical historical pixels, NOT a live reference.
        frame=replay.NativeFrame(row['session'],row['frame'],row['media_time_sec'],row['source_time_sec'],job['image'])
        cases.append((frame,row['raw_detector_boxes'],row,ref))
    def run_case(case,shared):
        frame,boxes,row,ref=case
        return evaluate_offline_frame(frame,boxes,row,data,ref,completed_at=row['completed_time_sec']+.001,
            shared=shared,offline_only=True)
    unchanged=[replay.signature(case[2]) for case in cases]
    def stable(result):
        return {k:result[k] for k in ('baseline','proposal','body_review_reason','lower_half_pixel_eligible',
            'offline_compute_only','reference_lifecycle_verified','live_authorized',*replay.FLAGS)}
    correctness=[]
    for i,case in enumerate(cases):
        before,after=run_case(case,False),run_case(case,True)
        if stable(before)!=stable(after):raise ValueError('legacy/shared computation differs')
        correctness.append(dict(original_frame=data['jobs'][i]['frame'],equal=True,
            proposal_available=after['proposal']['distance_available'],
            proposal_range_m=after['proposal']['horizontal_camera_foot_range_m'],
            reason=after['proposal']['reason']))
    print('Eight cases equal; profiling old CPU compute first, then shared compute.',flush=True)
    profiles={}
    for shared,label in ((False,'legacy'),(True,'shared')):
        profiler=cProfile.Profile();profiler.enable()
        for case in cases:run_case(case,shared)
        profiler.disable();stats=pstats.Stats(profiler)
        functions=[]
        for (filename,line,name),(primitive,total,own,cumulative,callers) in stats.stats.items():
            functions.append(dict(file=filename,line=line,function=name,primitive_calls=primitive,calls=total,
                own_sec=own,cumulative_sec=cumulative))
        functions.sort(key=lambda item:item['cumulative_sec'],reverse=True)
        profiles[label]=dict(total_sec=stats.total_tt,functions=functions,
            upper_observer_calls=sum(item['calls'] for item in functions if item['function']=='observe_upper_completion'))
    blocks=[];timing=[]
    for block_id,shared in enumerate((False,True,True,False)):
        for case in cases:run_case(case,shared)  # Per-block warmup excluded.
        measurements=[]
        for n in range(args.cycles*8):
            started=time.perf_counter();result=run_case(cases[n%8],shared)
            elapsed=1000*(time.perf_counter()-started);measurements.append(elapsed)
            timing.append(dict(block=block_id,shared=shared,ordinal=n,original_frame=data['jobs'][n%8]['frame'],wall_ms=elapsed))
        blocks.append(dict(id=block_id,shared=shared,wall_ms=replay.distribution(measurements)))
        print(f'CPU block {block_id+1}/4 shared={shared}: P50 {blocks[-1]["wall_ms"]["p50"]:.2f} ms',flush=True)
    if unchanged!=[replay.signature(case[2]) for case in cases]:raise ValueError('original result changed')
    if any(replay.digest_bytes(job['image'].tobytes())!=job['pixel_sha256'] for job in data['jobs']):
        raise ValueError('original pixels changed')
    for name,digest in data['input_sha256'].items():
        if replay.hash_regular(Path(name),512*1024*1024)!=digest:raise ValueError('original input file changed')
    grouped={label:replay.distribution([r['wall_ms'] for r in timing if r['shared'] is shared])
        for label,shared in (('legacy',False),('shared',True))}
    report=dict(schema='offline_guarded_compute_reuse_profile_v1',state='pass',cpu_only=True,
        correctness=correctness,profiles=profiles,blocks=blocks,groups=grouped,
        shared_vs_legacy_p50_ratio=grouped['shared']['p50']/grouped['legacy']['p50'],
        cycles=args.cycles,block_order=['legacy','shared','shared','legacy'],
        all_original_inputs_unchanged=True,input_sha256=data['input_sha256'],
        incoming_primary_sha256=replay.hash_regular(incoming/'block_00_off/primary_frames.jsonl',16*1024*1024),
        source_sha256={str(p.relative_to(ROOT)):replay.hash_regular(p,512*1024) for p in
            (Path(__file__),Path(__file__).with_name('compute.py'))},
        camera_started=False,cuda_started=False,runtime_modified=False,gpu_performance_verified=False,
        reference_lifecycle_verified=False,physical_metric_verified=False,usable_for_ffb=False)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    with (args.output_dir/'timing.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(timing[0]));writer.writeheader();writer.writerows(timing)
    print(json.dumps(dict(state=report['state'],groups=grouped,
        upper_observer_calls={label:p['upper_observer_calls'] for label,p in profiles.items()}),indent=2))


if __name__=='__main__':main()
