"""Local fixed-vehicle feature audit; no source image edits or alignment.

In-memory ROI comparisons only. No cropped/annotated/resampled image is saved.
Local template offsets do NOT prove camera pose or define a world correction.
"""
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256,write_csv

REGIONS=(('front_centre_lower',300,550,45,40),('front_left_holes',220,500,60,50),
         ('front_right_device',405,532,55,42),('rear_right_holes',1050,520,65,50),
         ('rear_lower_right_tape',1110,518,47,45))


def match_region(reference,current,region,margin=20):
    if (reference.shape!=(720,1280) or current.shape!=reference.shape
            or reference.dtype!=np.uint8 or current.dtype!=np.uint8):
        raise ValueError('native1280x720 grayscale diagnostic arrays required')
    name,x,y,w,h=region
    if type(margin) is not int or margin<4 or min(w,h)<4 or x-margin<0 or y-margin<0 or x+w+margin>1280 or y+h+margin>720:
        raise ValueError('bounded nonempty ROI/search region required')
    template=reference[y:y+h,x:x+w]
    if template.std()<2:raise ValueError('insufficient texture for normalized matching')
    response=cv2.matchTemplate(current[y-margin:y+h+margin,x-margin:x+w+margin],template,cv2.TM_CCOEFF_NORMED)
    _,best,_,position=cv2.minMaxLoc(response)
    dx,dy=position[0]-margin,position[1]-margin
    yy,xx=np.indices(response.shape)
    separated=response[np.maximum(abs(xx-position[0]),abs(yy-position[1]))>3]
    second=float(separated.max())
    matched=current[y+dy:y+dy+h,x+dx:x+dx+w]
    reverse=cv2.matchTemplate(reference[y-margin:y+h+margin,x-margin:x+w+margin],matched,cv2.TM_CCOEFF_NORMED)
    _,back_score,_,back=cv2.minMaxLoc(reverse)
    back_error=max(abs(back[0]-margin),abs(back[1]-margin))
    boundary=abs(dx)==margin or abs(dy)==margin
    reliable=best>=.8 and best-second>=.02 and back_error<=1 and not boundary
    reasons=[]
    if best<.8:reasons.append('low_correlation')
    if best-second<.02:reasons.append('competing_peak')
    if back_error>1:reasons.append('reverse_mismatch')
    if boundary:reasons.append('search_boundary')
    return dict(region=name,x=x,y=y,width=w,height=h,search_margin_px=margin,
        delta_x_current_minus_reference_px=dx,delta_y_current_minus_reference_px=dy,
        ncc=float(best),zero_offset_ncc=float(response[margin,margin]),second_separated_peak=second,
        separated_peak_margin=float(best-second),reverse_ncc=float(back_score),reverse_return_error_px=back_error,
        reliable_for_local_feature_comparison=bool(reliable),reason='consistent_local_match' if reliable else '|'.join(reasons))


def main():
    output=HERE/'view_audit_r01'
    if output.exists():raise ValueError('new view audit required; no overwrite')
    root=HERE.parent
    floor=root/'cone_floor_reference_real_r01/raw_samples'
    cone=root/'cone_static_distance_r01/raw_samples'
    ref=floor/'floor_reference_f000187.png'
    files=[('floor_control_'+str(n),'within_floor',floor/f'floor_reference_f{n:06d}.png') for n in (94,280,373)]
    files.extend((condition,'cone_vs_floor',cone/name) for condition,name in (
        ('center_080','center_080_f000241.png'),('center_130','center_130_f000217.png'),
        ('center_200','center_200_f000211.png'),('left_130','left_130_f000210.png'),('right_130','right_130_f000211.png')))
    files.extend(('cone_control_'+str(n),'within_cone',cone/f'center_130_f{n:06d}.png') for n in (1,434,651))
    before={str(f):sha256(f) for f in [Path(__file__),HERE/'test_view_registration.py',ref]+[v[2] for v in files]}
    reference=cv2.imread(str(ref),cv2.IMREAD_GRAYSCALE)
    cone_reference_path=cone/'center_130_f000217.png'
    before[str(cone_reference_path)]=sha256(cone_reference_path)
    cone_reference=cv2.imread(str(cone_reference_path),cv2.IMREAD_GRAYSCALE)
    rows=[]
    for identity,group,path in files:
        current=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        anchor=cone_reference if group=='within_cone' else reference
        for region in REGIONS:
            row=match_region(anchor,current,region)
            rows.append(dict(case=identity,group=group,file=str(path),
                reference=str(cone_reference_path if group=='within_cone' else ref),**row))
    output.mkdir(exist_ok=False)
    write_csv(output/'local_feature_matches.csv',rows)
    os.environ.setdefault('MPLCONFIGDIR',str(HERE/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),constrained_layout=True)
    cases=[identity for identity,group,path in files if group=='cone_vs_floor']
    for panel,axis in zip(axes,('x','y')):
        for name,*_ in REGIONS:
            selected=[next(r for r in rows if r['case']==identity and r['region']==name) for identity in cases]
            values=[r['delta_'+axis+'_current_minus_reference_px'] if r['reliable_for_local_feature_comparison'] else np.nan for r in selected]
            panel.plot(range(len(cases)),values,'o-',label=name)
        panel.axhline(0,color='black',lw=.8)
        panel.set(xticks=range(len(cases)),xticklabels=cases,ylabel=axis.upper()+' local offset [px]',
            title='Cone image minus floor image; NOT global alignment')
        panel.tick_params(axis='x',rotation=25);panel.grid(alpha=.25)
    axes[0].legend(fontsize=7)
    fig.savefig(output/'fixed_feature_offsets.png',dpi=150);plt.close(fig)
    if any(sha256(Path(f))!=digest for f,digest in before.items()):raise ValueError('native source image/code changed')
    summary=dict(status='COMPLETED_LOCAL_VEHICLE_FEATURE_DIAGNOSIS_NOT_POSE_CALIBRATION',
        regions=[list(r) for r in REGIONS],criteria=dict(min_ncc=.8,min_separated_peak_margin=.02,max_reverse_error_px=1),
        threshold_scope='diagnostic heuristic, not calibrated probability of a correct match',
        source_sha256=before,rows=len(rows),
        reliable_counts={group:sum(r['group']==group and r['reliable_for_local_feature_comparison'] for r in rows)
                         for group in ('within_floor','within_cone','cone_vs_floor')},
        limits=['assumes compared vehicle features did not physically move/change',
            'local translations can differ across a fisheye image; no rigid global shift or pose estimated',
            'paper/occlusion/low texture/repeating holes can change appearance or produce false matches',
            'all chosen ROI results retained, including unreliable ones',
            'does not prove operator changed camera height/angle; does not isolate camera/vehicle flex or capture processing'],
        source_images_changed=False,cropped_or_annotated_images_saved=False,
        correction_applied=False,physical_output=False,
        reference='https://docs.opencv.org/4.13.0/d4/dc6/tutorial_py_template_matching.html',
        output_sha256={f.name:sha256(f) for f in output.iterdir() if f.is_file()})
    (output/'provenance.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary['reliable_counts']))
    for row in rows:
        if row['group']=='cone_vs_floor':
            print(row['case'],row['region'],row['delta_x_current_minus_reference_px'],row['delta_y_current_minus_reference_px'],round(row['ncc'],3),round(row['separated_peak_margin'],3),row['reliable_for_local_feature_comparison'])


if __name__=='__main__':main()
