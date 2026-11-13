"""Review transient numeric values from original main log, never invent pixels."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from verify_driver_withheld_evidence import parse_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    base=Path(__file__).parent
    audit=json.loads((base/'results_r01/audit.json').read_bytes())
    source=ROOT/'recordings/2026-11-13/guarded_static_full_intake_r02/primary/motion_distance_frames.jsonl'
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=audit['supplied_files_sha256']['primary/motion_distance_frames.jsonl']:raise ValueError('verified log changed')
    records=[]
    with source.open('rb') as stream:
        for line in stream:
            row=parse_json(line);value=row['horizontal_camera_foot_range_m']
            if row['frame']<audit['first_reference_frame'] or not row['distance_available'] or value<=2.:continue
            observation=row.get('support_observation') or {};boxes=row['selected_detector_boxes']
            records.append(dict(frame=row['frame'],source_time_sec=row['source_time_sec'],range_m=value,
                support_x=row['support_pixel'][0],support_y=row['support_pixel'][1],
                selected_colour=observation.get('selected_colour'),front_candidates=row['front_candidates'],
                confidence=boxes[0]['confidence'] if len(boxes)==1 else None,
                candidate_xyxy=json.dumps([[b[k] for k in ('x1','y1','x2','y2')] for b in boxes]),
                exact_same_frame_image_supplied=False,physical_ground_truth_supplied=False))
    with (args.output_dir/'over_2m.csv').open('x',newline='') as stream:
        fields=list(records[0]) if records else ['frame','range_m']
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(records)
    report=dict(state='pass',selection='all post-reference main numeric values >2m; diagnostic threshold, NOT a correctness label',
        count=len(records),maximum_m=max((r['range_m'] for r in records),default=None),
        frames=[r['frame'] for r in records],selected_colours=sorted({r['selected_colour'] for r in records}),
        source_log_sha256=digest,source_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        support_pixel_change_observed_in_logs=True,cause_verified_from_images=False,
        not_proven_measurement_error_without_ground_truth=True,local_camera_started=False,local_cuda_started=False)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
