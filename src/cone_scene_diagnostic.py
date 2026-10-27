"""Conditional static-scene diagnostic, promoted without threshold changes.

Lineage: 2026-10-21 scene_geometry infer_up/alignment; 2026-10-23 cached
plane evaluator, exact-bin r02 extractor, PastOnlyPose. Never a measured TF,
physical contact verification, moving-camera estimator, or FFB safety gate.
"""
import math
import cv2
import numpy as np
from angular_fisheye_geometry import unproject
from fisheye_floor_geometry import checked_transform

def angle_degrees(a,b):
    return float(np.degrees(np.arccos(np.clip(np.dot(a,b),-1,1))))


def unit(v):
    v=np.asarray(v,float)
    if v.shape!=(3,) or not np.isfinite(v).all() or np.linalg.norm(v)<1e-12:
        raise ValueError('finite nonzero vector required')
    return v/np.linalg.norm(v)



def _plane_from_subset(native, rays, indices):
    """Only called with indices into this extractor's own paired frame arrays."""
    ids = np.asarray(indices)
    if ids.ndim != 1 or not np.issubdtype(ids.dtype, np.integer):
        raise ValueError('one-dimensional integer pool indices required')
    if len(native) != len(rays) or np.any(ids < 0) or np.any(ids >= len(native)):
        raise ValueError('paired same-frame pool and in-range indices required')
    p = np.asarray(native[ids], float)
    if (p.ndim != 2 or p.shape[1] != 2 or len(p) < 30
            or not np.isfinite(p).all() or not np.equal(p, np.rint(p)).all()):
        raise ValueError('30 actual native edge pixels required')
    selected = rays[ids]
    if selected.shape != (len(p), 3) or not np.isfinite(selected).all():
        raise ValueError('finite paired rays required')
    # The pool has already passed unproject.valid and the exact old 75-degree
    # filter. Keep the old plane evaluator's angular/span/SVD tests verbatim.
    if np.max(np.degrees(np.arccos(np.clip(selected[:, 2], -1, 1)))) > 75:
        return dict(accepted=False, reason='outside_75degree_scene_domain')
    span = angle_degrees(selected[0], selected[-1])
    if span < 12:
        return dict(accepted=False, reason='insufficient_ray_span', ray_span_deg=span)
    _, singular, vt = np.linalg.svd(selected, full_matrices=False)
    normal = vt[-1]
    if normal[0] < 0:
        normal = -normal
    errors = np.degrees(np.arcsin(np.clip(abs(selected @ normal), 0, 1)))
    rms = float(np.sqrt(np.mean(errors ** 2)))
    maximum = float(errors.max())
    accepted = rms <= .15 and maximum <= .4
    return dict(accepted=accepted,
                reason='accepted_plane' if accepted else 'not_one_ray_plane',
                normal=normal.tolist() if accepted else None,
                plane_rms_deg=rms, plane_max_deg=maximum,
                ray_span_deg=span, edge_points=len(p))



def bin_winners(ids, bins, distance):
    ids = np.asarray(ids)
    bins = np.asarray(bins)
    distance = np.asarray(distance)
    if (ids.ndim != 1 or bins.ndim != 1 or distance.ndim != 1
            or len(ids) != len(bins) or not np.issubdtype(ids.dtype, np.integer)
            or not np.issubdtype(bins.dtype, np.integer)
            or not np.issubdtype(distance.dtype, np.number) or np.iscomplexobj(distance)):
        raise ValueError('integer one-dimensional ids/bins and real numeric distances required')
    if (np.any(ids < 0) or np.any(ids >= len(distance))
            or np.any(ids[1:] <= ids[:-1]) or np.any(bins[1:] < bins[:-1])):
        raise ValueError('strictly increasing in-range ids and nondecreasing bins required')
    values = distance[ids]
    if not np.isfinite(values).all():
        raise ValueError('finite distances for selected indices required')
    if not len(ids):
        return np.empty(0, dtype=np.intp)
    starts = np.r_[0, np.flatnonzero(bins[1:] != bins[:-1]) + 1]
    minima = np.minimum.reduceat(values, starts)
    lengths = np.diff(np.r_[starts, len(ids)])
    positions = np.flatnonzero(values == np.repeat(minima, lengths))
    winning_bins = bins[positions]
    first = np.r_[True, winning_bins[1:] != winning_bins[:-1]]
    return ids[positions[first]].astype(np.intp, copy=False)


def extract_guarded_curve_planes(image, camera):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError('native uint8 BGR frame required')
    gray = cv2.cvtColor(image[:, :640], cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(cv2.Canny(gray, 60, 120))
    native = np.column_stack((xs, ys)).astype(float)
    roi = (xs >= 40) & (xs <= 600) & (ys >= 60) & (ys <= 300)
    native = native[roi]
    rays, valid = unproject(native, camera, image_size=(1280, 720))
    valid &= rays[:, 2] >= np.cos(np.deg2rad(75))
    native = native[valid]
    rays = rays[valid]
    points = 200 * rays[:, :2] / rays[:, 2, None]
    if not len(points):
        return []
    candidates = cv2.HoughLinesPointSet(
        points.astype(np.float32).reshape(-1, 1, 2),
        200, 40, -1000, 1000, 1, 0, np.pi, np.pi / 720)
    rows = []
    for index, (votes, rho, theta) in enumerate(
            candidates.reshape(-1, 3) if candidates is not None else []):
        distance = abs(points @ np.array([np.cos(theta), np.sin(theta)]) - rho)
        ids = np.flatnonzero(distance <= 1)
        bins = np.floor(native[ids, 1] / 2).astype(int)
        chosen = bin_winners(ids, bins, distance)
        observed = native[chosen]
        pieces = np.split(chosen, np.flatnonzero(np.diff(observed[:, 1]) > 6) + 1)
        for part, indices in enumerate(pieces):
            actual = native[indices]
            if len(actual) < 30:
                continue
            span = np.ptp(actual, axis=0)
            if span[1] < 60 or span[1] < 1.5 * span[0]:
                continue
            plane = _plane_from_subset(native, rays, indices)
            rows.append(dict(line_index=index, part=part, hough_votes=float(votes),
                             rho=float(rho), theta=float(theta),
                             native_y_span=float(span[1]),
                             actual_edge_pixels_json=actual.tolist(), **plane))
    kept = []
    for row in sorted((r for r in rows if r['accepted']), key=lambda r: -r['native_y_span']):
        n = np.array(row['normal'])
        if any(np.degrees(np.arccos(np.clip(abs(n @ np.array(r['normal'])), -1, 1))) < 2
               for r in kept):
            row.update(accepted=False, reason='duplicate_ray_plane')
        else:
            kept.append(row)
    return rows

def infer_up(normals,prior_up):
    n=np.asarray(normals,float)
    prior=unit(prior_up)
    if n.shape==(0,):n=np.empty((0,3))
    if n.ndim!=2 or n.shape[1]!=3 or not np.isfinite(n).all() or not np.allclose(np.linalg.norm(n,axis=1),1):
        raise ValueError('unit plane normals required')
    result=dict(accepted=False,reason='fewer_than_six_distinct_planes',up=None,planes=len(n),inliers=0,
        inlier_indices=[],median_residual_deg=None,normal_span_deg=None,rank_gap_ratio=None,
        architectural_vertical_independently_verified=False,usable_for_ffb=False)
    if len(n)<6:return result
    best=None
    for i in range(len(n)):
        for j in range(i):
            spread=np.degrees(np.arccos(np.clip(abs(n[i]@n[j]),-1,1)))
            if spread<8:continue
            g=unit(np.cross(n[i],n[j]));g=g if g@prior>=0 else -g
            if angle_degrees(g,prior)>20:continue
            residual=np.degrees(np.arcsin(np.clip(abs(n@g),0,1)));inside=residual<=1
            score=(int(inside.sum()),-float(np.median(residual[inside])))
            if best is None or score>best[0]:best=(score,g,inside)
    if best is None:return dict(result,reason='no_diverse_plane_pair_within_prior')
    _,g,inside=best
    for _ in range(2):
        if inside.sum()<6:return dict(result,reason='insufficient_consensus',inliers=int(inside.sum()))
        _,singular,vt=np.linalg.svd(n[inside],full_matrices=False)
        g=vt[-1];g=g if g@prior>=0 else -g
        residual=np.degrees(np.arcsin(np.clip(abs(n@g),0,1)));inside=residual<=1
    if inside.sum()<6:return dict(result,reason='insufficient_final_consensus',inliers=int(inside.sum()))
    # Quality refers to the final fixed inlier set.
    _,singular,_=np.linalg.svd(n[inside],full_matrices=False)
    span=float(np.max(np.degrees(np.arccos(np.clip(abs(n[inside]@n[inside].T),-1,1)))))
    gap=float(singular[1]/max(singular[-1],1e-15))
    accepted=angle_degrees(g,prior)<=20 and span>=15 and gap>=10
    return dict(result,accepted=accepted,reason='conditional_architectural_up' if accepted else 'poor_geometry_or_prior',
        up=g.tolist() if accepted else None,inliers=int(inside.sum()),inlier_indices=np.flatnonzero(inside).tolist(),
        median_residual_deg=float(np.median(residual[inside])),normal_span_deg=span,rank_gap_ratio=gap)


def align_up_preserving_heading_reference(T,up_optical):
    """Minimal rotation only; not a measured yaw or complete floor TF."""
    T=checked_transform(T);g=unit(up_optical);target=T[:3,:3].T@np.array([0.,0.,1.])
    v=np.cross(g,target);cosine=float(g@target)
    if cosine<-.999999:raise ValueError('antiparallel up needs an explicit rotation axis')
    skew=np.array([[0,-v[2],v[1]],[v[2],0,-v[0]],[-v[1],v[0],0]])
    Q=np.eye(3)+skew+skew@skew/(1+cosine)
    output=T.copy();output[:3,:3]=T[:3,:3]@Q
    return checked_transform(output)

MODES=('sample_only','bounded_between_samples_1s')


def direction(v):
    a=np.array(v,float,copy=True)
    if a.shape!=(3,) or not np.isfinite(a).all() or not np.isclose(np.linalg.norm(a),1.,atol=1e-8):
        raise ValueError('explicit finite unit direction required')
    return a/np.linalg.norm(a)


def angle(a,b):return float(np.degrees(np.arccos(np.clip(np.dot(a,b),-1.,1.))))


class PastOnlyPose:
    def __init__(self):
        self.last_frame=0;self.last_time=None;self.latest_accepted=False
        self.train=[];self.validation=[];self.candidate=None;self.ready=False;self.first_ready_time=None
        self.reason='no_scene_observation';self.restarts=0

    def ingest(self,frame,time_sec,accepted,up=None):
        if type(frame) is not int or frame<=self.last_frame or type(accepted) is not bool:
            raise ValueError('strictly increasing integer frame and explicit boolean required')
        if type(time_sec) not in (float,int) or not math.isfinite(time_sec) or time_sec<0 or (self.last_time is not None and time_sec<=self.last_time):
            raise ValueError('strictly increasing finite recording time required')
        g=direction(up) if accepted else None
        if not accepted and up is not None:raise ValueError('rejected image must not supply an accepted direction')
        self.last_frame=frame;self.last_time=float(time_sec);self.latest_accepted=accepted
        if not accepted:
            self.reason='latest_scene_image_rejected';return
        if self.candidate is None:
            proposed=self.train+[(frame,g)]
            mean=np.mean([v for _,v in proposed],axis=0)
            if np.linalg.norm(mean)<1e-12 or max(angle(mean/np.linalg.norm(mean),v) for _,v in proposed)>2.:
                self._restart(frame,g);return
            self.train=proposed
            if len(self.train)==2:
                self.candidate=mean/np.linalg.norm(mean);self.reason='waiting_for_two_later_validation_images'
            else:self.reason='waiting_for_second_training_image'
            return
        if angle(self.candidate,g)>2.:
            self._restart(frame,g);return
        if not self.ready:
            self.validation.append(frame)
            if len(self.validation)==2:
                self.ready=True
                if self.first_ready_time is None:self.first_ready_time=float(time_sec)
                self.reason='past_only_candidate_ready'
            else:self.reason='waiting_for_second_validation_image'
        else:self.reason='past_only_candidate_reconfirmed'

    def _restart(self,frame,g):
        self.train=[(frame,g)];self.validation=[];self.candidate=None;self.ready=False
        self.restarts+=1;self.reason='direction_disagrees_restart_from_current_image'

    def query(self,frame,time_sec,mode):
        if mode not in MODES:raise ValueError('explicit diagnostic mode required')
        if type(frame) is not int or frame<self.last_frame or type(time_sec) not in (int,float) or not math.isfinite(time_sec) or time_sec<0:
            raise ValueError('query cannot precede ingested evidence')
        if self.last_time is not None and time_sec<self.last_time:raise ValueError('query cannot precede ingested time')
        age=float(time_sec-self.last_time) if self.last_time is not None else None
        reason=self.reason
        available=self.ready and self.latest_accepted
        if available and mode=='sample_only' and frame!=self.last_frame:available=False;reason='no_current_frame_scene_sample'
        if available and age>1.:available=False;reason='scene_confirmation_older_than_one_second'
        return dict(pose_available=bool(available),pose_reason=reason,initialized=self.ready,
            latest_scene_frame=self.last_frame,latest_scene_time_sec=self.last_time,latest_scene_age_sec=age,
            training_frames=[f for f,_ in self.train],validation_frames=list(self.validation),restarts=self.restarts,
            up_optical=self.candidate.tolist() if available else None,physical_transform_verified=False,usable_for_ffb=False)


def estimate_scene(image, camera, prior_up):
    planes = extract_guarded_curve_planes(image, camera)
    normals = [p["normal"] for p in planes if p["accepted"]]
    pose = infer_up(np.asarray(normals).reshape(-1, 3), prior_up)
    return dict(pose, curve_rows=len(planes))

