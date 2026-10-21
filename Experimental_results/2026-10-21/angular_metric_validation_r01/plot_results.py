"""Numerical plots and conditional transfer diagnostics; never edit camera images."""
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate,unproject,project,floor_from_rays

MODELS=('ideal59_nominal','angular_nominal','angular_paper5_rotation')
LABELS=('Previous ideal + nominal pose','Angular KB4 + nominal pose','Angular KB4 + paper-5 pose')
COLORS=('#888888','#2980b9','#d35400')
CONDITIONS=(('static','center_080'),('static','center_130'),('static','center_200'),
            ('static','left_130'),('static','right_130'),('sequence','cone_130'),
            ('sequence','cone_200'),('paper_cone_20261019','cone_static'))
CONDITION_LABELS=('Static\n0.8 m','Static\n1.3 m','Static\n2.0 m','Left\n1.3 m',
                  'Right\n1.3 m','Sequence\n1.3 m','Sequence\n2.0 m','Oct19\n2.0 m')


def main():
    folder=HERE/'plots_r01'
    if folder.exists():raise ValueError('no plot/diagnostic overwrite')
    folder.mkdir()
    result=HERE/'results_r01'
    candidate_path=HERE.parent/'front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    inputs=[candidate_path,result/'summary.json',result/'floor_reference_results.csv',
            result/'cone_summary.csv',result/'floor_transform_candidate.json',Path(__file__)]
    sources={str(p):sha256(p) for p in inputs}
    camera=camera_from_candidate(json.loads(candidate_path.read_text()))
    transform=np.array(json.loads((result/'floor_transform_candidate.json').read_text())['transform_target_from_source'])
    floors=read_csv(result/'floor_reference_results.csv')
    cones=read_csv(result/'cone_summary.csv')
    floor_lookup={(r['model'],r['point_id']):r for r in floors}
    cone_lookup={(r['dataset'],r['condition'],r['model'],r['method']):r for r in cones}
    ids=('C080','C130','C200','L130','R130','H100','H160','paper_cone_2m')
    labels=('C0.8','C1.3','C2.0','L1.3','R1.3','H1.0','H1.6','Oct19\n2.0')
    fig,axes=plt.subplots(1,2,figsize=(12,4.7))
    for model,label,color in zip(MODELS,LABELS,COLORS):
        rows=[floor_lookup[model,i] for i in ids]
        axes[0].plot(range(8),[float(r['z_forward_m']) for r in rows],'o-',label=label,color=color)
        axes[1].plot(range(8),[100*float(r['planar_error_m']) for r in rows],'o-',label=label,color=color)
    axes[0].plot(range(8),[float(floor_lookup[MODELS[0],i]['reference_z_m']) for i in ids],
                 'k--',label='Placed reference')
    for ax in axes:
        ax.set_xticks(range(8));ax.set_xticklabels(labels);ax.axvline(4.5,color='k',ls=':')
        ax.axvline(6.5,color='k',ls=':');ax.grid(alpha=.25)
        ax.set_xlabel('Fit: first 5 | held-out: next 2 | cross-recording: last 1')
    axes[0].set_ylabel('Forward distance (m)');axes[1].set_ylabel('Planar position error (cm)')
    axes[0].legend(fontsize=8)
    fig.suptitle('Fixed checkerboard intrinsics: floor-reference validation (conditional, not runtime approval)')
    fig.tight_layout();fig.savefig(folder/'floor_metric_validation.png',dpi=150);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(13,4.7))
    for model,label,color in zip(MODELS,LABELS,COLORS):
        rows=[cone_lookup[d,c,model,'floor_bottom_proxy'] for d,c in CONDITIONS]
        axes[0].plot(range(8),[100*float(r['z_bias_m']) for r in rows],'o-',color=color,label=label)
    for method,label,style in [('height_vertical_proxy','Height: vertical endpoint assumption','o-'),
                              ('height_near_edge_assumption','Height: 18.75 cm forward-offset assumption','s--')]:
        for model,color in zip(MODELS,COLORS):
            rows=[cone_lookup[d,c,model,method] for d,c in CONDITIONS]
            axes[1].plot(range(8),[100*float(r['z_bias_m']) for r in rows],style,color=color,
                         label=label if model==MODELS[0] else None)
    for ax in axes:
        ax.axhline(0,color='k',lw=1);ax.grid(alpha=.25)
        ax.set_xticks(range(8));ax.set_xticklabels(CONDITION_LABELS,fontsize=8)
        ax.set_ylabel('Median forward-distance bias (cm)');ax.legend(fontsize=7)
    axes[0].set_title('Observed bottom pixel intersected with floor')
    axes[1].set_title('Known 73 cm height: same saved endpoint pixels')
    fig.suptitle('Cone proxies: all labelled conditions retained; endpoint correspondence NOT verified')
    fig.tight_layout();fig.savefig(folder/'cone_metric_comparison.png',dpi=150);plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(13,4.7))
    for model,label,color in zip(MODELS,LABELS,COLORS):
        rows=[cone_lookup[d,c,model,'height_vertical_proxy'] for d,c in CONDITIONS]
        axes[0].plot(range(8),[100*float(r['base_height_median_m']) for r in rows],'o-',color=color,label=label)
        axes[1].plot(range(8),[100*float(r['segment_residual_median_m']) for r in rows],'o-',color=color)
    for ax in axes:
        ax.set_xticks(range(8));ax.set_xticklabels(CONDITION_LABELS,fontsize=8);ax.grid(alpha=.25)
    axes[0].axhline(0,color='k',ls='--');axes[0].set_ylabel('Solved bottom point height (cm; floor = 0)')
    axes[1].axhline(2,color='k',ls=':',label='Previous 2 cm segment diagnostic screen')
    axes[1].set_ylabel('3D known-segment residual (cm)');axes[1].legend(fontsize=7)
    axes[0].legend(fontsize=7)
    fig.suptitle('Height-only depth is NOT proof of floor consistency (no floor constraint imposed)')
    fig.tight_layout();fig.savefig(folder/'cone_height_consistency.png',dpi=150);plt.close(fig)

    # No new fit: evaluate +/-1 native-pixel sensitivity with the frozen pose.
    diagnostics=[]
    for point_id in ids:
        r=floor_lookup[MODELS[2],point_id]
        uv=np.array([float(r['pixel_x']),float(r['pixel_y'])])
        samples=uv+np.array([[dx,dy] for dx in (-1,0,1) for dy in (-1,0,1)])
        rays,valid=unproject(samples,camera,image_size=(1280,720))
        xyz,valid=floor_from_rays(rays,valid,transform)
        assert valid.all()
        ref=np.array([[float(r['reference_z_m']),-float(r['reference_x_m']),0.]])
        predicted,valid=project((ref-transform[:3,3])@transform[:3,:3],camera)
        assert valid.all()
        diagnostics.append(dict(point_id=point_id,pixel_x=uv[0],pixel_y=uv[1],
            predicted_reference_x=predicted[0,0],predicted_reference_y=predicted[0,1],
            pixel_residual_norm=float(np.linalg.norm(uv-predicted[0])),
            z_at_observed_m=float(r['z_forward_m']),
            z_min_with_plusminus_one_pixel_m=float(xyz[:,0].min()),
            z_max_with_plusminus_one_pixel_m=float(xyz[:,0].max()),
            reference_z_m=float(r['reference_z_m']),
            # This is one-axis conditional equivalence, NOT a new height measurement.
            required_height_for_forward_z_only_m=.59*float(r['reference_z_m'])/float(r['z_forward_m']),
            physical_pose_change_proven=False,usable_for_ffb=False))
    write_csv(folder/'pixel_sensitivity_and_reference_projection.csv',diagnostics)
    pair=np.array([[float(floor_lookup[MODELS[2],i]['pixel_x']),float(floor_lookup[MODELS[2],i]['pixel_y'])]
                   for i in ('C200','paper_cone_2m')])
    rays,valid=unproject(pair,camera,image_size=(1280,720));assert valid.all()
    angle=float(np.degrees(np.arccos(np.clip(rays[0]@rays[1],-1,1))))
    record=dict(source_sha256=sources,
        paper7_to_oct19_native_delta_px=(pair[1]-pair[0]).tolist(),
        paper7_to_oct19_calibrated_ray_angle_deg=angle,
        paper7_to_oct19_depth_difference_m=float(floor_lookup[MODELS[2],'paper_cone_2m']['z_forward_m'])-float(floor_lookup[MODELS[2],'C200']['z_forward_m']),
        sensitivity_interpretation='Finite sensitivity scenarios, not measured corner uncertainty or confidence intervals',
        independently_measured_pose_change=False,usable_for_ffb=False,original_images_edited=False,
        output_sha256={p.name:sha256(p) for p in folder.iterdir() if p.is_file()})
    assert all(sha256(Path(p))==digest for p,digest in sources.items())
    (folder/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
