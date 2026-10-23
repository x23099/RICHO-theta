"""One vote per seam-supported group; explicit ambiguity, no metric consumer."""
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OBJECT=HERE.parent/'object_excluded_scene_r01'
BANDS=HERE.parent/'scene_separate_bands_r01'
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(ROOT/'src'),str(OLD),str(BANDS),str(UNIFORM)]
from cone_dataset import read_csv,write_csv,sha256
from scene_geometry import infer_up,plane_from_pixels
from angular_fisheye_geometry import camera_from_candidate
from curve_geometry import extract_curve_planes
from band_geometry import extract_band,fuse_planes
from analyze_scenes import summarize_directions
spec=importlib.util.spec_from_file_location('frozen_object_screen_for_join',OBJECT/'analyze.py')
object_screen=importlib.util.module_from_spec(spec);spec.loader.exec_module(object_screen)

MODES=('object_reference','join_count_only','join_refit')


def key(row):return int(row['line_index']),int(row['part'])


def normal_angle(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float)
    return float(np.degrees(np.arccos(np.clip(abs(a@b),-1,1))))


def recover_owners(curves):
    """Reproduce the frozen within-upper dedup order, without changing it."""
    candidates=[r for r in curves if r['reason'] in ('accepted_plane','duplicate_ray_plane')]
    kept=[];owners={}
    for row in sorted(candidates,key=lambda r:-r['native_y_span']):
        owner=next((r for r in kept if normal_angle(row['normal'],r['normal'])<2),None)
        if owner is None:
            assert row['accepted'],'frozen owner mismatch'
            kept.append(row);owners[key(row)]=key(row)
        else:
            assert not row['accepted'] and row['reason']=='duplicate_ray_plane'
            owners[key(row)]=key(owner)
    return owners


def near_seam(upper,lower):
    upper=np.asarray(upper,float);lower=np.asarray(lower,float)
    if (upper.ndim!=2 or lower.ndim!=2 or upper.shape[1:]!=(2,) or lower.shape[1:]!=(2,)
        or not len(upper) or not len(lower) or not np.isfinite(upper).all() or not np.isfinite(lower).all()):
        raise ValueError('finite actual support required')
    delta=lower[0]-upper[-1]
    return bool(1<=delta[1]<=6 and abs(delta[0])<=6)


def choose_links(links):
    """Only one owner and one lower candidate; never use pose/metric labels."""
    by_lower=defaultdict(list)
    for row in links:
        if row['combined_accepted']:by_lower[row['lower_key']].append(row)
    owner_lower=defaultdict(set)
    for lower,rows in by_lower.items():
        for row in rows:owner_lower[row['owner_key']].add(lower)
    chosen={};status={}
    for lower,rows in sorted(by_lower.items()):
        owners={r['owner_key'] for r in rows}
        if len(owners)!=1:status[lower]='multiple_upper_owner_groups';continue
        owner=next(iter(owners))
        if len(owner_lower[owner])!=1:status[lower]='multiple_lower_candidates_for_owner';continue
        chosen[lower]=min(rows,key=lambda r:(r['combined_rms_deg'],r['combined_max_deg'],-r['combined_points'],r['upper_key']))
        status[lower]='one_observed_group_join'
    return chosen,status


def dedup_votes(rows):
    kept=[];removed=[]
    for row in rows:
        owner=next((r for r in kept if normal_angle(row['normal'],r['normal'])<2),None)
        if owner is None:kept.append(row)
        else:removed.append((row,owner))
    return kept,removed


def build_join_votes(upper,lower,references,chosen,status,*,refit):
    replacements={r['owner_key']:r for r in chosen.values()}
    votes=[]
    for row in upper:
        link=replacements.get(key(row))
        votes.append(dict(row,normal=link['combined_normal'] if refit and link else row['normal'],
            joined_lower_key=link['lower_key'] if refit and link else None))
    for row in lower:
        if key(row) in status:continue  # consumed or ambiguous, neither earns a second vote
        if any(normal_angle(row['normal'],r['normal'])<2 for r in references):continue
        votes.append(dict(row,joined_lower_key=None))
    return dedup_votes(votes)


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new complete output required')
    old_manifest=OBJECT/'results_r01/summary.json';manifest=json.loads(old_manifest.read_text())
    for name,h in manifest['output_sha256'].items():assert sha256(old_manifest.parent/name)==h
    for p,h in manifest['source_sha256'].items():assert sha256(Path(p))==h
    samples=read_csv(UNIFORM/'intake_r01/native_sample_manifest.csv')
    frame_index,predictions,coverage,sources=object_screen.load_saved_boxes(samples)
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    inputs=[Path(__file__),HERE/'method.md',OBJECT/'analyze.py',old_manifest,candidate,floor,OLD/'scene_geometry.py',
        OLD/'curve_geometry.py',BANDS/'band_geometry.py',UNIFORM/'analyze_scenes.py',ROOT/'src/angular_fisheye_geometry.py',
        ROOT/'src/cone_dataset.py',UNIFORM/'intake_r01/native_sample_manifest.csv',
        UNIFORM/'scene_results_r01/line_candidates.csv',BANDS/'results_r01/lower_line_candidates.csv',OBJECT/'results_r01/image_diagnostics.csv']
    sources.update({str(p):sha256(p) for p in inputs})
    camera=camera_from_candidate(json.loads(candidate.read_text()));tf=json.loads(floor.read_text())
    T=np.array(tf['transform_target_from_source']);prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    old_index={(r['session'],int(r['frame'])):r for r in read_csv(OBJECT/'results_r01/image_diagnostics.csv') if r['mode']=='object_and_reference'}
    expected={(r['session'],int(r['frame']),band,int(r['line_index']),int(r['part'])):r
        for band,path in [('upper',UNIFORM/'scene_results_r01/line_candidates.csv'),('lower',BANDS/'results_r01/lower_line_candidates.csv')]
        for r in read_csv(path)}
    frames=[];votes_rows=[];link_rows=[];decision_rows=[];owner_rows=[];merge_rows=[];removed_rows=[]
    processed=0
    for sample in samples:
        identity=sample['session'],int(sample['frame']);variants={}
        if identity in frame_index:
            path=Path(sample['source_native_png']);assert sha256(path)==sample['png_sha256'];sources[str(path)]=sample['png_sha256']
            image=cv2.imread(str(path));upper_raw=extract_curve_planes(image,camera);lower_raw=extract_band(image,camera,band='lower')
            owners=recover_owners(upper_raw);eligible={};all_allowed={}
            for band,curves in [('upper',upper_raw),('lower',lower_raw)]:
                eligible[band]=[];all_allowed[band]=[]
                for curve in curves:
                    points=np.array(curve['actual_edge_pixels_json']);old=expected[(*identity,band,*key(curve))]
                    assert hashlib.sha256(points.astype('<i4').tobytes()).hexdigest()==old['native_points_sha256']
                    assert curve['reason']==old['reason'] and curve['accepted']==(old['accepted']=='True')
                    if curve.get('normal') is None:continue
                    if object_screen.overlap_evidence(points,predictions[identity])['object_overlap']:continue
                    row=dict(band=band,line_index=curve['line_index'],part=curve['part'],normal=curve['normal'],pixels=points,
                        first_native_json=json.dumps(points[0].tolist()),last_native_json=json.dumps(points[-1].tolist()))
                    if curve['accepted']:eligible[band].append(row)
                    if curve['reason'] in ('accepted_plane','duplicate_ray_plane'):all_allowed[band].append(row)
            upper,lower=eligible['upper'],eligible['lower'];owner_ids={key(r) for r in upper}
            references=all_allowed['upper']
            for raw in upper_raw:
                if key(raw) in owners:
                    owner_rows.append(dict(session=identity[0],frame=identity[1],upper_key_json=json.dumps(key(raw)),
                        owner_key_json=json.dumps(owners[key(raw)]),owner_survived_object_screen=owners[key(raw)] in owner_ids,
                        original_accepted=raw['accepted']))
            links=[]
            for low in lower:
                for up in references:
                    owner=owners[key(up)]
                    if owner not in owner_ids or not near_seam(up['pixels'],low['pixels']):continue
                    combined=np.concatenate((up['pixels'],low['pixels']))
                    fit=plane_from_pixels(combined,camera)
                    links.append(dict(upper_key=key(up),lower_key=key(low),owner_key=owner,
                        combined_accepted=fit['accepted'],combined_reason=fit['reason'],combined_rms_deg=fit.get('plane_rms_deg'),
                        combined_max_deg=fit.get('plane_max_deg'),combined_points=len(combined),combined_normal=fit.get('normal'),
                        combined_pixels=combined))
            chosen,status=choose_links(links)
            for row in links:
                link_rows.append(dict(session=identity[0],frame=identity[1],upper_key_json=json.dumps(row['upper_key']),
                    lower_key_json=json.dumps(row['lower_key']),owner_key_json=json.dumps(row['owner_key']),
                    combined_accepted=row['combined_accepted'],combined_reason=row['combined_reason'],
                    combined_rms_deg=row['combined_rms_deg'],combined_max_deg=row['combined_max_deg'],
                    combined_points=row['combined_points'],chosen_for_refit=chosen.get(row['lower_key']) is row,
                    physical_same_edge_verified=False))
            for low in lower:
                decision_rows.append(dict(session=identity[0],frame=identity[1],lower_key_json=json.dumps(key(low)),
                    decision=status.get(key(low),'no_accepted_continuation'),usable_for_ffb=False))
            for row in chosen.values():
                merge_rows.append(dict(session=identity[0],frame=identity[1],role=sample['role'],
                    upper_key_json=json.dumps(row['upper_key']),owner_key_json=json.dumps(row['owner_key']),lower_key_json=json.dumps(row['lower_key']),
                    combined_pixels_json=json.dumps(row['combined_pixels'].tolist()),combined_normal_json=json.dumps(row['combined_normal']),
                    combined_points_sha256=hashlib.sha256(row['combined_pixels'].astype('<i4').tobytes()).hexdigest(),
                    physical_same_edge_verified=False,usable_for_ffb=False))
            ordinary,_=fuse_planes(upper,lower)
            variants['object_reference'],_=object_screen.reference_filter([r for r in ordinary if r['band']=='upper'],
                [r for r in ordinary if r['band']=='lower'],references)
            for mode,refit in [('join_count_only',False),('join_refit',True)]:
                variants[mode],removed=build_join_votes(upper,lower,references,chosen,status,refit=refit)
                for row,owner in removed:removed_rows.append(dict(session=identity[0],frame=identity[1],mode=mode,
                    band=row['band'],key_json=json.dumps(key(row)),duplicate_of_band=owner['band'],duplicate_of_key_json=json.dumps(key(owner))))
            processed+=1
            if processed%40==0:print('native images',processed,'/',176,flush=True)
        for mode in MODES:
            members=variants.get(mode,[])
            pose=infer_up(np.array([r['normal'] for r in members]).reshape(-1,3),prior) if identity in frame_index else dict(accepted=False,reason='saved_bbox_stream_unavailable',up=None,inliers=0)
            if mode=='object_reference':
                old=old_index[identity];assert pose['accepted']==(old['accepted']=='True') and pose['reason']==old['reason'] and pose['inliers']==int(old['inliers'])
                if pose['accepted']:np.testing.assert_array_equal(pose['up'],json.loads(old['up_optical_json']))
            for i,row in enumerate(members):
                votes_rows.append(dict(session=identity[0],frame=identity[1],mode=mode,vote_index=i,band=row['band'],
                    key_json=json.dumps(key(row)),normal_json=json.dumps(row['normal']),
                    joined_lower_key_json=json.dumps(row.get('joined_lower_key')),usable_for_ffb=False))
            frames.append(dict(session=identity[0],frame=identity[1],time_sec=float(sample['time_sec']),role=sample['role'],mode=mode,
                bbox_stream_available=identity in frame_index,accepted=pose['accepted'],reason=pose['reason'],inliers=pose['inliers'],
                up_optical=pose['up'],physical_vertical_verified=False,usable_for_ffb=False))
    sessions=[]
    for session in sorted({r['session'] for r in samples}):
        for mode in MODES:
            summary=summarize_directions([r for r in frames if r['session']==session and r['mode']==mode],T)
            summary.pop('conditional_transform');summary['temporal_candidate_eligible']=summary.pop('metric_eligible')
            sessions.append(dict(session=session,mode=mode,**summary))
    output.mkdir()
    def structured(rows):return [{k+'_json' if k=='up_optical' else k:json.dumps(v) if k=='up_optical' else v for k,v in r.items()} for r in rows]
    exports=[('image_diagnostics.csv',structured(frames)),('session_hypotheses.csv',structured(sessions)),('vote_ledger.csv',votes_rows),
        ('upper_owners.csv',owner_rows),('all_adjacent_pairs.csv',link_rows),('lower_decisions.csv',decision_rows),
        ('merged_observed_support.csv',merge_rows),('post_refit_duplicate_votes.csv',removed_rows)]
    for name,rows in exports:
        write_csv(output/name,rows,fields=list(rows[0]) if rows else ['session','frame','mode','band','key_json','duplicate_of_band','duplicate_of_key_json'])
    assert all(sha256(Path(p))==h for p,h in sources.items())
    report=dict(status='COMPLETED_SAME_CONTOUR_SINGLE_VOTE_CONTROL_NOT_METRIC_OR_GATE_ADOPTION',work_date='2026-10-23',source_sha256=sources,
        sampled_images=len(samples),supported_images=processed,joined_observations=len(merge_rows),
        accepted_images_by_mode={m:sum(r['accepted'] for r in frames if r['mode']==m) for m in MODES},
        temporal_passes_by_mode={m:sum(r['temporal_candidate_eligible'] for r in sessions if r['mode']==m) for m in MODES},
        metric_labels_used=False,new_model_inference=False,source_images_edited=False,physical_output=False,production_settings_changed=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
