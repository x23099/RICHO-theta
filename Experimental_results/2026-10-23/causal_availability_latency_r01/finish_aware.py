"""Single-worker completion ordering for an offline, fixed-cost scenario."""
import math

from causal_pose import PastOnlyPose


def schedule(samples,service_seconds):
    jobs=[];last_frame=0;last_release=-1.;finish=0.
    for sample in samples:
        frame=int(sample['frame']);release=float(sample['time_sec']);cost=service_seconds[frame]
        if frame<=last_frame or not math.isfinite(release) or release<0 or release<=last_release:
            raise ValueError('strictly increasing sample frame and finite release time required')
        if type(cost) not in (float,int) or not math.isfinite(cost) or cost<0:
            raise ValueError('explicit finite nonnegative service seconds required')
        start=max(release,finish);finish=start+cost
        jobs.append(dict(frame=frame,release_sec=release,start_sec=start,finish_sec=finish,service_sec=float(cost),
            queue_wait_sec=start-release,sample=sample))
        last_frame=frame;last_release=release
    return jobs


class FinishAwarePose:
    def __init__(self,jobs):
        self.jobs=jobs;self.next_job=0;self.pose=PastOnlyPose();self.events=[];self.last_query_frame=0;self.last_query_time=-1.

    def query(self,frame,time_sec):
        if type(frame) is not int or frame<=self.last_query_frame or not math.isfinite(time_sec) or time_sec<=self.last_query_time:
            raise ValueError('strictly increasing decision frame/time required')
        self.last_query_frame=frame;self.last_query_time=time_sec
        import json
        while self.next_job<len(self.jobs) and self.jobs[self.next_job]['finish_sec']<=time_sec:
            job=self.jobs[self.next_job];sample=job['sample']
            if job['frame']>frame:raise ValueError('completed future frame cannot be applied to an earlier query')
            accepted=sample['accepted']
            if accepted not in ('True','False'):raise ValueError('explicit saved boolean required')
            accepted=accepted=='True';was_ready=self.pose.ready
            self.pose.ingest(job['frame'],job['release_sec'],accepted,json.loads(sample['up_optical_json']) if accepted else None)
            self.events.append(dict(scene_frame=job['frame'],source_time_sec=job['release_sec'],completion_time_sec=job['finish_sec'],
                first_query_frame=frame,first_query_time_sec=time_sec,initialization_event=self.pose.ready and not was_ready))
            self.next_job+=1
        # Freshness remains tied to original input time, NOT to completion time.
        return self.pose.query(frame,time_sec,'bounded_between_samples_1s')
