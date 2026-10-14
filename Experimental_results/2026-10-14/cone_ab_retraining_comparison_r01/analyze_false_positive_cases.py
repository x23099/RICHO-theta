"""Match only previously user-confirmed non-cone examples, without relabelling val."""
from pathlib import Path
import json
import sys

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'src'))
from cone_dataset import read_csv,sha256,write_csv
from cone_detection_diagnostics import intersection_over_union


def main():
    root=Path(__file__).resolve().parent
    if (root/'false_positive_case_verification.json').exists():raise ValueError('immutable case review already exists')
    reference=REPO/'Experimental_results/2026-10-13/cone_ab_visual_review_r01/reviewed_error_cases.csv'
    cases=[r for r in read_csv(reference) if r['category']=='non_cone_region' and 'User explicitly confirmed' in r['note']]
    if len(cases)!=2:raise ValueError('exact two previously user-confirmed non-cone references required')
    output=[];inputs={str(reference.relative_to(REPO)):sha256(reference)}
    for name,folder in (('baseline_35','cone_baseline_fp32_diagnose_r01'),('augmented_36','cone_augmented_v03_fp32_diagnose_r01')):
        path=root.parent/folder/'predictions.csv';predictions=read_csv(path)
        inputs[str(path.relative_to(REPO))]=sha256(path)
        for case in cases:
            reference_box={k:float(case[k]) for k in ('x1','y1','x2','y2')}
            matches=[]
            for prediction in predictions:
                if prediction['image']!=case['image']:continue
                overlap=intersection_over_union(reference_box,{k:float(prediction[k]) for k in reference_box})
                if overlap>=.5:matches.append((float(prediction['confidence']),prediction,overlap))
            best=max(matches,key=lambda item:item[0]) if matches else None
            output.append(dict(model=name,image=case['image'],
                matched_prediction_index=best[1]['prediction_index'] if best else '',
                confidence=best[0] if best else '',reference_iou=best[2] if best else '',
                retained_at_0p25=bool(best and best[0]>=.25),retained_at_0p50=bool(best and best[0]>=.5),
                scope='previously user-confirmed non-cone region in this exact image; not automatic proof for other images'))
    write_csv(root/'confirmed_noncone_cases.csv',output)
    summary=dict(date='2026-10-14',rows=len(output),reference_cases=2,input_sha256=inputs,
        output_sha256=sha256(root/'confirmed_noncone_cases.csv'),script_sha256=sha256(Path(__file__)),
        val_labels_modified=False,physical_output=False)
    (root/'false_positive_case_verification.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
