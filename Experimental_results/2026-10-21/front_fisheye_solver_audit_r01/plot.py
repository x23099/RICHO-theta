"""Numeric plots only; never modifies or renders over native camera images."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent


def main():
    output=HERE/'plots_r01'
    if output.exists():raise ValueError('no plot overwrite')
    old=json.loads((HERE/'results_r01/joint_diagnostic_candidate.json').read_text())
    new=json.loads((HERE/'angular_results_r01/angular_diagnostic_candidate.json').read_text())
    output.mkdir()
    fig,axes=plt.subplots(1,3,figsize=(16,4.8),constrained_layout=True)
    for result,label,colour in [(old,'OpenCV projection: boundary stop','tab:grey'),
                                (new,'Angular KB4: stationary candidate','tab:blue')]:
        axes[0].semilogy([r['evaluation'] for r in result['trace']],[r['pixel_rms'] for r in result['trace']],
                         marker='.',label=label,c=colour)
    axes[0].set(xlabel='Objective evaluation (includes rejected trial steps)',ylabel='Train pixel RMS',title='Same 46 train images / no view pruning')
    axes[0].legend(fontsize=7)
    x=np.arange(2)
    axes[1].bar(x-.18,[old['calibration_rms_px'],old['pose_validation_rms_px']],width=.36,color='tab:grey',label='Boundary-stopped; not adopted')
    values=[new['calibration_rms_px'],new['pose_validation_rms_px']]
    axes[1].bar(x+.18,values,width=.36,color='tab:blue',label='Angular KB4 diagnostic')
    for i,v in enumerate(values):axes[1].text(i+.18,v+.025,f'{v:.3f}',ha='center')
    axes[1].set(xticks=x,xticklabels=['Train (46 images)','Pose validation (11)'],ylabel='Aggregate reprojection RMS [px]',ylim=(0,1.2),title='Pixel error is not metric distance accuracy')
    axes[1].legend(fontsize=7)
    rows=new['per_view']
    for split,colour in [('train','tab:blue'),('pose_validation_only','tab:orange')]:
        selected=[r for r in rows if r['split']==split]
        axes[2].scatter([r['view_index'] for r in selected],[r['maximum_angle_deg'] for r in selected],s=20,c=colour,label=split)
    axes[2].axhline(90,c='red',ls='--',label='Z=0 (not actual measured lens FOV)')
    axes[2].set(xlabel='Frozen merged image index',ylabel='Estimated largest optical-axis angle [deg]',
                title=f"Angular estimate: {new['points_beyond_90']} corners > 90 deg")
    axes[2].legend(fontsize=7)
    fig.savefig(output/'solver_domain_comparison.png',dpi=150)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
    for split,colour in [('train','tab:blue'),('pose_validation_only','tab:orange')]:
        selected=[r for r in rows if r['split']==split]
        axes[0].scatter([r['view_index'] for r in selected],[r['rms_px'] for r in selected],c=colour,label=split)
    axes[0].axvline(53.5,c='grey',ls=':')
    axes[0].set(xlabel='Frozen merged index (r03 starts at 54)',ylabel='Per-image reprojection RMS [px]',title='All 57 images retained')
    axes[0].legend(fontsize=8)
    with (HERE/'results_r01/corner_audit.csv').open(newline='') as stream:audit=list(csv.DictReader(stream))
    axes[1].scatter([int(r['merged_index']) for r in audit],[float(r['subpix_movement_rms_px']) for r in audit],s=20,label='3 px cornerSubPix movement')
    classic=[r for r in audit if r['classic_grid_rms_px']]
    axes[1].scatter([int(r['merged_index']) for r in classic],[float(r['classic_grid_rms_px']) for r in classic],marker='x',label='Classic detector difference')
    axes[1].set(xlabel='Frozen merged index',ylabel='Coordinate difference [px]',title='Audit only: original SB corners used for fit')
    axes[1].legend(fontsize=8)
    fig.savefig(output/'per_view_and_corner_audit.png',dpi=150)
    plt.close(fig)


if __name__=='__main__':main()
