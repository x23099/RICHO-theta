"""Timing-only selection audit on existing comparisons; NOT CUDA/live replay."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from run_guarded_recording_comparison import hash_regular
from verify_driver_withheld_evidence import parse_json,read_regular
from report_driver_motion_logs import distribution


def select(events,hz):
    previous=None;selected=[];counts=Counter();numeric_total=numeric_selected=0;gaps=[]
    for item in events:
        when=item['clock'];numeric_total+=item['numeric']
        if previous is None or hz==0 or when+1e-9>=previous+1/hz:
            if previous is not None:gaps.append(1000*(when-previous))
            previous=when;counts[item['original_frame']]+=1;numeric_selected+=item['numeric']
            selected.append(item['ordinal'])
    return dict(max_hz=hz,offered=len(events),selected=len(selected),skipped=len(events)-len(selected),
        selected_by_original_frame=dict(counts),numeric_opportunities=numeric_total,
        numeric_selected=numeric_selected,numeric_skipped=numeric_total-numeric_selected,
        selected_start_gap_ms=distribution(gaps),selected_ordinals=selected)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    intake=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r03'
    report_path=ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r03/results_r01/audit.json'
    audit=parse_json(read_regular(report_path,1024*1024));hashes={};trials=[]
    for block in (1,2):
        label=f'block_{block:02d}_on';path=intake/label/'comparison/comparison_frames.jsonl'
        digest=hash_regular(path,16*1024*1024)
        if digest!=audit['supplied_files_sha256'][label+'/comparison/comparison_frames.jsonl']:
            raise ValueError('submitted comparison changed')
        hashes[str(path)]=digest
        rows=[parse_json(line) for line in read_regular(path,16*1024*1024).splitlines()][1:]
        frames=[6861,14203,14267,14297,14329,14382,14604,14922]
        actual=[dict(clock=row['completed_time_sec']-row['comparison_service_ms']/1000,
            ordinal=n,original_frame=frames[n%8],numeric=row['comparison_distance_available']) for n,row in enumerate(rows)]
        uniform=[dict(item,clock=n/30) for n,item in enumerate(actual)]
        for source,events in (('saved_worker_start_times',actual),('synthetic_uniform_30hz',uniform)):
            for hz in (0,5,10,15):trials.append(dict(block=block,clock_kind=source,**select(events,hz)))
    report=dict(state='pass',trials=trials,input_sha256=hashes,
        source_sha256={str(Path(__file__).relative_to(ROOT)):hash_regular(Path(__file__),512*1024)},
        actual_comparison_computed=False,cuda_started=False,camera_started=False,
        NOT_performance_accuracy_or_live_latency_validation=True)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    summary=[{k:v for k,v in row.items() if k not in ('selected_ordinals','selected_by_original_frame','selected_start_gap_ms')} for row in trials]
    with (args.output_dir/'selection.csv').open('x',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
