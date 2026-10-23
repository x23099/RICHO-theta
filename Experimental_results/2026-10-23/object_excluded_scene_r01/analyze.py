"""Saved native cone bbox exclusion of scene support, offline controls only."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
BANDS=HERE.parent/'scene_separate_bands_r01'
SUPPORT=HERE.parent/'lower_support_audit_r01'
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD),str(BANDS),str(UNIFORM)]
from cone_dataset import read_csv,write_csv,sha256
from cone_observation import checked_bbox
from angular_fisheye_geometry import camera_from_candidate
from scene_geometry import infer_up
from curve_geometry import extract_curve_planes
from band_geometry import extract_band,fuse_planes
from analyze_scenes import summarize_directions

MODES=('original_fusion','object_screen','reference_screen','object_and_reference')


def overlap_evidence(pixels,boxes):
    p=np.asarray(pixels,float)
    if p.ndim!=2 or p.shape[1]!=2 or not len(p) or not np.isfinite(p).all() or not np.equal(p,np.rint(p)).all():
        raise ValueError('actual finite integer native support required')
    if not ((p[:,0]>=0)&(p[:,0]<1280)&(p[:,1]>=0)&(p[:,1]<720)).all():raise ValueError('native support outside image')
    inside=np.zeros(len(p),bool);matched=[]
    for row in boxes:
        x1,y1,x2,y2=checked_bbox(row,1280,720)
        hit=(p[:,0]>=x1)&(p[:,0]<=x2)&(p[:,1]>=y1)&(p[:,1]<=y2)
        if hit.any():matched.append(int(row['prediction_index']))
        inside|=hit
    return dict(overlap_pixels=int(inside.sum()),support_pixels=len(p),overlap_fraction=float(inside.mean()),
                matched_prediction_indices_json=json.dumps(matched),object_overlap=bool(inside.any()))


def reference_filter(upper,lower,references):
    kept=list(upper);vetoed=[]
    n=np.array([r['normal'] for r in references]).reshape(-1,3)
    for row in lower:
        angle=np.degrees(np.arccos(np.clip(abs(n@np.array(row['normal'])),-1,1))) if len(n) else np.array([])
        if len(angle) and angle.min()<2:vetoed.append(row)
        else:kept.append(row)
    return kept,vetoed


def load_saved_boxes(samples):
    anchor=ROOT/'Experimental_results/2026-10-19/cone_support_extent_r01/results_r01/provenance.json'
    anchored=json.loads(anchor.read_text())['source_sha256'];sources={str(anchor):sha256(anchor)}
    frame_index={};preds=defaultdict(list);raw_by_session={}
    day=ROOT/'Experimental_results/2026-10-15'
    for name in ('cone_static_distance_r01','floor_cone_same_pose_analysis_r01'):
        folder=day/name/'inference_r01';provenance=folder/'provenance.json';meta=json.loads(provenance.read_text())
        assert meta['native_dimensions']==[1280,720] and meta['candidate']['confidence']==.5
        sources[str(provenance)]=sha256(provenance)
        for path in (folder/'frames.csv',folder/'predictions.csv'):
            assert sha256(path)==anchored[str(path)];sources[str(path)]=sha256(path)
        for path,hashes in meta['source_sessions'].items():raw_by_session[Path(path).name]=hashes['raw.avi']
        for r in read_csv(folder/'frames.csv'):
            key=r['session'],int(r['frame']);assert key not in frame_index;frame_index[key]=r
        for r in read_csv(folder/'predictions.csv'):
            checked_bbox(r,1280,720)
            assert int(r['class_id'])==0 and .5-1e-7<=float(r['confidence'])<=1
            preds[r['session'],int(r['frame'])].append(r)
    for key,r in frame_index.items():
        assert int(r['detections'])==len(preds[key])
        assert all(float(p['time_sec'])==float(r['time_sec']) for p in preds[key])
    coverage=[]
    for sample in samples:
        key=sample['session'],int(sample['frame']);present=key in frame_index
        if present:
            assert float(frame_index[key]['time_sec'])==float(sample['time_sec'])
            assert raw_by_session[key[0]]==sample['source_raw_sha256']
        coverage.append(dict(session=key[0],frame=key[1],role=sample['role'],saved_prediction_frame_present=present,
            saved_prediction_count=len(preds[key]) if present else None,
            state='saved_predictions' if present and preds[key] else 'saved_zero_predictions_NOT_ground_truth_absence' if present else 'unavailable',
            native_source_raw_sha256=sample['source_raw_sha256'],prediction_is_ground_truth=False))
    return frame_index,preds,coverage,sources


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new output required; no overwrite')
    prev_manifest=BANDS/'results_r01/summary.json';d=json.loads(prev_manifest.read_text())
    for name,h in d['output_sha256'].items():assert sha256(prev_manifest.parent/name)==h
    samples=read_csv(UNIFORM/'intake_r01/native_sample_manifest.csv')
    frame_index,preds,coverage,sources=load_saved_boxes(samples)
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    inputs=[Path(__file__),HERE/'method.md',prev_manifest,candidate,floor,ROOT/'src/cone_observation.py',ROOT/'src/cone_dataset.py',
        ROOT/'src/cone_detection_diagnostics.py',ROOT/'src/angular_fisheye_geometry.py',OLD/'curve_geometry.py',OLD/'scene_geometry.py',
        BANDS/'band_geometry.py',UNIFORM/'analyze_scenes.py',UNIFORM/'intake_r01/native_sample_manifest.csv',
        UNIFORM/'scene_results_r01/line_candidates.csv',BANDS/'results_r01/fused_plane_ledger.csv',
        BANDS/'results_r01/lower_line_candidates.csv',BANDS/'results_r01/image_diagnostics.csv',
        SUPPORT/'results_r01/counterfactual_images.csv',SUPPORT/'results_r01/actual_lower_support.csv']
    sources.update({str(p):sha256(p) for p in inputs})
    camera=camera_from_candidate(json.loads(candidate.read_text()));tf=json.loads(floor.read_text())
    T=np.array(tf['transform_target_from_source']);prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    upper_records=read_csv(UNIFORM/'scene_results_r01/line_candidates.csv')
    lower_records=read_csv(BANDS/'results_r01/lower_line_candidates.csv')
    old_lines={(r['session'],int(r['frame']),band,int(r['line_index']),int(r['part'])):r
               for band,rows in [('upper',upper_records),('lower',lower_records)] for r in rows}
    fused=defaultdict(list);all_upper=defaultdict(list)
    for r in read_csv(BANDS/'results_r01/fused_plane_ledger.csv'):
        fused[r['session'],int(r['frame'])].append(dict(band=r['band'],line_index=int(r['line_index']),part=int(r['part']),normal=json.loads(r['normal_json'])))
    for r in upper_records:
        if r['reason'] in ('accepted_plane','duplicate_ray_plane'):
            all_upper[r['session'],int(r['frame'])].append(dict(band='upper',line_index=int(r['line_index']),part=int(r['part']),normal=json.loads(r['normal_json'])))
    baseline={(r['session'],int(r['frame'])):r for r in read_csv(BANDS/'results_r01/image_diagnostics.csv') if r['mode']=='late_fusion'}
    old_strict={(r['session'],int(r['frame'])):r for r in read_csv(SUPPORT/'results_r01/counterfactual_images.csv')}
    frames=[];line_masks=[];mode_votes=[];native_count=0
    for sample in samples:
        key=sample['session'],int(sample['frame']);members=fused[key]
        upper=[r for r in members if r['band']=='upper'];lower=[r for r in members if r['band']=='lower']
        strict,_=reference_filter(upper,lower,all_upper[key])
        variants={'original_fusion':members,'reference_screen':strict}
        if key in frame_index:
            path=Path(sample['source_native_png']);assert sha256(path)==sample['png_sha256'];sources[str(path)]=sample['png_sha256']
            image=cv2.imread(str(path));native_count+=1
            curves_by_band={'upper':extract_curve_planes(image,camera),'lower':extract_band(image,camera,band='lower')}
            kept_by_band={};background_refs=[]
            for band,curves in curves_by_band.items():
                eligible=[]
                for r in curves:
                    pixels=np.array(r['actual_edge_pixels_json']);old=old_lines[key[0],key[1],band,r['line_index'],r['part']]
                    assert hashlib.sha256(pixels.astype('<i4').tobytes()).hexdigest()==old['native_points_sha256']
                    assert r['reason']==old['reason'] and r['accepted']==(old['accepted']=='True')
                    if r.get('normal') is None:continue
                    mask=overlap_evidence(pixels,preds[key])
                    entry=dict(session=key[0],frame=key[1],role=sample['role'],band=band,line_index=r['line_index'],part=r['part'],
                        original_accepted=r['accepted'],original_reason=r['reason'],
                        first_native_json=json.dumps(pixels[0].tolist()),last_native_json=json.dumps(pixels[-1].tolist()),
                        native_points_sha256=old['native_points_sha256'],**mask,usable_for_ffb=False)
                    line_masks.append(entry)
                    row=dict(band=band,line_index=r['line_index'],part=r['part'],normal=r['normal'])
                    if not mask['object_overlap']:
                        if r['accepted']:eligible.append(row)
                        if band=='upper' and r['reason'] in ('accepted_plane','duplicate_ray_plane'):background_refs.append(row)
                kept_by_band[band]=eligible
            screened,_=fuse_planes(kept_by_band['upper'],kept_by_band['lower'])
            variants['object_screen']=screened
            # Match the ordinary fusion's priority/near-direction contract before the extra reference veto.
            variants['object_and_reference'],_=reference_filter([r for r in screened if r['band']=='upper'],
                [r for r in screened if r['band']=='lower'],background_refs)
        for mode in MODES:
            available=mode in variants
            votes=variants.get(mode,[])
            pose=infer_up(np.array([r['normal'] for r in votes]).reshape(-1,3),prior) if available else dict(accepted=False,reason='saved_bbox_stream_unavailable',inliers=0,up=None)
            if mode in ('original_fusion','reference_screen'):
                expected=baseline[key] if mode=='original_fusion' else old_strict[key]
                assert pose['accepted']==(expected['accepted']=='True') and pose['reason']==expected['reason']
                assert pose['inliers']==int(expected['inliers'])
                if pose['accepted']:np.testing.assert_array_equal(pose['up'],json.loads(expected['up_optical_json']))
            for i,r in enumerate(votes):mode_votes.append(dict(session=key[0],frame=key[1],mode=mode,vote_index=i,band=r['band'],line_index=r['line_index'],part=r['part'],usable_for_ffb=False))
            frames.append(dict(session=key[0],frame=key[1],time_sec=float(sample['time_sec']),role=sample['role'],mode=mode,
                bbox_stream_available=key in frame_index,bbox_count=len(preds[key]) if key in frame_index else None,
                accepted=pose['accepted'],reason=pose['reason'],inliers=pose['inliers'],up_optical=pose['up'],
                object_screen_applied=mode in ('object_screen','object_and_reference') and available,
                background_identity_verified=False,usable_for_ffb=False))
        print('processed',key,'boxes',len(preds[key]) if key in frame_index else 'unavailable',flush=True) if native_count in (1,50,100,150) and key in frame_index else None
    sessions=[]
    for session in sorted({r['session'] for r in samples}):
        for mode in MODES:
            summary=summarize_directions([r for r in frames if r['session']==session and r['mode']==mode],T)
            summary.pop('conditional_transform');summary['temporal_candidate_eligible']=summary.pop('metric_eligible')
            sessions.append(dict(session=session,mode=mode,**summary))
    output.mkdir()
    def structured(rows):return [{k+'_json' if k=='up_optical' else k:json.dumps(v) if k=='up_optical' else v for k,v in r.items()} for r in rows]
    for name,rows in [('bbox_coverage.csv',coverage),('line_object_overlap.csv',line_masks),('mode_vote_ledger.csv',mode_votes),
        ('image_diagnostics.csv',structured(frames)),('session_hypotheses.csv',structured(sessions))]:write_csv(output/name,rows)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    record=dict(status='COMPLETED_SAVED_OBJECT_BBOX_EXCLUSION_CONTROL_NOT_PRODUCTION_GATE',work_date='2026-10-23',source_sha256=sources,
        sampled_images=len(samples),native_reextracted_images=native_count,bbox_supported_images=sum(r['saved_prediction_frame_present'] for r in coverage),
        bbox_unsupported_images=sum(not r['saved_prediction_frame_present'] for r in coverage),
        accepted_images_by_mode={m:sum(r['accepted'] for r in frames if r['mode']==m) for m in MODES},
        temporal_passes_by_mode={m:sum(r['temporal_candidate_eligible'] for r in sessions if r['mode']==m) for m in MODES},
        metric_labels_used=False,new_model_inference=False,source_images_edited=False,production_settings_changed=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
