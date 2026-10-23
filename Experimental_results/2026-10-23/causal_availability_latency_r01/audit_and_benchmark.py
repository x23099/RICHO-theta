"""Audit recorded clocks and benchmark only the frozen scene stage on this PC."""
import json
import os
from pathlib import Path
import platform
import sys
import time

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
UNIFORM=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01'
GEO=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
CAUSAL=HERE.parent/'causal_pose_replay_r01'
SESSION='floor_cone_same_pose_r01_20261015_160621_378'
sys.path[:0]=[str(ROOT/'src'),str(GEO),str(CAUSAL)]
from cone_dataset import read_csv,write_csv,sha256
from angular_fisheye_geometry import camera_from_candidate
from curve_geometry import extract_curve_planes
from scene_geometry import infer_up,angle_degrees
from frame_timing import PROCESSING_TIMING_FIELDS


def main():
    output=HERE/'benchmark_r01'
    if output.exists():raise ValueError('new benchmark output required')
    candidate=ROOT/'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
    floor=ROOT/'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
    paths=[HERE/'method.md',Path(__file__),GEO/'curve_geometry.py',GEO/'scene_geometry.py',ROOT/'src/angular_fisheye_geometry.py',
        ROOT/'src/frame_timing.py',ROOT/'src/bird_eye.py',candidate,floor,UNIFORM/'intake_r01/sampling_plan.json',
        UNIFORM/'scene_results_r01/image_diagnostics.csv',CAUSAL/'results_r01/summary.json']
    sources={str(p):sha256(p) for p in paths}
    plan=json.loads(paths[9].read_text())['sessions'];timing_rows=[];summaries=[]
    for p in plan:
        session=Path(p['session_path']);csvpath=session/'detections.csv';metapath=session/'metadata.json'
        sources[str(csvpath)]=sha256(csvpath);sources[str(metapath)]=sha256(metapath)
        meta=json.loads(metapath.read_text());rows=read_csv(csvpath)
        assert len(rows)==p['raw_frames']
        assert meta['processing_timing_total_endpoint']=='before detections.csv write'
        assert meta['processing_timing_clock']=='time.perf_counter' and meta['time_base']=='time.monotonic'
        assert tuple(meta['processing_timing_fields'])==PROCESSING_TIMING_FIELDS
        vals=[];times=[];invalid=0
        for r in rows:
            t=float(r['time_sec']);times.append(t)
            try:v=np.array([float(r[f]) for f in PROCESSING_TIMING_FIELDS]);valid=bool(np.isfinite(v).all() and (v>=0).all())
            except (ValueError,KeyError):valid=False
            invalid+=not valid
            entry=dict(session=p['session'],frame=int(r['frame']),time_sec=t,timing_fields_complete=valid)
            entry.update({f:r.get(f,'') for f in PROCESSING_TIMING_FIELDS})
            timing_rows.append(entry)
            if valid:vals.append(v)
        assert np.all(np.diff(times)>0)
        v=np.array(vals)
        summaries.append(dict(session=p['session'],frames=len(rows),valid_timing_frames=len(vals),invalid_timing_frames=invalid,
            historical_effective_fps=(len(times)-1)/(times[-1]-times[0]),
            processing_total_median_ms=float(np.median(v[:,-1])) if vals else None,
            processing_total_p95_ms=float(np.percentile(v[:,-1],95)) if vals else None,
            historical_blue_pipeline_median_ms=float(np.median(v[:,3])) if vals else None,
            new_scene_stage_included=False,exact_capture_or_completion_timestamp_available=False,usable_for_ffb=False))
    camera=camera_from_candidate(json.loads(candidate.read_text()))
    tf=json.loads(floor.read_text());prior=np.array(tf['nominal_transform'])[:3,:3].T@np.array([0.,0.,1.])
    frames=[r for r in read_csv(paths[10]) if r['session']==SESSION]
    assert len(frames)==52
    images=[]
    for r in frames:
        p=Path(r['source_native_png']);assert sha256(p)==r['png_sha256'];sources[str(p)]=sha256(p)
        img=cv2.imread(str(p));assert img.shape==(720,1280,3);images.append(img)
    cv2.setNumThreads(1)
    def compute(image):
        lines=extract_curve_planes(image,camera)
        normals=np.array([r['normal'] for r in lines if r['accepted']]).reshape(-1,3)
        return infer_up(normals,prior)
    compute(images[0])
    measured=[]
    for run in range(1,4):
        for r,image in zip(frames,images):
            start=time.perf_counter_ns();result=compute(image);elapsed=(time.perf_counter_ns()-start)/1e6
            assert result['accepted']==(r['accepted']=='True') and result['reason']==r['reason']
            if result['accepted']:assert angle_degrees(result['up'],json.loads(r['up_optical_json']))<1e-5
            measured.append(dict(session=SESSION,frame=int(r['frame']),time_sec=float(r['time_sec']),run=run,scene_service_ms=elapsed,
                scene_accepted=result['accepted'],scene_reason=result['reason'],original_single_frame_result_matches=True,
                image_read_in_timing=False,physical_output=False))
        print('benchmark pass',run,'/ 3 complete',flush=True)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    output.mkdir()
    write_csv(output/'recorded_timing_rows.csv',timing_rows);write_csv(output/'recorded_timing_summary.csv',summaries)
    write_csv(output/'scene_stage_measurements.csv',measured)
    costs=np.array([r['scene_service_ms'] for r in measured])
    record=dict(status='COMPLETED_CLOCK_AUDIT_AND_LOCAL_SCENE_STAGE_BENCHMARK_NOT_LIVE_LATENCY',work_date='2026-10-23',source_sha256=sources,
        historical_recordings=len(plan),historical_timing_rows=len(timing_rows),benchmark_session=SESSION,benchmark_unique_images=len(frames),
        benchmark_passes=3,benchmark_measurements=len(measured),warmup_images=1,scene_service_median_ms=float(np.median(costs)),
        scene_service_p95_ms=float(np.percentile(costs,95)),scene_service_observed_max_ms=float(max(costs)),
        environment=dict(host=platform.node(),platform=platform.platform(),processor=platform.processor(),python=sys.version.split()[0],
            numpy=np.__version__,opencv=cv2.__version__,opencv_threads=cv2.getNumThreads(),openblas_threads=os.environ.get('OPENBLAS_NUM_THREADS')),
        benchmark_matches_original_experiment_machine=False,end_to_end_latency_measured=False,source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))


if __name__=='__main__':main()
