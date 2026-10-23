"""Past-only, single-capture, static-scene diagnostic; not a runtime safety gate."""
import math

import numpy as np

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
