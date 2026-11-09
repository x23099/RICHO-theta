"""既存PNG＋同じframeの保存YOLO枠を走行評価engineへ通す。新規推論・撮影なし。

処理完了時刻は明示した模擬値。画像が実物でも走行・実時間性能の実験ではない。
異なるsessionの校正を未検証のまま転用するソフトウェア比較と明記する。
"""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import sys
import time
import unittest

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"src"))
from angular_fisheye_geometry import project, unproject
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_motion_range import MotionRangeEngine, horizontal_range, load_motion_profile
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_frames import NativeFrame


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir",type=Path,required=True)
    args=p.parse_args()
    if args.output_dir.exists():raise ValueError("new output directory required")
    folder=Path(__file__).parent
    prepared=folder/"prepared_r01"
    inputs=json.loads((prepared/"input_provenance.json").read_text())
    for name,sha in inputs.items():
        if digest(name)!=sha:raise ValueError("checked calibration input/source changed: "+name)
    settings,camera,_,_=load_config()
    profile,profile_sha=load_motion_profile(prepared/"motion_profile_r01.json",settings)
    inputs[str(prepared/"motion_profile_r01.json")]=profile_sha
    upper=ROOT/"recordings/2026-11-04/upper_support_capture_submission_r01/upper_support_capture_r01"
    multi=ROOT/"recordings/2026-11-04/floor_comparison_df33e833_multidistance_r01"
    jobs=[(upper/"distance_frames.jsonl",list((upper/"upper_support_evidence").glob("*.png")))]
    for label,frame in (("1p00",61948),("2p00",64232)):
        jobs.append((multi/f"floor_df33e833_z{label}_recent.jsonl",
            [multi/f"decoded_df33e833acdf4e7d8b00d1ec37b7bcae_f{frame:06d}.png"]))
    replay,metrics=[],[]
    for log,images in jobs:
        inputs[str(log)]=digest(log)
        by_frame={int(re.search(r"_f(\d+)\.png$",x.name)[1]):x for x in images}
        wanted={}
        for line in log.open():
            row=json.loads(line)
            if row.get("frame") in by_frame:wanted[row["frame"]]=row
        engine=MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
            target_roi=(270,0,350,720),observer=observe_upper_completion)
        for frame,path in sorted(by_frame.items()):
            old=wanted[frame]
            if path.name!=f"decoded_{old['session']}_f{frame:06d}.png":
                raise ValueError("exact cached detection/image identity required")
            inputs[str(path)]=digest(path)
            image=cv2.imread(str(path));before=image.copy()
            source=old["source_time_sec"]
            native=NativeFrame(old["session"],frame,old.get("frame_evidence",{}).get("input",{}).get("media_time_sec"),source,image)
            boxes=old["selected_detector_boxes"]
            started=time.perf_counter()
            result=engine.measure(native,boxes,source+.01)
            elapsed=1000*(time.perf_counter()-started)
            result.update(inference_source="cached_YOLO_boxes_NOT_new_inference",
                original_inference_source=old.get("inference_source"),
                timing_basis="recorded_source_plus_simulated_10ms_completion_NOT_live_performance",
                replay_cross_session_calibration_unverified=True, actual_vehicle_motion_trial=False)
            if not np.array_equal(image,before) or digest(path)!=inputs[str(path)]:
                raise ValueError("camera image changed")
            replay.append(result)
            metrics.append(dict(session=native.session,frame=frame,range_available=result["distance_available"],
                range_m=result["horizontal_camera_foot_range_m"],reason=result["reason"],
                observed_point=result["support_pixel"],offline_engine_service_ms=elapsed,
                live_timing_measured=False,calibration_transfer_verified=False,
                physical_metric_verified=False,usable_for_ffb=False))
    # Metric board range has no vehicle-side or heading coordinate. Reflect
    # both normal and ray as a BASIS change; no image or runtime reflection.
    primary=next(m for m in profile["models"] if m["id"]==profile["primary_model"])
    mirror=np.diag([-1.,1.,1.])
    mirrored=dict(primary,up_optical=(mirror@np.array(primary["up_optical"])).tolist())
    checks=[]
    for pixel in ([300.,380.],[320.,400.],[350.,430.]):
        rays,_=unproject([pixel],camera,image_size=(1280,720))
        a=horizontal_range(rays[0],primary);b=horizontal_range(mirror@rays[0],mirrored)
        checks.append(dict(pixel=pixel,raw_range_m=a,simultaneous_basis_reflection_range_m=b,
                           absolute_difference_m=abs(a-b),physical_mirror_verified=False))
    sys.path.insert(0,str(ROOT/"tests"))
    suite=unittest.TestSuite()
    for pattern in ("test_cone_motion_range.py","test_cone_motion_worker.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern=pattern))
    log=io.StringIO();run=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    sources=[Path(__file__),ROOT/"start_cone_distance.sh"]
    sources += [ROOT/"src"/name for name in ("cone_motion_range.py","cone_motion_worker.py",
        "run_cone_motion_live.py","prepare_cone_motion_profile.py","cone_distance_worker.py",
        "cone_distance_core.py","cone_upper_support_candidate.py","cone_support_completion_candidate.py")]
    sources += [ROOT/"tests"/name for name in ("test_cone_motion_range.py","test_cone_motion_worker.py")]
    inputs.update({str(p):digest(p) for p in sources})
    summary=dict(status="PASS_SOFTWARE_ONLY_NOT_LIVE_DRIVING_VALIDATION" if run.wasSuccessful() else "FAIL",
        tests=run.testsRun,failures=len(run.failures),errors=len(run.errors),skipped=len(run.skipped),
        real_saved_images=len(replay),range_available_images=sum(r["distance_available"] for r in replay),
        cached_detection_replay=True,new_yolo_inference_run=False,
        actual_camera_or_cuda_test_run=False,actual_vehicle_motion_trial=False,
        no_new_recording=True,physical_metric_verified=False,usable_for_ffb=False,
        control_or_robot_started=False,baseline_static_runtime_changed=False,
        metric="horizontal_camera_foot_range_m_NOT_forward_or_contact",metrics=metrics)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/"input_provenance.json").write_text(json.dumps(inputs,indent=2)+"\n")
    (args.output_dir/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (args.output_dir/"reflection_basis_checks.json").write_text(json.dumps(checks,indent=2)+"\n")
    (args.output_dir/"tests.log").write_text(log.getvalue())
    with (args.output_dir/"cached_replay.jsonl").open("x") as stream:
        for row in replay:stream.write(json.dumps(row,allow_nan=False)+"\n")
    with (args.output_dir/"cached_replay_metrics.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(metrics[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(metrics)
    print(json.dumps(summary,indent=2))
    raise SystemExit(not run.wasSuccessful())


if __name__=="__main__":main()
