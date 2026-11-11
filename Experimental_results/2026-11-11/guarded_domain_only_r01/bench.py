"""Exact validity-only vs inverse-ray reference, offline CPU ABBA benchmark."""
import argparse
from contextlib import ExitStack, contextmanager
import copy
import cProfile
import csv
import json
from pathlib import Path
import pstats
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01'))
from compute import evaluate_offline_frame
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_replay_r01'))
import cuda_replay as replay
from angular_fisheye_geometry import unproject

ALIASES=('cone_distance_core','cone_colour_support_candidate',
    'cone_support_completion_candidate','cone_upper_support_candidate')
SOURCES=('angular_fisheye_geometry.py',*[name+'.py' for name in ALIASES])


def inverse_reference(pixels,camera,*,image_size):
    return unproject(pixels,camera,image_size=image_size)[1]


@contextmanager
def mode(domain_only):
    # One isolated offline process; no runtime/thread/global deployment mutation.
    with ExitStack() as stack:
        if not domain_only:
            for module in ALIASES:
                stack.enter_context(patch(module+'.pixels_in_domain',inverse_reference))
        yield


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=8)
    args=parser.parse_args()
    if not 1<=args.cycles<=32:raise ValueError('bounded cycles required')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    base=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01'
    data=replay.load_inputs(base/'driver_motion_live_20261110_171250',base/'motion_withheld_20261110_171250')
    source=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r03/block_00_off/primary_frames.jsonl'
    rows=[replay.parse_json(line) for line in source.read_bytes().splitlines()]
    cases=[]
    for job,row in zip(data['jobs'],rows[:8]):
        ref=copy.deepcopy(data['reference']);ref['session']=row['session']
        frame=replay.NativeFrame(row['session'],row['frame'],row['media_time_sec'],row['source_time_sec'],job['image'])
        cases.append((frame,row['raw_detector_boxes'],row,ref))
    if len(cases)!=8:raise ValueError('exactly eight native input cases required')
    def run(case):
        frame,boxes,original,ref=case
        return evaluate_offline_frame(frame,boxes,original,data,ref,completed_at=original['completed_time_sec']+.001,
            shared=True,offline_only=True,compact=True)
    paths=[Path(__file__),ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01/compute.py',
        *[ROOT/'src'/name for name in SOURCES]]
    hashes={str(p.relative_to(ROOT)):replay.hash_regular(p,512*1024) for p in paths}
    originals=[copy.deepcopy(case[2]) for case in cases];checks=[]
    for n,case in enumerate(cases):
        with mode(False):reference=run(case)
        with mode(True):candidate=run(case)
        if reference!=candidate:raise ValueError('inverse-reference/domain-only complete result mismatch')
        checks.append(dict(original_frame=data['jobs'][n]['frame'],equal=True,
            available=candidate['proposal']['distance_available'],range_m=candidate['proposal']['horizontal_camera_foot_range_m'],
            reason=candidate['proposal']['reason']))
    print('All eight complete results equal; isolated CPU profiling, no CUDA.',flush=True)
    profiles={}
    for label,domain_only in (('inverse_reference',False),('domain_only',True)):
        with mode(domain_only):
            profiler=cProfile.Profile();profiler.enable()
            for case in cases:run(case)
            profiler.disable()
        stats=pstats.Stats(profiler);functions=[]
        for (filename,line,name),(primitive,total,own,cumulative,_) in stats.stats.items():
            functions.append(dict(file=filename,line=line,function=name,primitive_calls=primitive,calls=total,
                own_sec=own,cumulative_sec=cumulative))
        functions.sort(key=lambda row:row['cumulative_sec'],reverse=True)
        profiles[label]=dict(total_sec=stats.total_tt,functions=functions,
            unproject_calls=sum(row['calls'] for row in functions if row['function']=='unproject'),
            radial_calls=sum(row['calls'] for row in functions if row['function']=='radial'))
    timings=[];blocks=[]
    for block,domain_only in enumerate((False,True,True,False)):
        with mode(domain_only):
            for case in cases:run(case)
            for n in range(args.cycles*8):
                start=time.perf_counter();run(cases[n%8]);elapsed=1000*(time.perf_counter()-start)
                timings.append(dict(block=block,domain_only=domain_only,ordinal=n,
                    original_frame=data['jobs'][n%8]['frame'],wall_ms=elapsed))
        values=[r['wall_ms'] for r in timings if r['block']==block]
        blocks.append(dict(block=block,domain_only=domain_only,wall_ms=replay.distribution(values)))
        print(f'CPU block {block+1}/4 domain_only={domain_only}: P50={blocks[-1]["wall_ms"]["p50"]:.2f} ms',flush=True)
    if originals!=[case[2] for case in cases]:raise ValueError('original main result changed')
    if any(replay.digest_bytes(job['image'].tobytes())!=job['pixel_sha256'] for job in data['jobs']):
        raise ValueError('original pixels changed')
    for name,digest in data['input_sha256'].items():
        if replay.hash_regular(Path(name),512*1024*1024)!=digest:raise ValueError('original input changed')
    if any(replay.hash_regular(ROOT/name,512*1024)!=digest for name,digest in hashes.items()):
        raise ValueError('benchmark source changed')
    groups={label:replay.distribution([row['wall_ms'] for row in timings if row['domain_only'] is domain_only])
        for label,domain_only in (('inverse_reference',False),('domain_only',True))}
    summary=dict(state='pass',cpu_only=True,correctness=checks,groups=groups,blocks=blocks,profiles=profiles,
        domain_vs_reference_p50_ratio=groups['domain_only']['p50']/groups['inverse_reference']['p50'],
        cycles=args.cycles,block_order=['inverse_reference','domain_only','domain_only','inverse_reference'],
        reference_method='identical unproject(...)[1] via four aliases in isolated offline process',
        source_sha256=hashes,input_sha256=data['input_sha256'],
        submitted_primary_sha256=replay.hash_regular(source,16*1024*1024),
        all_original_inputs_unchanged=True,cuda_started=False,camera_started=False,
        GPU_performance_verified=False,live_latency_verified=False,physical_metric_verified=False)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (args.output_dir/'timing.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(timings[0]));writer.writeheader();writer.writerows(timings)
    print(json.dumps(dict(state='pass',groups=groups,
        inverse_calls={k:v['unproject_calls'] for k,v in profiles.items()},
        radial_calls={k:v['radial_calls'] for k,v in profiles.items()}),indent=2))


if __name__=='__main__':main()
