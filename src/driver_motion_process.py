"""GPU subprocess for driver frame tap. No ROS, Qt, camera or RTC listener."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import time

from driver_motion_protocol import compact_result, read_frame, write_message


def serve(engine, predictor, input_stream, output_stream, log_path, *, clock=time.monotonic, evidence=None, comparison=None):
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
            result_line=json.dumps(result,allow_nan=False)+"\n"
            log.write(result_line);log.flush()
            write_message(output_stream,dict(type="result",result=compact_result(result)))
            if comparison is not None:
                try:
                    comparison.offer(frame,result_line)
                except Exception as error:
                    print("[WARNING] comparison disabled; main distance continues: "+str(error),file=sys.stderr)
                    comparison=None
            if evidence is not None:
                try:
                    evidence.offer(frame,result,result_line)
                except Exception as error:
                    print("[WARNING] evidence disabled; distance continues: "+str(error),file=sys.stderr)
                    evidence=None
            processed += 1
            available += int(result["distance_available"])


def main(argv=None):
    from cone_distance_core import DEFAULT_CONFIG, digest, load_config
    from cone_distance_worker import YoloConePredictor
    from cone_motion_range import MotionRangeEngine, load_motion_profile
    from cone_upper_support_candidate import observe_upper_completion
    from driver_withheld_evidence import (WithheldEvidenceRecorder, EvidenceLimits,
        add_evidence_arguments, evidence_path, limits_from_args)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights",type=Path,required=True)
    parser.add_argument("--profile",type=Path,required=True)
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--device",type=int,default=0)
    parser.add_argument("--target-roi",type=int,nargs=4)
    parser.add_argument("--experimental-rigid-mount",action="store_true",required=True)
    parser.add_argument("--comparison-dir",type=Path,help="OFF by default; new recordings/ comparison directory")
    add_evidence_arguments(parser)
    args=parser.parse_args(argv)
    # Keep stdout exclusively for IPC, including during model setup/predict.
    output=sys.stdout.buffer
    evidence=None
    comparison=None
    previous_sigterm=None
    class EvidenceShutdown(BaseException):
        pass
    def stop_evidence_worker(signum,frame):
        import signal
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        raise EvidenceShutdown()
    try:
        with redirect_stdout(sys.stderr):
            limits=limits_from_args(args)
            if args.withheld_evidence_dir is None and limits != EvidenceLimits():
                raise ValueError("evidence limits require --withheld-evidence-dir")
            directory=evidence_path(args.withheld_evidence_dir) if args.withheld_evidence_dir is not None else None
            comparison_directory=None
            if args.comparison_dir is not None:
                from driver_guarded_comparison import comparison_path
                comparison_directory=comparison_path(args.comparison_dir)
                for other in (args.output_dir.resolve(),directory):
                    if other is not None and (other == comparison_directory or other in comparison_directory.parents
                                              or comparison_directory in other.parents):
                        raise ValueError("comparison, evidence, and main output must be separate")
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
            if directory is not None:
                try:
                    evidence=WithheldEvidenceRecorder(directory,args.output_dir/"motion_distance_frames.jsonl",limits)
                except Exception as error:
                    print("[WARNING] evidence initialization failed; distance continues: "+str(error),file=sys.stderr)
                    summary["withheld_evidence_initialization_error"]=f"{type(error).__name__}: {error}"[:1000]
            if comparison_directory is not None:
                try:
                    from driver_guarded_comparison import GuardedComparisonWorker
                    comparison=GuardedComparisonWorker(comparison_directory,settings,camera,profile,sha,
                        target_roi=args.target_roi)
                except Exception as error:
                    summary["comparison_initialization_error"]=f"{type(error).__name__}: {error}"[:1000]
                    print("[WARNING] comparison initialization failed; main distance continues: "+str(error),file=sys.stderr)
            if evidence is not None or comparison is not None:
                import signal
                previous_sigterm=signal.signal(signal.SIGTERM,stop_evidence_worker)
            summary["guarded_comparison"]=dict(requested=comparison_directory is not None,
                worker_started=comparison is not None,directory=str(comparison_directory) if comparison_directory else None,
                main_display_modified=False,controlling_distance=False)
            summary["withheld_evidence"]=dict(requested=directory is not None,
                recorder_started=evidence is not None, directory=str(directory) if directory else None,
                target_reason="colour_contour_reaches_roi_edge", max_frames=limits.max_frames,
                max_png_and_sidecar_bytes=limits.max_bytes, interval_sec=limits.interval_sec)
            (args.output_dir/"motion_engine_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
            (args.output_dir/"motion_profile_used.json").write_text(json.dumps(profile,indent=2)+"\n")
            serve(engine,predictor,sys.stdin.buffer,output,args.output_dir/"motion_distance_frames.jsonl",
                evidence=evidence,comparison=comparison)
    except EvidenceShutdown:
        return 0
    except Exception as error:
        write_message(output,dict(type="error",error=f"{type(error).__name__}: {error}"[:1000]))
        return 1
    finally:
        if previous_sigterm is not None:
            import signal
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
        if evidence is not None:
            evidence.close(timeout=.25)
        if comparison is not None:
            comparison.close(timeout=.25)
        if previous_sigterm is not None:
            import signal
            signal.signal(signal.SIGTERM,previous_sigterm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
