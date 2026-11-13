"""Rejection-only diagnostic display review; NEVER a controlling distance.

Scalar validation can run in the UI interpreter without importing geometry or
models. Geometry is imported only when the GPU child reviews current support.
"""
import math
import re

FLAGS=('physical_metric_verified','floor_contact_verified','controlling_distance','usable_for_ffb','published_to_ros')
CLEAR='clear_of_reviewed_local_body_boundary_NOT_floor_contact'
SCHEMA='driver_body_display_review_v1'
FIELDS={'schema','session','frame','source_time_sec','original_available','original_range_m',
    'display_available','display_range_m','reason','body_review_reason','reference_generation',
    'reference_frame','reference_png_sha256','reference_scope_verified','completed_time_sec',*FLAGS}


def checked_display_review(value, original):
    if (not isinstance(value,dict) or set(value)!=FIELDS or value['schema']!=SCHEMA
            or any(value[k] is not False for k in FLAGS)
            or any(value[k]!=original[k] for k in ('session','frame','source_time_sec'))
            or type(value['frame']) is not int
            or type(value['original_available']) is not bool
            or value['original_available']!=original['distance_available']
            or value['original_range_m']!=original['horizontal_camera_foot_range_m']
            or type(value['display_available']) is not bool or type(value['reference_scope_verified']) is not bool
            or not isinstance(value['reason'],str) or not 0<len(value['reason'])<=300
            or not isinstance(value['body_review_reason'],str) or not 0<len(value['body_review_reason'])<=300
            or type(value['completed_time_sec']) not in (int,float) or not math.isfinite(value['completed_time_sec'])
            or value['completed_time_sec']<value['source_time_sec']):
        raise ValueError('matching non-controlling display review required')
    bound=value['reference_scope_verified']
    if bound:
        if (type(value['reference_generation']) is not int or value['reference_generation']<1
                or type(value['reference_frame']) is not int or not 0<value['reference_frame']<value['frame']
                or not isinstance(value['reference_png_sha256'],str)
                or not re.fullmatch('[0-9a-f]{64}',value['reference_png_sha256'])):
            raise ValueError('bounded current-session display reference required')
    elif any(value[k] is not None for k in ('reference_generation','reference_frame','reference_png_sha256')):
        raise ValueError('unverified display reference metadata must be null')
    if value['display_available']:
        if (not original['distance_available'] or not bound or value['body_review_reason']!=CLEAR
                or value['reason']!=original['reason'] or value['display_range_m']!=original['horizontal_camera_foot_range_m']
                or type(value['display_range_m']) not in (int,float) or not math.isfinite(value['display_range_m'])
                or not 0<value['display_range_m']<=100):
            raise ValueError('display review must only preserve or revoke original range')
    elif value['display_range_m'] is not None:
        raise ValueError('withheld display review range must be null')
    return dict(value)


class BodyDisplayGuard:
    """Current-support veto only; owns small session/gap state, no image history."""
    def __init__(self):
        self.session=None;self.last_frame=0;self.last_source=None
        self.highest_generation=0;self.retired_generation=0

    def review(self, original, capability, now):
        source=original['source_time_sec'];session=original['session'];number=original['frame']
        result=dict(schema=SCHEMA,session=session,frame=number,source_time_sec=source,
            original_available=original['distance_available'],original_range_m=original['horizontal_camera_foot_range_m'],
            display_available=False,display_range_m=None,reason=original['reason'],body_review_reason='original_withheld',
            reference_generation=None,reference_frame=None,reference_png_sha256=None,reference_scope_verified=False,
            completed_time_sec=now,**{k:False for k in FLAGS})
        if self.session!=session:
            self.session=session;self.last_frame=0;self.last_source=None
            self.highest_generation=self.retired_generation=0
        generation=capability.get('generation',0) if isinstance(capability,dict) else 0
        if type(generation) is not int or generation<0:generation=0
        if self.last_source is not None and (number<=self.last_frame or source<=self.last_source or source-self.last_source>.5):
            self.retired_generation=max(self.retired_generation,self.highest_generation,generation)
        self.last_frame,self.last_source=number,source
        if type(generation) is int:self.highest_generation=max(self.highest_generation,generation)
        def reject(reason):
            result.update(reason=reason,body_review_reason=reason)
            return checked_display_review(result,original)
        if not 0<=now-source<=.5:return reject('display_body_review_stale')
        if any(original.get(k) is not False for k in FLAGS):raise ValueError('non-controlling original required')
        if not original['distance_available']:return checked_display_review(result,original)
        if capability is None:return reject('display_body_reference_unavailable')
        try:
            from cone_self_body_shadow import checked_reference,compare_self_body
            ref=checked_reference(capability['reference'])
            if ref['session']!=session:return reject('display_body_reference_session_mismatch')
            if (type(generation) is not int or generation<=self.retired_generation or generation<self.highest_generation
                    or type(capability['activation_frame']) is not int or number<=capability['activation_frame']
                    or type(capability['activated_at']) not in (int,float) or not math.isfinite(capability['activated_at'])
                    or source<capability['activated_at'] or ref['source_frame']>=number):
                return reject('display_body_reference_not_current')
            result.update(reference_generation=generation,reference_frame=ref['source_frame'],
                reference_png_sha256=ref['source_png_sha256'],reference_scope_verified=True)
            observation=original.get('support_observation')
            if not isinstance(observation,dict) or observation.get('point')!=original.get('support_pixel'):
                return reject('display_body_support_mismatch')
            reviewed=compare_self_body(observation,ref,session=session,reference_matches=True,compact=True)
            if reviewed['revoked'] or not reviewed['reference_usable']:
                return reject(reviewed['reason'])
            if reviewed['reason']!=CLEAR:return reject('display_body_review_incomplete')
            result.update(display_available=True,display_range_m=original['horizontal_camera_foot_range_m'],body_review_reason=CLEAR)
            return checked_display_review(result,original)
        except (KeyError,TypeError,ValueError):
            return reject('display_body_review_invalid')
