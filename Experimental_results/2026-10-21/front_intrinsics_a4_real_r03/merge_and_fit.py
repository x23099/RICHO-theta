"""Frozen multi-session merge and one unchanged offline intrinsic fit attempt."""
from collections import Counter
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256, write_csv
from fisheye_intrinsic_calibration import Board, FRONT_ROI, SCREEN, corner_rms, coverage, partition_views, fit_candidate


def merge_sources(target, incoming):
    for path, digest in incoming.items():
        if path in target and target[path] != digest:
            raise ValueError('inconsistent source hashes')
        target[path] = digest


def merge_views(datasets):
    """Input order and per-source frames remain fixed; no residual-based selection."""
    selected, decisions = [], []
    for session, path, data in datasets:
        if [v['retained_index'] for v in data['retained_views']] != list(range(len(data['retained_views']))):
            raise ValueError('source view indices are not consecutive')
        for v in data['retained_views']:
            points = np.asarray(v['corners_native'])
            nearest = min((corner_rms(points,np.asarray(old['corners_native'])) for old in selected), default=None)
            row = dict(session=session, source_frame=v['frame'], source_time_sec=v['time_sec'],
                       source_observations=str(path), source_retained_index=v['retained_index'],
                       source_native_png=str(path.parent/v['native_png']), png_sha256=v['png_sha256'],
                       decoded_bgr_sha256=v['decoded_bgr_sha256'], nearest_prior_pose_rms_px=nearest)
            if nearest is not None and nearest < SCREEN['duplicate_rms_px']:
                decisions.append(dict(row,selected=False,reason='cross_session_near_duplicate'))
                continue
            selected.append(dict(row,merged_index=len(selected),corners_native=v['corners_native'],
                                 centre_x=v['centre_x'],centre_y=v['centre_y']))
            decisions.append(dict(row,selected=True,reason='selected_before_fit'))
    return selected, decisions


def plot_distribution(selected, train, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,2,figsize=(11,5),constrained_layout=True)
    sessions = list(dict.fromkeys(r['session'] for r in selected))
    for session, colour in zip(sessions,['tab:blue','tab:orange']):
        rows = [r for r in selected if r['session']==session]
        points = np.concatenate([r['corners_native'] for r in rows])
        axes[0].scatter(points[:,0],points[:,1],s=2,alpha=.22,c=colour)
        axes[0].scatter([r['centre_x'] for r in rows],[r['centre_y'] for r in rows],s=15,c=colour,label=session)
    for x in (640/3,1280/3):
        axes[0].axvline(x,c='grey',lw=.5)
    for y in (240,480):
        axes[0].axhline(y,c='grey',lw=.5)
    axes[0].set(xlim=(0,640),ylim=(720,0),xlabel='Native x [px]',ylabel='Native y [px]',
                title='r02 + r03 observations (no camera overlay)')
    axes[0].legend(fontsize=8)
    c=coverage([np.asarray(selected[i]['corners_native']) for i in train],FRONT_ROI)
    values=[c['span_fraction_x']*100,c['span_fraction_y']*100]
    axes[1].bar(['Training X span','Training Y span'],values,color=['tab:blue','tab:orange'])
    axes[1].axhline(35,c='black',ls='--',label='35% pre-fit screen')
    axes[1].set(ylim=(0,100),ylabel='Corner span / ROI [%]',title=f"Train centre bins: {c['centre_bins']} / required 4")
    for i,value in enumerate(values):
        axes[1].text(i,value+2,f'{value:.2f}%',ha='center')
    axes[1].legend()
    fig.savefig(output/'merged_coverage.png',dpi=150)
    plt.close(fig)


def main():
    output = HERE/'combined_candidate_r01'
    if output.exists():
        raise ValueError('no merge/fit overwrite')
    bases=[HERE.parent/'front_intrinsics_a4_real_r02',HERE]
    sources={str(p):sha256(p) for p in (HERE/'method.md',HERE/'target_review.json',Path(__file__),
        ROOT/'src/fisheye_intrinsic_calibration.py')}
    review=json.loads((HERE/'target_review.json').read_text())
    if not review['moving_board_identity_representatives_confirmed']:
        raise ValueError('native target identity review required')
    datasets,metadata=[],[]
    for base in bases:
        path=base/'extraction_r01/observations.json'
        data=json.loads(path.read_text())
        if (data['image_size']!=[1280,720] or data['roi_native_xywh']!=list(FRONT_ROI)
            or data['selected_lens']!='front_left' or data['board']!=dict(inner_columns=9,inner_rows=6,square_mm=20.)):
            raise ValueError('incompatible source board or native coordinate domain')
        merge_sources(sources,data['source_sha256'])
        merge_sources(sources,{str(path):sha256(path)})
        intake_path=base/'intake_summary.json'
        merge_sources(sources,{str(intake_path):sha256(intake_path)})
        intake=json.loads(intake_path.read_text())
        if intake['integrity']['decision']!='PASS':
            raise ValueError('source recording integrity failed')
        datasets.append((base.name,path,data))
        metadata.append(intake['metadata'])
    keys=['device','requested_camera_width','requested_camera_height','requested_camera_fps','camera_capture_properties']
    compatibility={k:metadata[0].get(k)==metadata[1].get(k) for k in keys}
    if not all(compatibility.values()):
        raise ValueError('reported capture settings mismatch; no automatic merge')
    assert all(sha256(Path(p))==digest for p,digest in sources.items())
    selected,decisions=merge_views(datasets)
    for r in selected:
        png=Path(r['source_native_png'])
        if sha256(png)!=r['png_sha256']:
            raise ValueError('native PNG hash mismatch')
    train,validation=partition_views(selected)
    distribution=coverage([np.asarray(selected[i]['corners_native']) for i in train],FRONT_ROI)
    prefit_checks=dict(enough_views=len(selected)>=20,centre_bins=distribution['centre_bins']>=SCREEN['centre_bins'],
        x_span=distribution['span_fraction_x']>=SCREEN['image_span_fraction'],
        y_span=distribution['span_fraction_y']>=SCREEN['image_span_fraction'])
    output.mkdir()
    manifest=[dict(r,split='train' if r['merged_index'] in train else 'pose_validation_only')
              for r in selected]
    # Persist full multi-session coordinates and fixed split before calling any solver.
    combined=dict(schema='multi_session_native_front_fisheye_observations_v1',source_sha256=sources,
        camera_model='opencv_fisheye_4coef',image_size=[1280,720],roi_native_xywh=list(FRONT_ROI),
        board=datasets[0][2]['board'],selected_views=manifest,train_indices=train,validation_indices=validation,
        merge_order=[d[0] for d in datasets],capture_settings_equal=compatibility,
        capture_metadata_cannot_prove_unchanged_optical_state=True,board_size_basis='same 20 mm r02 board supplement',
        prefit_checks=prefit_checks,train_coverage=distribution,physical_output=False,usable_for_ffb=False)
    (output/'merged_observations.json').write_text(json.dumps(combined,indent=2)+'\n')
    write_csv(output/'merge_decisions.csv',decisions)
    write_csv(output/'selected_view_manifest.csv',[{k:v for k,v in r.items() if k!='corners_native'} for r in manifest])
    plot_distribution(selected,train,output)
    summary=dict(decision='NO_FIT_INSUFFICIENT_OBSERVATIONS',source_counts={d[0]:len(d[2]['retained_views']) for d in datasets},
        selected_counts=dict(Counter(r['session'] for r in selected)),selected_view_count=len(selected),
        near_duplicates_rejected=sum(not r['selected'] for r in decisions),train_views=len(train),validation_views=len(validation),
        prefit_checks=prefit_checks,train_coverage=distribution,intrinsic_solver_attempted=False,
        physical_output=False,original_images_edited=False,production_settings_changed=False,
        usable_for_ffb=False,source_sha256=sources,merged_observations_sha256=sha256(output/'merged_observations.json'))
    if all(prefit_checks.values()):
        summary['intrinsic_solver_attempted']=True
        try:
            candidate=fit_candidate([r['corners_native'] for r in selected],Board(**datasets[0][2]['board']))
            candidate.update(source_sha256=sources,merged_observations_sha256=summary['merged_observations_sha256'],
                source_view_mapping=[dict(merged_index=r['merged_index'],session=r['session'],frame=r['source_frame']) for r in selected])
            (output/'intrinsics_candidate.json').write_text(json.dumps(candidate,indent=2)+'\n')
            per_view=[dict(candidate['per_view'][i],session=selected[r['view_index']]['session'],
                          source_frame=selected[r['view_index']]['source_frame']) for i,r in enumerate(candidate['per_view'])]
            write_csv(output/'reprojection_by_view.csv',per_view)
            summary.update(decision=candidate['decision'],calibration_rms_px=candidate['calibration_rms_px'],
                pose_validation_rms_px=candidate['pose_validation_rms_px'],normal_spread_deg=candidate['normal_spread_deg'],
                checks=candidate['checks'],K=candidate['K'],D=candidate['D'])
        except (ValueError,RuntimeError,cv2.error) as error:
            summary.update(decision='SOLVER_REJECTED_NO_APPROVED_INTRINSICS',error_type=type(error).__name__,error=str(error))
    assert all(sha256(Path(p))==digest for p,digest in sources.items())
    summary['output_sha256']={p.name:sha256(p) for p in output.iterdir() if p.is_file()}
    (output/'run_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':
    main()
