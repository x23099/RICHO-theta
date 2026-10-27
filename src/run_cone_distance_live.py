#!/usr/bin/env python3
"""Optional GPU receiver using the existing video-only native RTC transport.

No ROS / motion / FFB. Static-camera conditional distance diagnostic only.
Sender remains start_theta_stream_rtc.sh --diagnostic. Do not run both receivers
on port 5002. Real camera/network validation remains a separate hardware step.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import time

import cv2
import numpy as np

from cone_distance_core import DEFAULT_CONFIG, checked_target_roi, digest, load_config, render_distance
from cone_distance_worker import DistanceWorker, YoloConePredictor
from theta_rtc_diagnostic import Receiver, save_decoded_frame
from theta_rtc_frames import LatestNativeFrame


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--duration-sec", type=float)
    parser.add_argument("--target-roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                        help="explicit diagnostic target scope; outside is NOT monitored")
    return parser


async def run(args):
    from aiohttp import web
    if args.output_dir.exists() or args.device < 0 or not 1 <= args.port <= 65535:
        raise ValueError("new output, nonnegative CUDA device, and valid port required")
    if args.duration_sec is not None and (not np.isfinite(args.duration_sec) or args.duration_sec <= 0):
        raise ValueError("positive finite duration required")
    settings, _, _, _ = load_config(args.config)
    checked_target_roi(args.target_roi)
    # Complete model / CUDA validation BEFORE opening a network listener.
    predictor = YoloConePredictor(args.weights, settings, args.output_dir, args.device)
    slot = LatestNativeFrame()
    server = Receiver(slot)
    worker = DistanceWorker(slot, args.config, predictor, args.output_dir / "distance_frames.jsonl", target_roi=args.target_roi)
    app = web.Application(client_max_size=256 * 1024)
    app.router.add_post("/offer", server.offer)
    runner = web.AppRunner(app, access_log=None)
    summary = dict(status="LIVE_CONDITIONAL_DIAGNOSTIC_NOT_PHYSICAL_APPROVAL", gpu=predictor.gpu,
                   weights_sha256=predictor.weights_sha256, config_sha256=digest(args.config),
                   static_camera_only=True, target_frame="paper7_ground_reference",
                   target_roi_native_xyxy=worker.engine.target_roi,
                   physical_metric_verified=False, usable_for_ffb=False, physical_output=False,
                   cross_pc_capture_latency_measured=False)
    started = time.monotonic()
    try:
        await runner.setup()
        await web.TCPSite(runner, args.host, args.port).start()
        worker.start()
        logging.info("Read-only GPU distance receiver on %s:%s; no ROS/FFB. Q/Ctrl+C stops.", args.host, args.port)
        last_state = None
        while args.duration_sec is None or time.monotonic()-started < args.duration_sec:
            now = time.monotonic()
            current, input_state = slot.current(now)
            paired, state = worker.poll(now, current)
            state = state if current is not None else input_state
            if state != last_state:
                logging.info("Distance display: %s", state)
                last_state = state
            if worker.error is not None:
                raise RuntimeError("distance worker failed: " + worker.error)
            if not args.headless:
                if paired is not None:
                    frame, result = paired
                    display = render_distance(frame.image, result)
                else:
                    frame = current
                    display = current.image.copy() if current is not None else np.zeros((720, 1280, 3), np.uint8)
                    cv2.rectangle(display, (0, 0), (1280, 65), (0, 0, 0), -1)
                    cv2.putText(display, "LIVE DIAGNOSTIC | WITHHELD | NO ROS / FFB", (12, 27),
                                cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 255, 255), 1)
                    cv2.putText(display, state[:115], (12, 53), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1)
                cv2.imshow("THETA static cone diagnostic", display)
                key = cv2.waitKey(1) & 0xff
                if key in (ord("q"), ord("Q")):
                    break
                if key in (ord("s"), ord("S")) and frame is not None:
                    try:
                        await asyncio.to_thread(save_decoded_frame, args.output_dir, frame)
                    except ValueError as exc:
                        logging.info("%s", exc)
            await asyncio.sleep(.02)
    finally:
        await server.close()
        await runner.cleanup()
        if worker.thread.ident is not None:
            await asyncio.to_thread(worker.close)
        if not args.headless:
            cv2.destroyAllWindows()
        summary.update(elapsed_sec=time.monotonic()-started, worker_error=worker.error,
                       worker_stopped=not worker.thread.is_alive())
        (args.output_dir / "live_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        asyncio.run(run(build_parser().parse_args(argv)))
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        logging.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
