#!/usr/bin/env python3
"""Exercise the REAL worker/log reporter with injected scene/boxes/test clock.

NOT a camera/GPU/network measurement. Output explicitly keeps that distinction.
"""
import argparse
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG, digest
from cone_distance_worker import DistanceWorker
from summarize_cone_distance_live import summarize
from theta_rtc_frames import LatestNativeFrame


class CompletedScenePool:
    def __init__(self, **kwargs):
        pass

    def submit(self, function, *args):
        future = Future()
        future.set_result(function(*args))
        return future

    def shutdown(self, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw = output/"injected_input"
    raw.mkdir()
    slot = LatestNativeFrame()
    now = [10.]
    image = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
    box = dict(x1=290., y1=305., x2=350., y2=405., confidence=.9, class_id=0)
    worker = DistanceWorker(slot, DEFAULT_CONFIG, lambda frame: [box], raw/"distance_frames.jsonl",
        clock=lambda: now[0], scene_function=lambda *args: dict(accepted=True,
            up=worker.engine.prior_up.tolist(), reason="INJECTED_SCENE_NOT_CAMERA_EVIDENCE"))
    scenarios = (("injected_first", (10., 11., 12., 13., 13.04, 13.08)),
                 ("injected_reconnected", (15., 15.04)))
    with patch("cone_distance_worker.ThreadPoolExecutor", CompletedScenePool):
        worker.start()
        try:
            for session, timestamps in scenarios:
                slot.begin(session)
                for sequence, timestamp in enumerate(timestamps, 1):
                    now[0] = timestamp
                    slot.publish(session, image, timestamp-timestamps[0], timestamp)
                    deadline = time.monotonic()+2
                    while True:
                        with worker.lock:
                            ready = (worker.latest is not None and worker.latest[0].session == session
                                     and worker.latest[0].sequence == sequence)
                            error = worker.error
                        if error:
                            raise RuntimeError(error)
                        if ready:
                            break
                        if time.monotonic() > deadline:
                            raise RuntimeError("bounded synthetic worker wait expired")
                        worker.updated.wait(.005)
                        worker.updated.clear()
        finally:
            shutdown = worker.close()
    final = dict(runtime_status="STOPPED", run_error=None, worker_error=worker.error, cleanup_errors=[],
        shutdown=shutdown, worker_stopped=shutdown["worker_stopped"], physical_metric_verified=False,
        usable_for_ffb=False, physical_output=False, synthetic_fixture=True,
        description="Injected native-size image, detector boxes, accepted scene poses and clock; NO real FPS or accuracy evidence.",
        source_sha256={str(path): digest(path) for path in (Path(__file__), ROOT/"src/cone_distance_worker.py",
            ROOT/"src/cone_distance_core.py", ROOT/"src/cone_scene_diagnostic.py", DEFAULT_CONFIG)})
    (raw/"live_summary.json").write_text(json.dumps(final, indent=2)+"\n")
    result = summarize(raw, output/"report")
    print(json.dumps({key: result[key] for key in ("status", "processed_frames", "conditional_output_frames",
                      "session_count", "contains_injected_or_unverified_predictor")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
