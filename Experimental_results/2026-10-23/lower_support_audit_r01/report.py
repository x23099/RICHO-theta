"""Support provenance report; no segmentation or veto from color values."""
from collections import Counter
import json
from pathlib import Path
import shutil

import cv2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from support_audit import HERE,PREVIOUS,UNIFORM
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'report_r01'
    if output.exists():raise ValueError('new report output required')
    results=HERE/'results_r01';summary=json.loads((results/'summary.json').read_text())
    for name,h in summary['output_sha256'].items():assert sha256(results/name)==h
    inputs=[Path(__file__),results/'summary.json',results/'all_lower_references.csv',results/'lower_inlier_support.csv',
        results/'actual_lower_support.csv',results/'leave_one_plane_out.csv',results/'counterfactual_sessions.csv',
        UNIFORM/'intake_r01/native_sample_manifest.csv']
    sources={str(p):sha256(p) for p in inputs}
    samples={(r['session'],r['frame']):r for r in read_csv(UNIFORM/'intake_r01/native_sample_manifest.csv')}
    supports=read_csv(results/'lower_inlier_support.csv')
    refs={(r['session'],r['frame'],r['fusion_index']):r for r in read_csv(results/'all_lower_references.csv')}
    color_rows=[]
    for r in read_csv(results/'actual_lower_support.csv'):
        sample=samples[r['session'],r['frame']];path=Path(sample['source_native_png'])
        assert sha256(path)==sample['png_sha256'];sources[str(path)]=sample['png_sha256']
        image=cv2.imread(str(path));pixels=np.array(json.loads(r['actual_edge_pixels_json']),int)
        rgb=image[pixels[:,1],pixels[:,0],::-1]
        med=np.median(rgb,axis=0)
        color_rows.append(dict(session=r['session'],frame=r['frame'],fusion_index=r['fusion_index'],
            actual_support_pixels=len(pixels),median_r=float(med[0]),median_g=float(med[1]),median_b=float(med[2]),
            median_r_minus_g=float(np.median(rgb[:,0].astype(float)-rgb[:,1])),
            used_as_segmentation_or_veto=False,physical_vertical_verified=False))
    output.mkdir();write_csv(output/'actual_support_color_values.csv',color_rows)
    new=[r for r in supports if r['newly_accepted_image']=='True']
    categories=Counter()
    for r in new:
        ref=refs[r['session'],r['frame'],r['fusion_index']]
        categories[(ref['counterfactual_veto'],r['seam_continuation_possible'])]+=1
    category_rows=[dict(close_to_pre_dedup_upper=a,seam_continuation_possible=b,observations=n)
                   for (a,b),n in sorted(categories.items())]
    write_csv(output/'new_support_joint_evidence.csv',category_rows)
    loo=read_csv(results/'leave_one_plane_out.csv')
    new_lower=[r for r in loo if r['newly_accepted_image']=='True' and r['removed_band']=='lower']
    fig,axes=plt.subplots(1,2,figsize=(11,4.8))
    axes[0].bar(['Original upper','Separate-band fusion','Audit veto (NOT adopted)'],[27,53,36],color=['#888888','#2980b9','#c49a38'])
    axes[0].set_ylabel('Accepted images / same 492 inputs');axes[0].tick_params(axis='x',labelsize=8)
    axes[0].set_title('Coverage is sensitive to duplicate references')
    labels=['Near old duplicate +\nconnectable seam','No seam evidence;\nadditional context review needed']
    axes[1].bar(labels,[categories['True','True'],categories['False','False']],color=['#c49a38','#888888'])
    axes[1].set_ylabel('New lower inlier observations / 26');axes[1].tick_params(axis='x',labelsize=8)
    axes[1].set_title('Direction/continuity are not physical identity')
    for ax in axes:ax.grid(axis='y',alpha=.2)
    fig.suptitle('Audit of the one lower-band vote: previous 5/9 temporal passes are NOT physical validation')
    fig.tight_layout();fig.savefig(output/'lower_support_independence_audit.png',dpi=150);plt.close(fig)
    # Context examples selected for the diagnostic causes, not a performance holdout.
    chosen=[('cone_static_center_z1p30_r01_20261015_135329_732','152','seam_context'),
            ('cone_static_no_cone_r01_20261015_134940_713','92','no_cone_context'),
            ('one_static_center_z0p80_r01_20261015_135155_823','149','cone_surface_context')]
    assets=[]
    for session,frame,label in chosen:
        sample=samples[session,frame];source=Path(sample['source_native_png']);name=f'native_{label}_f{int(frame):06d}.png'
        shutil.copy2(source,output/name);assert sha256(output/name)==sample['png_sha256']
        assets.append(dict(file=name,source=str(source),session=session,frame=int(frame),sha256=sample['png_sha256'],image_edited=False,width=1280,height=720))
    record=dict(status='COMPLETED_SUPPORT_CONTEXT_AND_ABLATION_REPORT_NOT_GATE_ADOPTION',work_date='2026-10-23',
        source_sha256=sources,native_assets=assets,new_lower_removal_trials=len(new_lower),
        new_lower_removal_rejections=sum(r['remaining_accepted']=='False' for r in new_lower),
        new_lower_removal_alternative_directions=sum(r['remaining_accepted']=='True' for r in new_lower),
        source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    assert all(sha256(Path(p))==h for p,h in sources.items())
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256','native_assets')},indent=2))


if __name__=='__main__':main()
