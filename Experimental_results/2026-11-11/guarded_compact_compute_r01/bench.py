"""CPU full/compact comparison kernel ABBA benchmark; no CUDA/model/device."""
import argparse
import copy
import cProfile
import csv
import json
from pathlib import Path
import pstats
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01'))
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
    source=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r02/block_00_off/primary_frames.jsonl'
    rows=[replay.parse_json(line) for line in source.read_bytes().splitlines()]
    cases=[]
    for job,row in zip(data['jobs'],rows[:8]):
        ref=copy.deepcopy(data['reference']);ref['session']=row['session']
        frame=replay.NativeFrame(row['session'],row['frame'],row['media_time_sec'],row['source_time_sec'],job['image'])
        cases.append((frame,row['raw_detector_boxes'],row,ref))
    def run(case,compact):
        frame,boxes,original,ref=case
        return evaluate_offline_frame(frame,boxes,original,data,ref,completed_at=original['completed_time_sec']+.001,
            shared=True,offline_only=True,compact=compact)
    paths=[Path(__file__),ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01/compute.py',
        *[ROOT/'src'/name for name in ('cone_guarded_lower_edge_shadow.py','cone_bbox_boundary_shadow.py',
            'cone_self_body_shadow.py','cone_motion_range.py')]]
    hashes={str(p.relative_to(ROOT)):replay.hash_regular(p,512*1024) for p in paths}
    originals=[replay.signature(case[2]) for case in cases];checks=[]
    for n,case in enumerate(cases):
        full,compact=run(case,False),run(case,True)
        if full!=compact:raise ValueError('full/compact result mismatch')
        checks.append(dict(original_frame=data['jobs'][n]['frame'],equal=True,
            available=compact['proposal']['distance_available'],range_m=compact['proposal']['horizontal_camera_foot_range_m'],
            reason=compact['proposal']['reason']))
    print('All eight saved cases equal; CPU profiling (no CUDA).',flush=True)
    profiles={}
    for label,compact in (('full',False),('compact',True)):
        profiler=cProfile.Profile();profiler.enable()
        for case in cases:run(case,compact)
        profiler.disable();stats=pstats.Stats(profiler);functions=[]
        for (filename,line,name),(primitive,total,own,cumulative,_) in stats.stats.items():
            functions.append(dict(file=filename,line=line,function=name,primitive_calls=primitive,calls=total,
                own_sec=own,cumulative_sec=cumulative))
        functions.sort(key=lambda row:row['cumulative_sec'],reverse=True)
        profiles[label]=dict(total_sec=stats.total_tt,functions=functions,
            deepcopy_calls=sum(row['calls'] for row in functions if row['function']=='deepcopy'),
            upper_observer_calls=sum(row['calls'] for row in functions if row['function']=='observe_upper_completion'))
    timings=[];blocks=[]
    for block,compact in enumerate((False,True,True,False)):
        for case in cases:run(case,compact)
        for n in range(args.cycles*8):
            start=time.perf_counter();run(cases[n%8],compact);elapsed=1000*(time.perf_counter()-start)
            timings.append(dict(block=block,compact=compact,ordinal=n,original_frame=data['jobs'][n%8]['frame'],wall_ms=elapsed))
        values=[r['wall_ms'] for r in timings if r['block']==block]
        blocks.append(dict(block=block,compact=compact,wall_ms=replay.distribution(values)))
        print(f'CPU block {block+1}/4 compact={compact}: P50={blocks[-1]["wall_ms"]["p50"]:.2f} ms',flush=True)
    if originals!=[replay.signature(case[2]) for case in cases]:raise ValueError('original main result changed')
    if any(replay.digest_bytes(job['image'].tobytes())!=job['pixel_sha256'] for job in data['jobs']):
        raise ValueError('original pixels changed')
    for name,digest in data['input_sha256'].items():
        if replay.hash_regular(Path(name),512*1024*1024)!=digest:raise ValueError('original input changed')
    if any(replay.hash_regular(ROOT/name,512*1024)!=digest for name,digest in hashes.items()):
        raise ValueError('benchmark source changed')
    groups={label:replay.distribution([row['wall_ms'] for row in timings if row['compact'] is compact])
        for label,compact in (('full',False),('compact',True))}
    summary=dict(state='pass',cpu_only=True,correctness=checks,groups=groups,blocks=blocks,profiles=profiles,
        compact_vs_full_p50_ratio=groups['compact']['p50']/groups['full']['p50'],
        cycles=args.cycles,block_order=['full','compact','compact','full'],source_sha256=hashes,
        input_sha256=data['input_sha256'],submitted_primary_sha256=replay.hash_regular(source,16*1024*1024),
        all_original_inputs_unchanged=True,cuda_started=False,camera_started=False,
        GPU_performance_verified=False,live_latency_verified=False,physical_metric_verified=False)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (args.output_dir/'timing.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(timings[0]));writer.writeheader();writer.writerows(timings)
    print(json.dumps(dict(state='pass',groups=groups,deepcopy_calls={k:v['deepcopy_calls'] for k,v in profiles.items()}),indent=2))


if __name__=='__main__':main()
