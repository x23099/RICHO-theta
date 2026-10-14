"""Explain fixed-threshold misses without adjusting model or annotation."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256,write_csv
from cone_detection_diagnostics import intersection_over_union


def main():
    out=Path(__file__).resolve().parent
    if (out/'miss_cases.csv').exists():raise ValueError('miss snapshot already exists')
    diagnostic=out.parent/'cone_negative_v04_b_diagnose_r01'
    truths=read_csv(diagnostic/'ground_truth.csv');predictions=read_csv(diagnostic/'predictions.csv')
    for row in truths+predictions:
        for key in ('x1','y1','x2','y2'):row[key]=float(row[key])
    for row in predictions:row['confidence']=float(row['confidence'])
    result=[]
    for row in read_csv(diagnostic/'matches.csv'):
        if row['confidence_threshold']!='0.25' or row['outcome']!='FN':continue
        truth=next(t for t in truths if t['image']==row['image'] and t['gt_index']==row['gt_index'])
        candidates=[p for p in predictions if p['image']==truth['image']]
        best=max(candidates,key=lambda p:intersection_over_union(truth,p),default=None)
        overlap=intersection_over_union(truth,best) if best else 0
        result.append(dict(scope='B human reviewed labels',image=truth['image'],color=truth['color'],
            best_overlap_iou=overlap,score=best['confidence'] if best else '',threshold=.25,
            explanation='overlapping candidate exists below threshold' if best and overlap>=.5 and best['confidence']<.25
                        else 'no sufficient-overlap candidate',model='negative_52'))
    for row in read_csv(out/'e_target_associations.csv'):
        if row['model']=='negative_52' and row['present_at_0p25']=='0':
            result.append(dict(scope='E assistant reference, NOT human GT',image=row['image'],color=row['color'],
                best_overlap_iou='',score=row['best_score'],threshold=.25,
                explanation='associated candidate below threshold' if row['best_score'] else 'no sufficient-overlap candidate',
                model='negative_52'))
    write_csv(out/'miss_cases.csv',result)
    (out/'miss_verification.json').write_text(json.dumps(dict(misses=result,
        source_sha256={str(p):sha256(p) for p in [diagnostic/'matches.csv',diagnostic/'ground_truth.csv',
                        diagnostic/'predictions.csv',out/'e_target_associations.csv']},
        script_sha256=sha256(Path(__file__)),threshold_changed=False,labels_changed=False),indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
