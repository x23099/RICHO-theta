"""OFFLINE compute candidate. No imports from runtime entry points.

Shares ONLY a baseline freshly computed by the comparator on this very frame.
Does not implement/authorize stream reference lifecycle or measure live latency.
"""
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from cone_distance_core import select_front_boxes
from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge
from cone_motion_range import FLAGS,MotionRangeEngine
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_frames import native_frame

FIELDS=('distance_available','horizontal_camera_foot_range_m','reason','support_pixel',
    'models','selected_detector_boxes','support_observation','front_candidates','primary_model','profile_sha256',*FLAGS)


def evaluate_offline_frame(frame,boxes,original,data,reference,*,completed_at,shared=False,offline_only=False,compact=False):
    if offline_only is not True or type(shared) is not bool or type(compact) is not bool:
        raise ValueError('explicit offline compute mode required')
    native_frame(frame.image)
    if (not math.isfinite(completed_at) or original.get('schema')!='cone_motion_range_v1'
        or (original.get('session'),original.get('frame'),original.get('source_time_sec'))
            !=(frame.session,frame.sequence,frame.received_at)
        or original.get('profile_sha256')!=data['profile_sha']
        or not frame.received_at<=original.get('completed_time_sec',-1)<=completed_at<=frame.received_at+.5
        or any(original.get(key) is not False for key in FLAGS)):
        raise ValueError('matching fresh non-controlling original result required')
    # Independently select from the newly submitted detector boxes, not original's claim.
    selected=select_front_boxes(boxes,data['camera'],data['settings']['confidence'],[270,0,350,720])
    comparison=None
    if len(selected)==1:
        comparison=compare_guarded_lower_edge(frame.image,selected[0],data['camera'],reference,
            session=frame.session,reference_matches=True,compact=compact)

    def current_observation(image,box,camera):
        # Local closure, no shared/global/per-stream cache or main-log observation.
        if image is not frame.image or camera is not data['camera'] or box!=selected[0]:
            raise ValueError('fresh observation must belong to this exact input')
        # MotionRangeEngine owns a deepcopy in its result; it never mutates this.
        return comparison['baseline']

    observer=current_observation if shared and comparison is not None else observe_upper_completion
    engine=MotionRangeEngine(data['settings'],data['camera'],data['profile'],data['profile_sha'],
        acknowledged=True,target_roi=[270,0,350,720],observer=observer)
    baseline=engine.measure(frame,boxes,completed_at)
    if any(baseline.get(key)!=original.get(key) for key in FIELDS):
        raise ValueError('fresh baseline cannot reproduce original')
    proposal=baseline
    if comparison is not None:
        if comparison['baseline']!=baseline.get('support_observation'):
            raise ValueError('comparison and baseline observation differ')
        engine=MotionRangeEngine(data['settings'],data['camera'],data['profile'],data['profile_sha'],
            acknowledged=True,target_roi=[270,0,350,720],
            observer=lambda *a:comparison['proposed_observation'])
        proposal=engine.measure(frame,boxes,completed_at)
    return dict(baseline=baseline,proposal=proposal,
        body_review_reason=comparison['proposed_body_review']['reason'] if comparison else None,
        lower_half_pixel_eligible=comparison['lower_half_pixel_eligible'] if comparison else False,
        offline_compute_only=True,reference_lifecycle_verified=False,live_authorized=False,**FLAGS)
