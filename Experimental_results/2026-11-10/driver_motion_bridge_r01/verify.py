"""追加撮影なし：ローカルpipe・保存YOLO枠・合成の操縦通信で接続を検証。

実カメラ・ROSノード・RTC待受け・機体・GPUを起動しない。
--cached-worker は本検証だけの保存枠再生で、製品の推論fallbackではない。
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import digest,load_config
from driver_motion_bridge import DriverMotionBridge
from driver_motion_protocol import PROFILE


def cached_worker(manifest,output):
    from cone_motion_range import MotionRangeEngine,load_motion_profile
    from cone_upper_support_candidate import observe_upper_completion
    from driver_motion_process import serve
    spec=json.loads(manifest.read_text())
    settings,camera,_,_=load_config()
    profile,sha=load_motion_profile(Path(spec["profile"]),settings)
    engine=MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
        target_roi=(270,0,350,720),observer=observe_upper_completion)
    class CachedPredictor:
        inference_source="cached_YOLO_boxes_NOT_new_inference_NOT_live_GPU"
        def __call__(self,frame):
            key=hashlib.sha256(frame.image.tobytes()).hexdigest()
            return spec["frames_by_decoded_pixel_sha256"][key]["boxes"]
    serve(engine,CachedPredictor(),sys.stdin.buffer,sys.stdout.buffer,output/"motion_distance_frames.jsonl")


def wait_for(predicate,bridge,timeout=10.):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if bridge.error:raise RuntimeError(bridge.error)
        if predicate():return
        time.sleep(.005)
    raise RuntimeError("bounded offline pipe wait expired")


def verify(output):
    import cv2
    import numpy as np
    if output.exists():raise ValueError("new output directory required")
    output.mkdir(parents=True)
    prior=ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01"
    provenance=json.loads((prior/"verification_r02/input_provenance.json").read_text())
    profile=prior/"prepared_r01/motion_profile_r01.json"
    # Changed driver launchers are deliberately NOT presented as unchanged.
    # Only unchanged geometry/calibration/raw inputs underpin cached comparison.
    relevant=[ROOT/"src"/name for name in ("cone_motion_range.py","angular_fisheye_geometry.py",
        "floor_reference_pose.py","cone_upper_support_candidate.py","cone_support_completion_candidate.py",
        "cone_distance_diagnostic_config.json","cone_distance_core.py","theta_rtc_frames.py",
        "theta_rtc_diagnostic.py","cone_distance_worker.py")]+[profile]
    inputs={}
    for path in relevant:
        actual=digest(path)
        if provenance[str(path)] != actual:raise ValueError("baseline geometry/input changed: "+str(path))
        inputs[str(path)]=actual
    config=load_config()[0]
    for kind in ("camera","floor"):
        path=ROOT/config[kind+"_candidate"]
        inputs[str(path)]=digest(path)
        if inputs[str(path)]!=config[kind+"_sha256"]:raise ValueError("changed calibration candidate")
    original=[json.loads(line) for line in (prior/"verification_r02/cached_replay.jsonl").read_text().splitlines()]
    paths={Path(key).name:Path(key) for key in provenance if key.endswith(".png")}
    jobs=[];frames={}
    for row in original:
        name=f"decoded_{row['session']}_f{row['frame']:06d}.png";path=paths[name]
        inputs[str(path)]=digest(path)
        if inputs[str(path)] != provenance[str(path)]:raise ValueError("baseline camera PNG changed")
        pixels=cv2.imread(str(path),cv2.IMREAD_COLOR)
        key=hashlib.sha256(pixels.tobytes()).hexdigest()
        frames[key]=dict(boxes=row["selected_detector_boxes"],original_session=row["session"],original_frame=row["frame"])
        jobs.append((path,row,key))
    manifest=output/"cached_worker_manifest.json"
    manifest.write_text(json.dumps(dict(profile=str(profile),frames_by_decoded_pixel_sha256=frames),indent=2)+"\n")
    bridge=DriverMotionBridge([sys.executable,"-u",str(Path(__file__).resolve()),"--cached-worker",
        "--manifest",str(manifest.resolve()),"--output-dir",str((output/"pipe_replay").resolve())],output/"pipe_replay")
    replay=[]
    try:
        bridge.start();wait_for(lambda:bridge.ready.is_set(),bridge)
        previous_original=None;sequence=0
        for path,old,pixel_sha in jobs:
            if old["session"] != previous_original:
                # New OFFLINE session identity, not a forged capture connection.
                bridge.begin(uuid.uuid4().hex,dict(PROFILE));sequence=0
                previous_original=old["session"]
            sequence+=1
            pixels=cv2.imread(str(path),cv2.IMREAD_COLOR);before=pixels.copy();pixels.flags.writeable=False
            count=bridge.returned
            if not bridge.publish(bridge.session,pixels,sequence/30.,time.monotonic()):
                raise ValueError("offline native input refused")
            wait_for(lambda:bridge.returned>count,bridge)
            view=bridge.snapshot()
            if "result" not in view:raise ValueError("offline reply not available in source age bound")
            value=view["result"]
            expected=old["horizontal_camera_foot_range_m"];actual=value["horizontal_camera_foot_range_m"]
            if ((expected is None) != (actual is None) or expected is not None and abs(expected-actual)>1e-9
                    or old["distance_available"] != value["distance_available"] or old["reason"] != value["reason"]):
                raise ValueError("pipe path changed baseline current-frame geometry")
            if not np.array_equal(pixels,before) or digest(path)!=inputs[str(path)]:
                raise ValueError("camera pixels changed")
            replay.append(dict(original_session=old["session"],original_frame=old["frame"],
                offline_pipe_session=value["session"],offline_pipe_frame=value["frame"],
                expected_range_m=expected,pipe_range_m=actual,distance_available=value["distance_available"],
                reason=value["reason"],baseline_equal=True,calibration_transfer_verified=False,
                actual_vehicle_motion_trial=False,new_yolo_inference=False))
    finally:
        shutdown=bridge.close()
    if not shutdown["child_stopped"] or not shutdown["io_thread_stopped"]:raise RuntimeError("pipe child did not stop")
    sys.path.insert(0,str(ROOT/"tests"))
    suite=unittest.TestSuite()
    patterns=("test_driver_motion*.py","test_cone_motion*.py","test_theta_rtc_diagnostic.py",
              "test_theta_rtc_capture_recovery.py","test_camera_capture_properties.py")
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern=pattern))
    log=io.StringIO();run=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    checks=[]
    env=dict(os.environ,THETA_UI_NO_VENV="1",THETA_UI_PYTHON=sys.executable,THETA_RTC_PYTHON=sys.executable)
    for name,mode in (("start_theta_receive_rtc.sh","--motion-distance"),("start_theta_stream_rtc.sh","--motion-native")):
        syntax=subprocess.run(["bash","-n",str(ROOT/"src"/name)],capture_output=True,text=True)
        help_run=subprocess.run(["bash",str(ROOT/"src"/name),mode,"--help"],env=env,
            capture_output=True,text=True,timeout=20.)
        checks.append(dict(script=name,syntax_exit_code=syntax.returncode,help_exit_code=help_run.returncode))
        (output/(name+".help.txt")).write_text(help_run.stdout+help_run.stderr)
    sources=[ROOT/"src"/name for name in ("driver_motion_bridge.py","driver_motion_camera.py",
        "driver_motion_process.py","driver_motion_protocol.py","webrtc_receive_ui.py","webrtc_stream.py",
        "start_theta_receive_rtc.sh","start_theta_stream_rtc.sh")]
    for pattern in patterns:sources += sorted((ROOT/"tests").glob(pattern))
    sources += [ROOT/"src"/name for name in ("cone_observation.py","cone_support_quality.py",
        "cone_motion_worker.py","run_cone_motion_live.py","prepare_cone_motion_profile.py")]
    sources += [Path(__file__).resolve()]
    summary=dict(status="PASS_SOFTWARE_PIPE_AND_MOCKS_ONLY" if run.wasSuccessful() and
        all(c["syntax_exit_code"]==c["help_exit_code"]==0 for c in checks) else "FAIL",
        tests=run.testsRun,failures=len(run.failures),errors=len(run.errors),skipped=len(run.skipped),
        cached_real_images=len(replay),range_available_images=sum(r["distance_available"] for r in replay),
        baseline_equal_images=sum(r["baseline_equal"] for r in replay),
        checks=checks,physical_metric_verified=False,actual_cuda_inference=False,actual_vehicle_motion_trial=False,
        live_driver_latency_measured=False,ros_nodes_started=False,network_listener_started=False,
        python_version=sys.version,opencv_version=cv2.__version__,numpy_version=np.__version__,
        new_camera_recording=False,camera_images_edited_or_exported=False,control_distance_connected=False,
        scope="synthetic local processes and mocked control signaling, NOT hardware compatibility approval",
        input_sha256=inputs,source_sha256={str(p):digest(p) for p in sources})
    (output/"tests.log").write_text(log.getvalue())
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    with (output/"cached_pipe_metrics.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(replay[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(replay)
    print(json.dumps({k:v for k,v in summary.items() if not k.endswith("sha256")},indent=2))
    return summary["status"]=="PASS_SOFTWARE_PIPE_AND_MOCKS_ONLY"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--cached-worker",action="store_true")
    parser.add_argument("--manifest",type=Path)
    args=parser.parse_args()
    if args.cached_worker:
        if args.manifest is None:raise ValueError("explicit offline cache manifest required")
        cached_worker(args.manifest,args.output_dir);return 0
    return 0 if verify(args.output_dir) else 1


if __name__=="__main__":raise SystemExit(main())
