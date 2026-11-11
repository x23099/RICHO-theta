"""New runtime versus submitted CUDA results, synthetic clock; NOT performance."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_cuda_replay_r01'))
import cuda_replay as replay
from cone_guarded_stream_comparison import GuardedStreamComparison


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--input-dir',type=Path,default=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r01')
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    base=ROOT/'recordings/2026-11-10/driver_motion_171250_intake_r01'
    data=replay.load_inputs(base/'driver_motion_live_20261110_171250',base/'motion_withheld_20261110_171250')
    incoming=args.input_dir.resolve()
    fields=('session','frame','source_time_sec','original_distance_available','original_range_m',
        'comparison_distance_available','comparison_range_m','comparison_support_pixel','reason',
        'baseline_reproduced','reference_generation','reference_frame','reference_scope_verified',
        'reference_used_posthoc','main_display_modified','body_review_reason','lower_half_pixel_eligible',*replay.FLAGS)
    checks=[];inputs={}
    for block_id in (1,2):
        folder=incoming/f'block_{block_id:02d}_on'
        names=['primary_frames.jsonl','setup.jsonl','comparison/reference.json','comparison/comparison_frames.jsonl']
        paths=[folder/name for name in names]
        inputs.update({str(p):replay.hash_regular(p,16*1024*1024) for p in paths})
        parse_rows=lambda p:[replay.parse_json(line) for line in p.read_bytes().splitlines()]
        setup=parse_rows(folder/'setup.jsonl')[0];primary=parse_rows(folder/'primary_frames.jsonl')
        reference=replay.parse_json((folder/'comparison/reference.json').read_bytes())
        old=parse_rows(folder/'comparison/comparison_frames.jsonl')
        png=folder/'comparison'/f"decoded_{reference['session']}_f000001.png"
        inputs[str(png)]=replay.hash_regular(png,4*1024*1024)
        now=[setup['completed_time_sec']+.001]
        stream=GuardedStreamComparison(data['settings'],data['camera'],data['profile'],data['profile_sha'],
            acknowledged=True,target_roi=[270,0,350,720],clock=lambda:now[0])
        def frame(row,job):
            return replay.NativeFrame(row['session'],row['frame'],row['media_time_sec'],row['source_time_sec'],job['image'])
        ref_job=next(job for job in data['jobs'] if job['frame']==data['reference']['source_frame'])
        initial=frame(setup,ref_job);stream.admit(initial.session,initial.sequence,initial.received_at)
        stream.pin_reference_frame(initial)
        now[0]=max(now[0],primary[0]['source_time_sec']-.000001)
        stream.activate(reference,png.read_bytes())
        if len(old)!=161 or len(primary)!=160:raise ValueError('incomplete submitted block')
        try:
            for n,(main_row,old_row) in enumerate(zip(primary,old[1:])):
                current=frame(main_row,data['jobs'][n%8]);now[0]=main_row['completed_time_sec']+.001
                stream.admit(current.session,current.sequence,current.received_at)
                result=stream.compare(current,main_row['raw_detector_boxes'],main_row)
                if any(result.get(k)!=old_row.get(k) for k in fields):
                    raise ValueError('updated runtime differs from submitted comparison')
                checks.append(dict(block=block_id,frame=main_row['frame'],original_frame=main_row['original_frame'],
                    equal=True,comparison_distance_available=result['comparison_distance_available'],
                    comparison_range_m=result['comparison_range_m'],reason=result['reason']))
        finally:stream.close()
        print(f'Updated runtime: block {block_id} all 160 submitted rows reproduced.',flush=True)
    report=dict(state='pass',compared_rows=len(checks),equal_rows=sum(row['equal'] for row in checks),
        numeric_rows=sum(row['comparison_distance_available'] for row in checks),rows=checks,
        synthetic_clock=True,NOT_performance_or_latency_evidence=True,cuda_started=False,camera_started=False,
        input_sha256=inputs,source_sha256={str(p.relative_to(ROOT)):replay.hash_regular(p,512*1024) for p in
            (Path(__file__),ROOT/'src/cone_motion_range.py',ROOT/'src/cone_guarded_stream_comparison.py')})
    for name,digest in inputs.items():
        if replay.hash_regular(Path(name),16*1024*1024)!=digest:raise ValueError('submitted original changed')
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','compared_rows','equal_rows','numeric_rows')},indent=2))


if __name__=='__main__':main()
