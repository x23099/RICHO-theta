"""Frozen all-frame comparison of user-measured cone height; no live output."""
from collections import defaultdict, Counter
import importlib.util
import json
import os
from pathlib import Path
import sys
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WIDTH = HERE.parent/'cone_known_size_pinhole_r01'
DAY19 = ROOT/'Experimental_results/2026-10-19'
for path in (ROOT/'src', WIDTH, DAY19/'cone_support_extent_r01', DAY19/'cone_bottom_ties_r01'):
    sys.path.insert(0,str(path))
from cone_dataset import read_csv, write_csv, sha256
from cone_observation import ConeGroundProjector
from fisheye_floor_geometry import legacy_front_diagnostic_geometry
from known_width import raw_to_rectified, VIRTUAL_K
from known_height import height_position, contour_pair, empty, HEIGHT_M, BASE_HALF_M
from bottom_points import extract_bottoms
from support import native_contour

spec = importlib.util.spec_from_file_location('frozen_width_study', WIDTH/'analyze.py')
width = importlib.util.module_from_spec(spec)
spec.loader.exec_module(width)

METHODS = {'colour_vertical_proxy':0., 'colour_near_edge_offset_assumption':BASE_HALF_M,
           'bbox_vertical_control':0.}


def red_contour(image):
    # Same fixed ROI/guards as previous width study; no detector claimed.
    x,y,w,h = 285,290,65,95
    hsv=cv2.cvtColor(image[y:y+h,x:x+w],cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(0,80,30),(10,255,255)) | cv2.inRange(hsv,(170,80,30),(179,255,255))
    contours=sorted((c for c in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)[0]
                     if cv2.contourArea(c)>=20),key=cv2.contourArea,reverse=True)
    if not contours:
        return None,'no_red_component'
    if len(contours)>1 and cv2.contourArea(contours[1]) >= .25*cv2.contourArea(contours[0]):
        return None,'ambiguous_red_components'
    bx,by,bw,bh=cv2.boundingRect(contours[0])
    if bx==0 or by==0 or bx+bw>=w or by+bh>=h:
        return None,'roi_edge_truncation'
    if bw<5 or bh<8 or len(np.unique(contours[0][:,0,0]))<8:
        return None,'insufficient_red_extent'
    return contours[0][:,0,:]+[x,y],'known_red_roi_NOT_YOLO'


def key(r):
    return r['dataset'],r['session'],int(r['frame'])


def load_pixels():
    provenance=json.loads((WIDTH/'results_r01/provenance.json').read_text())
    for path,digest in provenance['source_sha256'].items():
        assert sha256(Path(path))==digest, path
    for name,digest in provenance['output_sha256'].items():
        assert sha256(WIDTH/'results_r01'/name)==digest, name
    baseline=[r for r in read_csv(WIDTH/'results_r01/all_frame_estimates.csv')
              if r['model']=='height_only59' and r['method']=='visible_full_span']
    sources,geometries,refs,conditions,phases,hashes=width.old.load_inputs()
    scope=ConeGroundProjector(geometries['recorded58'],width=1280,height=720,front_lens='left',confidence_threshold=.5)
    _,candidates=width.old.make_ledger(sources,scope,refs,conditions,phases)
    old15=ROOT/'Experimental_results/2026-10-15'
    a=json.loads((old15/'cone_static_distance_r01/intake_summary.json').read_text())
    b=json.loads((old15/'floor_cone_same_pose_analysis_r01/intake_summary.json').read_text())
    c=json.loads((DAY19/'paper_cone_2m_validation_r01/intake_summary.json').read_text())
    directories=[('static',Path(r['path'])) for r in a['inputs']]+[
        ('sequence',Path(b['session'])),('paper_cone_20261019',Path(c['session']))]
    groups=defaultdict(list)
    for r in baseline:
        groups[r['dataset'],r['session']].append(r)
    observations=[]
    for dataset,directory in directories:
        frames=groups[dataset,directory.name]
        raw_csv=read_csv(directory/'detections.csv')
        assert len(frames)==len(raw_csv)
        for name in ('raw.avi','detections.csv','metadata.json'):
            p=directory/name
            hashes[str(p)]=sha256(p)
        cap=cv2.VideoCapture(str(directory/'raw.avi'))
        assert cap.isOpened()
        try:
            for source,original in zip(frames,raw_csv):
                ok,image=cap.read()
                assert ok and image.shape==(720,1280,3)
                assert int(original['frame'])==int(source['frame']) and float(original['time_sec'])==float(source['time_sec'])
                boxes=candidates.get(key(source),[])
                if dataset=='paper_cone_20261019':
                    contour,reason=red_contour(image)
                elif len(boxes)==1:
                    contour,legacy=native_contour(image,boxes[0],extract_bottoms)
                    reason=legacy['reason']
                else:
                    contour,reason=None,'no_unique_saved_bbox'
                if contour is not None:
                    xs=np.unique(contour[:,0])
                    endpoints=np.array([[x,max(contour[contour[:,0]==x,1])] for x in (xs[0],xs[-1])])
                    assert source['left_x'], 'new colour span absent in frozen width data'
                    expected=np.array([[float(source['left_x']),float(source['left_y'])],
                                       [float(source['right_x']),float(source['right_y'])]])
                    np.testing.assert_array_equal(endpoints,expected)
                    pair=contour_pair(contour)
                else:
                    assert not source['left_x'], 'frozen colour span unexpectedly lost'
                    pair=None
                bbox=None
                if len(boxes)==1:
                    box=boxes[0]
                    x=(float(box['x1'])+float(box['x2']))/2
                    bbox=np.array([[x,float(box['y1'])],[x,float(box['y2'])]])
                observations.append(dict(dataset=dataset,session=directory.name,frame=int(source['frame']),
                    time_sec=float(source['time_sec']),condition=source['condition'],
                    reference_z_m=float(source['reference_z_m']) if source['reference_z_m'] else None,
                    reference_x_m=float(source['reference_x_m']) if source['reference_x_m'] else None,
                    quality_accepted=source['quality_accepted']=='True',colour_reason=reason,
                    native_colour_pair_json=json.dumps(pair.tolist()) if pair is not None else '',
                    native_bbox_pair_json=json.dumps(bbox.tolist()) if bbox is not None else '',
                    previous_width_z_m=float(source['z_forward_m']) if source['estimated']=='True' else None,
                    previous_width_floor_z_m=float(source['floor_z_m']) if source['floor_z_m'] else None))
            assert not cap.read()[0], 'extra raw frames'
        finally:
            cap.release()
        print('Native pixels',dataset,directory.name,len(frames),flush=True)
    assert len(observations)==6876 and len({key(r) for r in observations})==6876
    paths=[Path(__file__),HERE/'known_height.py',HERE/'method.md',
           WIDTH/'results_r01/provenance.json',WIDTH/'results_r01/all_frame_estimates.csv',
           DAY19/'cone_support_extent_r01/support.py',DAY19/'cone_bottom_ties_r01/bottom_points.py']
    hashes.update({str(p):sha256(p) for p in paths})
    return observations,geometries,hashes


def replay(pixels,geometries):
    output=[]
    for source in pixels:
        for model,parameters in geometries.items():
            _,T=legacy_front_diagnostic_geometry(parameters)
            for method,offset in METHODS.items():
                field='native_bbox_pair_json' if method=='bbox_vertical_control' else 'native_colour_pair_json'
                row=dict(**source,model=model,method=method,tip_forward_offset_m=offset,
                         rectified_pair_json='',height_m=HEIGHT_M)
                if not source[field]:
                    row.update(empty('no_observed_pair'))
                else:
                    uv=raw_to_rectified(json.loads(source[field]),parameters)
                    if uv is None:
                        row.update(empty('outside_native_lens_or_virtual_view'))
                    else:
                        row.update(height_position(uv,VIRTUAL_K,T,tip_forward_offset_m=offset),
                                   rectified_pair_json=json.dumps(uv.tolist()))
                output.append(row)
    return output


def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        groups[r['dataset'],r['condition'],r['model'],r['method']].append(r)
    output=[]
    for (dataset,condition,model,method),group in sorted(groups.items()):
        for population in ('all_estimates','support_time_accepted','matched_width_frames'):
            selected=[r for r in group if r['estimated'] and (
                population=='all_estimates' or population=='support_time_accepted' and r['quality_accepted']
                or population=='matched_width_frames' and r['previous_width_z_m'] is not None)]
            ref=group[0]['reference_z_m']
            med=lambda field:float(np.median([r[field] for r in selected])) if selected else None
            z=np.array([r['z_forward_m'] for r in selected])
            dz=z-ref if ref is not None else None
            old=[r['previous_width_z_m'] for r in selected if r['previous_width_z_m'] is not None]
            output.append(dict(dataset=dataset,condition=condition,model=model,method=method,population=population,
                frames=len(group),estimated_frames=len(selected),reference_z_m=ref,z_median_m=med('z_forward_m'),
                z_bias_m=float(np.median(dz)) if dz is not None and len(dz) else None,
                z_abs_error_p95_m=float(np.percentile(abs(dz),95)) if dz is not None and len(dz) else None,
                base_height_median_m=med('base_height_m'),residual_median_m=med('residual_m'),
                consistent_frames=sum(r['segment_consistent'] for r in selected),
                outside_range_frames=sum(not r['in_diagnostic_range'] for r in selected),
                matched_width_z_median_m=float(np.median(old)) if population=='matched_width_frames' and old else None,
                missing_reasons=json.dumps(dict(Counter(r['reason'] for r in group if not r['estimated']))),usable_for_ffb=False))
    return output


def plot(summary,rows,output):
    os.environ.setdefault('MPLCONFIGDIR',str(output/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    keys=sorted({(r['dataset'],r['condition']) for r in summary if r['reference_z_m'] is not None})
    fig,axes=plt.subplots(2,1,figsize=(12,7),layout='constrained')
    for i,method in enumerate(METHODS):
        chosen=[next(r for r in summary if (r['dataset'],r['condition'])==k and r['model']=='height_only59'
                     and r['method']==method and r['population']=='all_estimates') for k in keys]
        x=np.arange(len(keys))+(i-1)*.24
        axes[0].bar(x,[r['z_median_m'] if r['z_median_m'] is not None else np.nan for r in chosen],.23,label=method)
        axes[1].plot(np.arange(len(keys)),[r['z_abs_error_p95_m'] for r in chosen],'o-',label=method)
    axes[0].plot(np.arange(len(keys)),[next(r['reference_z_m'] for r in summary if (r['dataset'],r['condition'])==k) for k in keys],
                 'k_',ms=25,label='nominal near-edge Z')
    axes[0].set(ylabel='Forward Z [m]',title='Measured height 0.73 m / fixed uncalibrated camera model')
    axes[1].axhline(.2,c='k',ls='--',label='development screen 0.2 m')
    axes[1].set(ylabel='p95 absolute difference [m]',title='All estimates retained; no reference-distance fitting')
    for ax in axes:
        ax.set_xticks(np.arange(len(keys)),[d.replace('paper_cone_20261019','new19')+'\n'+c for d,c in keys],fontsize=8)
        ax.legend(fontsize=8)
        ax.grid(axis='y',alpha=.2)
    fig.savefig(output/'height_comparison.png',dpi=150)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for method in ('colour_vertical_proxy','colour_near_edge_offset_assumption'):
        chosen=[r for r in rows if r['dataset']=='sequence' and r['model']=='height_only59' and r['method']==method and 1100<=r['frame']<=1160]
        axes[0].plot([r['frame'] for r in chosen],[r['z_forward_m'] if r['estimated'] else np.nan for r in chosen],'.-',label=method)
    axes[0].axhline(2.,c='k',ls='--')
    axes[0].set(xlabel='Original frame',ylabel='Forward Z [m]',title='Occlusion / recovery; no interpolation')
    for method in ('colour_vertical_proxy','colour_near_edge_offset_assumption'):
        chosen=[r for r in summary if r['model']=='height_only59' and r['method']==method and r['population']=='all_estimates' and r['reference_z_m'] is not None]
        axes[1].plot(np.arange(len(chosen)),[r['base_height_median_m'] for r in chosen],'o-',label=method)
    axes[1].axhline(0,c='k',ls='--')
    axes[1].set(xlabel='Conditions in comparison order',ylabel='Estimated base height [m]',title='Diagnostic only: base NOT forced onto floor')
    for ax in axes:
        ax.legend(fontsize=7)
        ax.grid(alpha=.2)
    fig.savefig(output/'height_occlusion_and_floor_residual.png',dpi=150)
    plt.close(fig)


def main():
    output=HERE/'results_r01'
    if output.exists():
        raise ValueError('new output required; no overwrite')
    pixels,geometries,hashes=load_pixels()
    rows=replay(pixels,geometries)
    summary=summarize(rows)
    assert len(rows)==6876*len(geometries)*len(METHODS)
    assert all(sha256(Path(p))==digest for p,digest in hashes.items())
    screen={}
    for method in METHODS:
        evaluated=[r for r in summary if r['model']=='height_only59' and r['method']==method
                   and r['population']=='all_estimates' and r['reference_z_m'] is not None]
        failed=[dict(condition=r['condition'],dataset=r['dataset'],bias=r['z_bias_m'],p95=r['z_abs_error_p95_m']) for r in evaluated
                if r['z_bias_m'] is None or abs(r['z_bias_m'])>.1 or r['z_abs_error_p95_m']>.2]
        screen[method]=dict(evaluation_conditions=len(evaluated),failures=failed,
            decision='DEFER_UNVERIFIED_HEIGHT_CORRESPONDENCE' if failed else 'PROMISING_NOT_CALIBRATION_OR_RUNTIME_APPROVAL')
    output.mkdir()
    write_csv(output/'observed_pixels.csv',pixels)
    write_csv(output/'all_frame_estimates.csv',rows)
    write_csv(output/'summary.csv',summary)
    (output/'screen.json').write_text(json.dumps(screen,indent=2)+'\n')
    plot(summary,rows,output)
    provenance=dict(frames=len(pixels),rows=len(rows),models=geometries,methods=METHODS,height_m=HEIGHT_M,
        measured_height_source='user_reply_2026-10-21_floor_to_tip_including_base_73cm',
        geometry_or_size_fit=False,new_yolo_inference=False,live_tf=False,physical_output=False,
        production_settings_changed=False,calibrated_intrinsics=False,physical_endpoint_correspondence_verified=False,
        usable_for_ffb=False,source_sha256=hashes,output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps({'screen':screen,'primary':[r for r in summary if r['model']=='height_only59' and r['population']=='all_estimates' and r['reference_z_m'] is not None]},indent=2))


if __name__=='__main__':
    main()
