"""Numeric extraction diagnostics and native review manifest; no calibration."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256


def main():
    output=HERE/'diagnosis_r01'
    if output.exists():
        raise ValueError('no output overwrite')
    extraction=HERE/'extraction_r01/observations.json'
    j=json.loads(extraction.read_text())
    intake=json.loads((HERE/'intake_summary.json').read_text())
    counts=Counter(r['reason'] for r in j['attempts'])
    reviews=[]
    for r in j['retained_views']:
        # Recorded after viewing each of six full-native saved PNGs.
        assert r['frame'] in (1,51,55,61,68,77)
        reviews.append(dict(frame=r['frame'],native_png='../extraction_r01/'+r['native_png'],
            target_identity='person-held paper, not stationary window',assistant_native_identity_review=True,
            human_full_corner_review=False,planarity_not_established_from_fisheye_image=True,
            image_edited=False,png_sha256=r['png_sha256']))
    output.mkdir()
    write_csv(output/'target_review.csv',reviews)
    summary=dict(decision=j['decision'],calibration_fit_executed=False,K_D_produced=False,
        measured_square_mm=20.,frames=2844,attempts=len(j['attempts']),detected=sum(r['detected'] for r in j['attempts']),
        retained_views=len(j['retained_views']),retained_frame_numbers=[r['frame'] for r in j['retained_views']],
        retained_time_range_sec=[min(r['time_sec'] for r in j['retained_views']),max(r['time_sec'] for r in j['retained_views'])],
        reasons=dict(counts),all_retained_coverage=j['all_retained_coverage'],prefit_checks=j['prefit_checks'],
        fixed_window_retained_views=0,all_retained_assistant_identity_reviewed=True,
        human_full_corner_review=False,physical_board_flatness_not_confirmed=True,
        sample_is_not_all_frame_corner_search=True,thresholds_not_relaxed=True,
        raw_archive_unchanged=all(sha256(Path(p))==digest for p,digest in intake['source_sha256'].items()),
        physical_output=False,production_settings_changed=False,usable_for_ffb=False,
        source_sha256={str(p):sha256(p) for p in (extraction,HERE/'intake_summary.json',Path(__file__))})
    os.environ.setdefault('MPLCONFIGDIR',str(output/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(13,4),layout='constrained')
    observed=[r for r in j['attempts'] if r['median_spacing_px'] is not None]
    axes[0].plot([r['time_sec'] for r in observed],[r['median_spacing_px'] for r in observed],'.',label='all measured grid spacing')
    selected=j['retained_views']
    axes[0].plot([r['time_sec'] for r in selected],[r['median_spacing_px'] for r in selected],'o',mfc='none',label='distinct retained candidates')
    axes[0].axhline(8.,c='k',ls='--',label='unchanged 8 px screen')
    axes[0].set(xlabel='CSV elapsed time [s]',ylabel='Median adjacent corner spacing [px]',title='Usable-size grids mostly at the start')
    axes[0].legend(fontsize=6)
    axes[1].scatter([r['centre_x'] for r in selected],[r['centre_y'] for r in selected])
    for x in (640/3,1280/3): axes[1].axvline(x,c='gray',ls='--',lw=.7)
    for y in (240,480): axes[1].axhline(y,c='gray',ls='--',lw=.7)
    axes[1].set(xlim=(0,640),ylim=(720,0),xlabel='Native front-lens X [px]',ylabel='Native Y [px]',title='Six retained centres: one bin only\nNumerical chart, NOT a camera-image overlay')
    keys=list(counts)
    axes[2].barh(range(len(keys)),[counts[k] for k in keys])
    axes[2].set_yticks(range(len(keys)),[k.replace('_','\n') for k in keys],fontsize=6)
    axes[2].set(xlabel='Sample attempts',title='Failures and exclusions retained')
    for ax in axes: ax.grid(alpha=.2)
    fig.savefig(output/'extraction_diagnostics.png',dpi=150)
    plt.close(fig)
    summary['output_sha256']={p.name:sha256(p) for p in output.iterdir() if p.is_file()}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
