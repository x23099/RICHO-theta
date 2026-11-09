"""Opt-in GPU range display during motion under a fixed-mount/planar-floor assumption.

Experimental display/log ONLY. No robot command, ROS, FFB or movement startup.
Uses the existing native diagnostic sender and port 5002, NOT the static receiver
at the same time. No new camera recording or on-site calibration is required.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import time

import cv2
import numpy as np

from cone_distance_core import DEFAULT_CONFIG, checked_target_roi, digest, load_config
from cone_distance_worker import YoloConePredictor
from cone_motion_range import FLAGS, MotionRangeEngine, load_motion_profile
from cone_motion_worker import MotionRangeWorker
from cone_support_completion_candidate import observe_lateral_completion
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_diagnostic import Receiver, save_decoded_frame
from theta_rtc_frames import LatestNativeFrame


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weights", type=Path, required=True)
    p.add_argument("--motion-profile", type=Path, required=True)
    p.add_argument("--experimental-rigid-mount", action="store_true",
        help="explicitly acknowledge UNVERIFIED transferred calibration, fixed camera height/tilt and locally planar floor")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5002)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--support-source", choices=("lateral", "upper"), default="upper",
        help="experimental current-frame observed support; upper also permits the existing bounded top-only completion")
    p.add_argument("--duration-sec", type=float)
    p.add_argument("--target-roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                   help="explicit native bbox-centre scope; outside is NOT monitored")
    return p


def validate_options(args):
    if args.experimental_rigid_mount is not True:
        raise ValueError("--experimental-rigid-mount is required; NOT physical calibration approval")
    if args.output_dir.exists() or args.device < 0 or not 1 <= args.port <= 65535:
        raise ValueError("new output directory, nonnegative CUDA device, valid port required")
    if args.duration_sec is not None and (not np.isfinite(args.duration_sec) or args.duration_sec <= 0):
        raise ValueError("positive finite duration required")
    checked_target_roi(args.target_roi)
    settings, camera, _, _ = load_config(args.config)
    profile, sha = load_motion_profile(args.motion_profile, settings)
    return settings, camera, profile, sha


def render_motion(image, result=None, reason="waiting_for_current_motion_range"):
    """Live display copy only; never saved over the native camera image."""
    display = image.copy()
    cv2.rectangle(display, (0, 0), (1280, 165), (0, 0, 0), -1)
    available = result is not None and result["distance_available"]
    value = f"{result['horizontal_camera_foot_range_m']:.3f} m" if available else "WITHHELD"
    lines = [f"MOTION RANGE EXPERIMENT | {value} | NO CONTROL / ROS / FFB",
        "Horizontal camera-foot -> visible support, NOT base_link/contact distance",
        "ASSUMED fixed mount + planar floor | NO pitch/roll/bounce compensation",
        (result["reason"] if result is not None else reason)[:120]]
    if result is not None:
        lines.append(f"frame {result['frame']} | receive-age {result['frame_age_ms']:.0f} ms | primary {result['primary_model']} UNVERIFIED")
        others = [f"{m['id']}={m['horizontal_camera_foot_range_m']:.3f}m" for m in result["models"] if m["range_available"]]
        lines.append("Other hypotheses, NOT accuracy bounds: "+", ".join(others[:4]))
        if result.get("support_pixel") is not None:
            cv2.circle(display, tuple(result["support_pixel"]), 4, (0, 255, 255), 1)
    for i, text in enumerate(lines):
        cv2.putText(display, text, (10, 25+i*25), cv2.FONT_HERSHEY_SIMPLEX, .53,
                    (0, 255, 255) if i == 0 else (255, 255, 255), 1)
    return display


async def run(args):
    settings, camera, profile, profile_sha = validate_options(args)  # Before GPU/network.
    engine = MotionRangeEngine(settings, camera, profile, profile_sha,
        acknowledged=True, target_roi=args.target_roi,
        observer=observe_upper_completion if args.support_source == "upper" else observe_lateral_completion)
    predictor = YoloConePredictor(args.weights, settings, args.output_dir, args.device)
    from aiohttp import web
    slot = LatestNativeFrame()
    server = Receiver(slot)
    worker = MotionRangeWorker(slot, engine, predictor, args.output_dir/"motion_distance_frames.jsonl")
    app = web.Application(client_max_size=256*1024)
    app.router.add_post("/offer", server.offer)
    runner = web.AppRunner(app, access_log=None)
    summary = dict(schema="cone_motion_live_summary_v1", status="UNVERIFIED_RIGID_MOUNT_MOTION_EXPERIMENT",
        motion_profile_sha256=profile_sha, profile_source=profile["source"],
        primary_model=profile["primary_model"], models=profile["models"],
        gpu=predictor.gpu, weights_sha256=predictor.weights_sha256, config_sha256=digest(args.config),
        metric="horizontal_camera_foot_range_m", target_roi_native_xyxy=engine.target_roi,
        support_source=args.support_source, temporal_static_support_gate_used=False,
        static_scene_required=False, mount_or_floor_tilt_compensated=False,
        cross_session_mount_verified=False, cross_pc_capture_latency_measured=False,
        robot_movement_started=False, physical_output=False, **FLAGS)
    sources = [Path(__file__), Path(__file__).with_name("cone_motion_range.py"),
               Path(__file__).with_name("cone_motion_worker.py"), Path(__file__).with_name("theta_rtc_frames.py")]
    summary["source_sha256"] = {p.name: digest(p) for p in sources}
    (args.output_dir/"motion_profile_used.json").write_text(json.dumps(profile, indent=2)+"\n")
    started, run_error = time.monotonic(), None
    try:
        await runner.setup()
        await web.TCPSite(runner, args.host, args.port).start()
        worker.start()
        logging.info("Motion range experiment on %s:%s; does NOT start robot/control/FFB. Q stops.", args.host, args.port)
        last_state = None
        while args.duration_sec is None or time.monotonic()-started < args.duration_sec:
            now = time.monotonic()
            current, input_state = slot.current(now)
            paired, state = worker.poll(now, current)
            if current is None:
                state = input_state
            if state != last_state:
                logging.info("Motion range display: %s", state)
                last_state = state
            if worker.error:
                raise RuntimeError(worker.error)
            if not args.headless:
                frame, result = paired if paired is not None else (current, None)
                image = frame.image if frame is not None else np.zeros((720, 1280, 3), np.uint8)
                cv2.imshow("THETA motion range EXPERIMENT - NO CONTROL", render_motion(image, result, state))
                key = cv2.waitKey(1) & 0xff
                if key in (ord("q"), ord("Q")):
                    break
                if key in (ord("s"), ord("S")) and frame is not None:
                    try:
                        await asyncio.to_thread(save_decoded_frame, args.output_dir, frame)
                    except ValueError as error:
                        logging.info("%s", error)
            await asyncio.sleep(.02)
    except BaseException as error:
        run_error = f"{type(error).__name__}: {error}"
        raise
    finally:
        errors = []
        for name, cleanup in (("receiver", server.close), ("http_runner", runner.cleanup)):
            try:
                await cleanup()
            except Exception as error:
                errors.append(f"{name}: {type(error).__name__}: {error}")
        shutdown = dict(shutdown_complete=False, worker_stopped=False)
        try:
            # Receiver and HTTP are already closed. close() is a bounded 2 s
            # join, not inference; no second executor is needed just to join
            # the daemon worker during final teardown.
            shutdown = worker.close()
        except Exception as error:
            errors.append(f"worker: {type(error).__name__}: {error}")
        if not args.headless:
            try:
                cv2.destroyAllWindows()
            except Exception as error:
                errors.append(f"display: {error}")
        summary.update(elapsed_sec=time.monotonic()-started, run_error=run_error, cleanup_errors=errors,
            shutdown=shutdown, worker_error=worker.error, processed=worker.processed,
            range_available_frames=worker.available, retired_inference_results=worker.retired_results,
            runtime_status="CLEANUP_INCOMPLETE" if errors or not shutdown["shutdown_complete"] else
                           "RUN_FAILED" if run_error else "STOPPED")
        (args.output_dir/"motion_live_summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        if summary["runtime_status"] == "CLEANUP_INCOMPLETE" and run_error is None:
            raise RuntimeError("motion receiver cleanup incomplete; a native inference call may still run")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        asyncio.run(run(build_parser().parse_args(argv)))
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as error:
        logging.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
