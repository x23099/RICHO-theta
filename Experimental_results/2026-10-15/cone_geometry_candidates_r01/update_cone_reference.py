"""Re-score frozen coordinates using user-confirmed edge/size, NEVER refit."""
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256,write_csv


def main():
    output=HERE/'reference_update_r01'
    if output.exists():raise ValueError('new reference result required; no overwrite')
    confirmation_path=HERE/'cone_reference_confirmation.json'
    confirmation=json.loads(confirmation_path.read_text())
    half=float(confirmation['base_side_m'])/2
    edge=float(confirmation['lateral_inner_edge_abs_x_m'])
    side_centre=edge+half
    previous_path=HERE/'results_r01/cone_transfer_frames.csv'
    rows=read_csv(previous_path)
    paths=[Path(__file__),confirmation_path,previous_path,HERE/'results_r01/candidate_parameters.json']
    before={str(f):sha256(f) for f in paths}
    adjusted=[]
    references=[]
    for condition,x,z in (('center_080',0,.8),('center_130',0,1.3),('center_200',0,2.),
        ('left_130',-side_centre,1.3),('right_130',side_centre,1.3)):
        references.append(dict(condition=condition,reference_x_m=x,reference_z_m=z,
            physical_point='midpoint of vehicle-side/front base edge',
            x_basis='base centre inferred from inner edge and width' if x else 'central placement',
            orientation_assumption='base edges approximately parallel to vehicle axes; unmeasured',
            base_side_m=2*half,physical_contact_verified=False))
    by_condition={r['condition']:r for r in references}
    for row in rows:
        result=dict(row,capture_label_reference_x_m=row['reference_x_m'],capture_label_reference_z_m=row['reference_z_m'])
        if row['condition'] in by_condition:
            reference=by_condition[row['condition']]
            x,z=reference['reference_x_m'],reference['reference_z_m']
            if float(row['reference_z_m'])!=z:raise ValueError('forward edge reference must NOT change')
            result.update(reference_x_m=x,reference_z_m=z,baseline_error_x_updated_m=None,
                baseline_error_z_updated_m=None,candidate_error_x_m=None,candidate_error_z_m=None)
            if row['baseline_used']=='True':
                result.update(baseline_error_x_updated_m=float(row['baseline_x_m'])-x,
                    baseline_error_z_updated_m=float(row['baseline_z_m'])-z)
            if row['candidate_used']=='True':
                result.update(candidate_error_x_m=float(row['candidate_x_m'])-x,
                    candidate_error_z_m=float(row['candidate_z_m'])-z)
            result['reference_basis']='user-confirmed front edge/inner edge/base width; X midpoint assumes axis alignment'
        else:
            result.update(baseline_error_x_updated_m=None,baseline_error_z_updated_m=None,reference_basis='no cone')
        adjusted.append(result)
    summaries=[]
    for reference in references:
        selected=[r for r in adjusted if r['condition']==reference['condition']]
        row=dict(reference,frames=len(selected),baseline_used=sum(r['baseline_used']=='True' for r in selected),
            candidate_used=sum(r['candidate_used']=='True' for r in selected),
            hypothetical_base_rotation_0_to_45deg_error_x_min_m=None,
            hypothetical_base_rotation_0_to_45deg_error_x_max_m=None)
        for prefix,flag in (('baseline','baseline_used'),('candidate','candidate_used')):
            valid=[r for r in selected if r[flag]=='True']
            for axis in ('x','z'):
                row[prefix+'_'+axis+'_median_m']=float(np.median([float(r[prefix+'_'+axis+'_m']) for r in valid]))
                field=prefix+'_error_'+axis+('_updated_m' if prefix=='baseline' else '_m')
                row[prefix+'_error_'+axis+'_median_m']=float(np.median([float(r[field]) for r in valid]))
        if reference['condition'] in ('left_130','right_130'):
            sign=-1 if reference['condition']=='left_130' else 1
            centres=[sign*(edge+half),sign*(edge+half*math.sqrt(2))]
            errors=[row['candidate_x_median_m']-x for x in centres]
            row.update(hypothetical_base_rotation_0_to_45deg_error_x_min_m=min(errors),
                       hypothetical_base_rotation_0_to_45deg_error_x_max_m=max(errors))
        summaries.append(row)
    output.mkdir(exist_ok=False)
    write_csv(output/'reference_conditions.csv',references)
    write_csv(output/'cone_transfer_frames_updated.csv',adjusted)
    write_csv(output/'cone_transfer_summary_updated.csv',summaries)
    if any(sha256(Path(f))!=digest for f,digest in before.items()):raise ValueError('source/parameters changed')
    report=dict(status='COMPLETED_USER_REFERENCE_RESCORE_NO_PARAMETER_OR_COORDINATE_CHANGE',
        reference_source=str(confirmation_path),base_orientation_assumption_explicit=True,
        derived_abs_midpoint_x_m=side_centre,forward_edge_reference_preserved=True,
        frames_retained=len(adjusted),parameters_refitted=False,predicted_coordinates_changed=False,
        physical_output=False,usable_for_ffb=False,source_sha256=before,
        output_sha256={f.name:sha256(f) for f in output.iterdir() if f.is_file()})
    (output/'provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in summaries:
        print(row['condition'],'referenceX',row['reference_x_m'],'baseline errorX',round(row['baseline_error_x_median_m'],4),
            'candidate errorX',round(row['candidate_error_x_median_m'],4),'candidate Z',round(row['candidate_z_median_m'],4))


if __name__=='__main__':main()
