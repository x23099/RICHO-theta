"""Save numeric plots, verify untouched sample PNGs, and persist tests."""
from collections import Counter
import io
import json
from pathlib import Path
import sys
import unittest

import cv2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(HERE))
from cone_dataset import read_csv,write_csv,sha256

CONDITIONS=(('static','center_080'),('static','center_130'),('static','center_200'),('static','left_130'),
            ('static','right_130'),('sequence','cone_130'),('sequence','cone_200'),('paper_cone_20261019','cone_static'))
LABELS=('Static\n0.8 m','Static\n1.3 m','Static\n2.0 m','Left\n1.3 m','Right\n1.3 m','Sequence\n1.3 m','Sequence\n2.0 m','Oct19\n2.0 m')


def main():
    output=HERE/'plots_and_verification_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    output.mkdir()
    source=HERE/'results_r01/condition_summary.csv'
    sources={str(p):sha256(p) for p in (source,HERE/'results_r01/summary.json',Path(__file__),HERE/'test_contact_geometry.py')}
    rows=read_csv(source)
    lookup={(r['dataset'],r['condition'],r['model'],float(r['offset_m'])):r for r in rows}
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    for model,label,color in [('angular_nominal','Angular + nominal pose','#2980b9'),
                              ('angular_paper5_rotation','Angular + paper-5 pose','#d35400')]:
        chosen=[lookup[d,c,model,0.] for d,c in CONDITIONS]
        axes[0].plot(range(8),[float(r['tip_elevation_median_deg']) for r in chosen],'o-',label=label,color=color)
        lo=np.array([float(r['support_tip_height_min_median_m']) for r in chosen])
        hi=np.array([float(r['support_tip_height_max_median_m']) for r in chosen])
        axes[1].errorbar(np.arange(8)+(-.08 if model=='angular_nominal' else .08),100*(lo+hi)/2,
            yerr=50*(hi-lo),fmt='o-',capsize=4,label=label,color=color)
    axes[0].axhline(0,color='k',ls='--',label='Camera-level ray')
    axes[0].set_ylabel('Tip elevation (degrees)');axes[0].legend(fontsize=8)
    axes[0].set_title('Known 73 cm tip should be above a 59 cm camera (conditional geometry test)')
    axes[1].axhline(73,color='k',ls='--',label='User-measured total height: 73 cm')
    axes[1].axhline(59,color='gray',ls=':',label='User-measured camera height: 59 cm')
    axes[1].set_ylabel('Floor-implied tip height (cm)');axes[1].legend(fontsize=8)
    axes[1].set_title('Full observed central support: medians of per-frame min/max; NOT confidence intervals')
    for ax in axes:ax.grid(alpha=.25)
    axes[1].set_xticks(range(8));axes[1].set_xticklabels(LABELS,fontsize=8)
    fig.tight_layout();fig.savefig(output/'tip_and_floor_necessary_conditions.png',dpi=150);plt.close(fig)

    fig,axes=plt.subplots(3,1,figsize=(11,9),sharex=True)
    for offset,label,color in [(0.,'Vertical-segment assumption','#d35400'),(.1875,'18.75 cm forward-offset assumption','#2980b9')]:
        chosen=[lookup[d,c,'angular_paper5_rotation',offset] for d,c in CONDITIONS]
        axes[0].plot(range(8),[float(r['old_height_z_matched_median_m']) for r in chosen],'x--',color=color,label='Same X: '+label)
        axes[0].plot(range(8),[float(r['selected_height_z_median_m']) for r in chosen],'o-',color=color,label='Ray plane: '+label)
        axes[1].plot(range(8),[100*float(r['selected_height_base_height_median_m']) for r in chosen],'o-',color=color,label=label)
        axes[2].plot(range(8),[1000*float(r['selected_height_residual_median_m']) for r in chosen],'o-',color=color)
    axes[0].plot(range(8),[float(r['reference_z_m']) for r in chosen],'k_',markersize=17,label='Placed near-edge distance')
    axes[0].set_ylabel('Forward distance (m)');axes[0].legend(fontsize=7,ncol=2)
    axes[0].set_title('Same matched frames; intrinsics and paper-5 pose FIXED')
    axes[1].axhline(0,color='k',ls='--');axes[1].set_ylabel('Solved bottom height (cm)');axes[1].legend(fontsize=7)
    axes[2].set_ylabel('Known-segment residual (mm)')
    axes[2].set_title('Lower residual uses the SAME plane for selection and check; NOT independent accuracy proof')
    for ax in axes:ax.grid(alpha=.25)
    axes[2].set_xticks(range(8));axes[2].set_xticklabels(LABELS,fontsize=8)
    fig.tight_layout();fig.savefig(output/'same_frame_contact_selection.png',dpi=150);plt.close(fig)

    # Existing full-size PNGs only: compare to historical sample manifests.
    examples=[('2026-10-15/cone_static_distance_r01','raw_samples/center_200_f000421.png'),
              ('2026-10-15/floor_cone_same_pose_analysis_r01','raw_samples/same_pose_f001265.png'),
              ('2026-10-19/paper_cone_2m_validation_r01','raw_samples/paper_cone_f001019.png')]
    sample_rows=[]
    for study,name in examples:
        directory=ROOT/'Experimental_results'/study
        manifest=directory/'raw_sample_manifest.csv';png=directory/name
        sources[str(manifest)]=sha256(manifest);sources[str(png)]=sha256(png)
        matches=[r for r in read_csv(manifest) if r.get('file',r.get('path',r.get('output','')))==name]
        # Older intake manifests may store only the basename / a different path key.
        if not matches:
            matches=[r for r in read_csv(manifest) if any(str(v).endswith(name) for v in r.values())]
        assert len(matches)==1,(manifest,name)
        row=matches[0]
        expected=row.get('png_sha256',row.get('sha256'))
        assert sha256(png)==expected,(png,expected)
        image=cv2.imread(str(png));assert image.shape==(720,1280,3)
        sample_rows.append(dict(source_native_png=str(png),source_manifest=str(manifest),png_sha256=expected,
            frame=row.get('frame'),session=row.get('session'),width=1280,height=720,original_image_edited=False))
    write_csv(output/'native_sample_manifest.csv',sample_rows)
    suite=unittest.TestSuite()
    suite.addTests(unittest.TestLoader().discover(str(HERE),pattern='test_contact_geometry.py'))
    suite.addTests(unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_angular_fisheye_geometry.py'))
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (output/'test_log.txt').write_text(stream.getvalue())
    assert all(sha256(Path(p))==digest for p,digest in sources.items())
    record=dict(status='PASS_OFFLINE_CONTACT_CHECKS_NOT_METRIC_APPROVAL' if result.wasSuccessful() else 'FAIL',
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        source_sha256=sources,verified_unchanged_native_pngs=3,raw_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'verification.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
