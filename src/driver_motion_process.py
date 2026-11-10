"""GPU subprocess for driver frame tap. No ROS, Qt, camera or RTC listener."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import time

from driver_motion_protocol import compact_result, read_frame, write_message


def serve(engine, predictor, input_stream, output_stream, log_path, *, clock=time.monotonic):
    processed = available = 0
    with Path(log_path).open("x") as log:
        while True:
            write_message(output_stream,dict(type="request"))
            try:
                frame = read_frame(input_stream)
            except EOFError:
                return dict(processed=processed,range_available_frames=available)
            started = clock()
            if 0 <= started-frame.received_at <= engine.settings["frame_max_age_sec"]:
                boxes = predictor(frame)
            else:
                boxes = []  # Engine revokes stale input, no wasted inference.
            inferred = clock()
            result = engine.measure(frame,boxes,inferred)
            finished = clock()
            result.update(completed_time_sec=finished,frame_age_ms=1000*(finished-frame.received_at),
                predict_ms=1000*(inferred-started),support_geometry_ms=1000*(finished-inferred),
                inference_source=getattr(predictor,"inference_source","injected_predictor_NOT_live_cuda"),
                input_source="driver_native_receive_tap_NOT_remapped_view")
            if finished-frame.received_at > engine.settings["frame_max_age_sec"]:
                from cone_motion_range import revoke_range
                revoke_range(result,"frame_processing_too_old")
            log.write(json.dumps(result,allow_nan=False)+"\n");log.flush()
            write_message(output_stream,dict(type="result",result=compact_result(result)))
            processed += 1
            available += int(result["distance_available"])


def main(argv=None):
    from cone_distance_core import DEFAULT_CONFIG, digest, load_config
    from cone_distance_worker import YoloConePredictor
    from cone_motion_range import MotionRangeEngine, load_motion_profile
    from cone_upper_support_candidate import observe_upper_completion
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights",type=Path,required=True)
    parser.add_argument("--profile",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--device",type=int,default=0)
    parser.add_argument("--target-roi",type=int,nargs=4)
    parser.add_argument("--experimental-rigid-mount",action="store_true",required=True)
    args=parser.parse_args(argv)
    # Keep stdout exclusively for IPC, including during model setup/predict.
    output=sys.stdout.buffer
    try:
        with redirect_stdout(sys.stderr):
            settings,camera,_,_=load_config(args.config)
            profile,sha=load_motion_profile(args.profile,settings)
            engine=MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
                target_roi=args.target_roi,observer=observe_upper_completion)
            predictor=YoloConePredictor(args.weights,settings,args.output_dir,args.device)
            summary=dict(schema="driver_motion_engine_v1",profile_sha256=sha,
                weights_sha256=predictor.weights_sha256,config_sha256=digest(args.config),
                gpu=predictor.gpu,physical_metric_verified=False,usable_for_ffb=False,
                published_to_ros=False,mount_or_floor_tilt_compensated=False,
                metric="horizontal_camera_foot_range_m_NOT_base_link_or_contact")
            (args.output_dir/"motion_engine_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
            (args.output_dir/"motion_profile_used.json").write_text(json.dumps(profile,indent=2)+"\n")
            serve(engine,predictor,sys.stdin.buffer,output,args.output_dir/"motion_distance_frames.jsonl")
    except Exception as error:
        write_message(output,dict(type="error",error=f"{type(error).__name__}: {error}"[:1000]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
