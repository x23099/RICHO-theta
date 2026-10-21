"""Numerical graphs, selected-edge provenance, and offline regression checks."""
from collections import Counter
import io
import json
from pathlib import Path
import sys
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(HERE))
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'plots_and_verification_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    output.mkdir()
    files=[HERE/'results_r01/image_diagnostics.csv',HERE/'curve_results_r01/image_diagnostics.csv',
        HERE/'curve_results_r01/line_candidates.csv',HERE/'curve_results_r01/session_hypotheses.csv',
        HERE/'curve_results_r01/cone_condition_summary.csv',HERE/'test_scene_geometry.py',Path(__file__),
        HERE.parent/'angular_metric_validation_r01/results_r01/cone_summary.csv']
    sources={str(p):sha256(p) for p in files}
    original=read_csv(files[0]);frames=read_csv(files[1]);lines=read_csv(files[2]);sessions=read_csv(files[3]);metric=read_csv(files[4])
    baseline=read_csv(files[-1])
    names={r['session']:r['session'].split('_r01_')[0].replace('cone_static_','').replace('one_static_','').replace('floor_cone_same_pose','sequence').replace('itiawase2_20261015_183552_599','paper7').replace('paper_cone_center_z2p00','Oct19 paper+cone') for r in sessions}
    x=np.arange(len(sessions))
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True)
    axes[0].bar(x-.18,[int(r['usable_estimate_frames']) for r in sessions],.36,label='Usable first-half images')
    axes[0].bar(x+.18,[int(r['usable_heldout_frames']) for r in sessions],.36,label='Usable held-out images')
    axes[0].axhline(2,color='k',ls=':',label='At least 2 first-half hypotheses needed')
    axes[0].legend(fontsize=8);axes[0].set_ylabel('Images yielding up hypotheses')
    axes[0].set_title('Curved-edge ray-plane method: fixed split and quality screens')
    axes[1].bar(x,[int(r['accepted']=='True') for r in sessions],color=['#2980b9' if r['accepted']=='True' else '#999999' for r in sessions])
    axes[1].set_ylabel('Session hypothesis available (0/1)');axes[1].set_ylim(0,1.2)
    axes[1].set_xticks(x);axes[1].set_xticklabels([names[r['session']] for r in sessions],rotation=25,ha='right',fontsize=8)
    for ax in axes:ax.grid(axis='y',alpha=.2)
    fig.suptitle('86 native samples / 9 sessions: ordinary LSD 0 sessions; curved edges 1 CONDITIONAL hypothesis')
    fig.tight_layout();fig.savefig(output/'scene_up_coverage.png',dpi=150);plt.close(fig)

    chosen=[next(r for r in metric if r['dataset']=='sequence' and r['condition']==c) for c in ('cone_130','cone_200')]
    before_floor=[next(r for r in baseline if r['dataset']=='sequence' and r['condition']==c and r['model']=='angular_paper5_rotation' and r['method']=='floor_bottom_proxy') for c in ('cone_130','cone_200')]
    before_height=[next(r for r in baseline if r['dataset']=='sequence' and r['condition']==c and r['model']=='angular_paper5_rotation' and r['method']=='height_vertical_proxy') for c in ('cone_130','cone_200')]
    labels=('Placed 1.30 m\n218/218 valid frames','Placed 2.00 m\n541/548 valid frames')
    fig,axes=plt.subplots(1,3,figsize=(13,4.8))
    axes[0].plot([0,1],[float(r['z_median_m']) for r in before_floor],'o--',label='Transferred paper-5 pose')
    axes[0].plot([0,1],[float(r['floor_forward_median_m']) for r in chosen],'o-',label='Scene-up hypothesis')
    axes[0].plot([0,1],[1.3,2.],'k_',ms=20,label='Placed near-edge reference')
    axes[0].set_ylabel('Floor-intersection distance (m)');axes[0].legend(fontsize=7)
    axes[1].plot([0,1],[float(r['height_forward_median_m']) for r in chosen],'o-',color='#d35400',label='Known-height hypothesis')
    axes[1].plot([0,1],[1.3,2.],'k_',ms=20,label='Placed near-edge reference')
    axes[1].set_ylabel('Height-only distance (m)');axes[1].legend(fontsize=7)
    axes[2].plot([0,1],[100*float(r['base_height_median_m']) for r in before_height],'o--',label='Transferred paper-5 pose')
    axes[2].plot([0,1],[100*float(r['height_base_median_m']) for r in chosen],'o-',label='Scene-up hypothesis')
    axes[2].axhline(0,color='k',ls=':');axes[2].set_ylabel('Known-height solved bottom height (cm)');axes[2].legend(fontsize=7)
    for ax in axes:ax.set_xticks([0,1]);ax.set_xticklabels(labels,fontsize=8);ax.grid(alpha=.25)
    fig.suptitle('SAME saved cone pixels; scene inference never uses cone size, endpoints or placed distance\nConditional yaw/59 cm height retained; known-height mismatch still remains')
    fig.tight_layout();fig.savefig(output/'sequence_metric_crosscheck.png',dpi=150);plt.close(fig)

    # Coordinate-only audit for manual inspection against UNEDITED original PNGs.
    lookup={(r['session'],r['frame']):r for r in frames}
    selection=[]
    for r in lines:
        frame=lookup[r['session'],r['frame']]
        if frame['accepted']!='True' or r['accepted']!='True':continue
        normal=np.array(json.loads(r['normal_json']));g=np.array(json.loads(frame['up_optical_json']))
        residual=float(np.degrees(np.arcsin(np.clip(abs(normal@g),0,1))))
        if residual<=1:
            points=np.array(json.loads(r['actual_edge_pixels_json']))
            selection.append(dict(session=r['session'],frame=r['frame'],role=frame['role'],line_index=r['line_index'],part=r['part'],
                source_native_png=frame['source_native_png'],first_native_json=json.dumps(points[0].tolist()),
                last_native_json=json.dumps(points[-1].tolist()),points=len(points),
                gravity_residual_deg=residual,physically_surveyed_vertical=False,usable_for_ffb=False))
    write_csv(output/'selected_scene_edges.csv',selection)
    suite=unittest.TestSuite()
    suite.addTests(unittest.TestLoader().discover(str(HERE),pattern='test_scene_geometry.py'))
    suite.addTests(unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_angular_fisheye_geometry.py'))
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (output/'test_log.txt').write_text(stream.getvalue())
    assert all(sha256(Path(p))==v for p,v in sources.items())
    record=dict(status='PASS_OFFLINE_SCENE_GEOMETRY_TESTS_NOT_FFB_APPROVAL' if result.wasSuccessful() else 'FAIL',
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        native_images=86,sessions=9,ordinary_lsd_accepted_frames=sum(r['accepted']=='True' for r in original),
        curved_accepted_frames=sum(r['accepted']=='True' for r in frames),curved_accepted_sessions=sum(r['accepted']=='True' for r in sessions),
        ordinary_reason_counts=dict(Counter(r['reason'] for r in original)),curved_reason_counts=dict(Counter(r['reason'] for r in frames)),
        source_sha256=sources,original_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'verification.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
