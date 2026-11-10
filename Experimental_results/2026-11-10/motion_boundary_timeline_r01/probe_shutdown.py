"""所有する模擬測距子プロセスだけで終了待ちを観測。実機・ROSなし。"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest
from driver_motion_bridge import DriverMotionBridge
from driver_motion_protocol import PROFILE
import numpy as np

CHILD = r'''
import signal,sys,time
sys.path.insert(0,sys.argv[1]+'/src')
from driver_motion_protocol import read_frame,write_message
mode=sys.argv[2]
def delayed(signum,frame):
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    time.sleep(4.)
    raise SystemExit(0)
if mode=='ignore':signal.signal(signal.SIGTERM,signal.SIG_IGN)
elif mode=='delayed':signal.signal(signal.SIGTERM,delayed)
write_message(sys.stdout.buffer,dict(type='request'))
read_frame(sys.stdin.buffer)
# Hold stdout open without returning a result: parent is blocked in read_message.
while True:time.sleep(.01)
'''


def wait(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():return
        time.sleep(.005)
    raise RuntimeError("synthetic process bounded wait expired")


def run(output):
    if output.exists():raise ValueError("new output required")
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for mode in ("normal", "delayed", "ignore"):
        bridge = DriverMotionBridge([sys.executable, "-u", "-c", CHILD, str(ROOT), mode], output / mode)
        cleanup_kill = False
        try:
            bridge.start()
            wait(lambda: bridge.ready.is_set())
            bridge.begin("a" * 32, dict(PROFILE))
            image = np.zeros((720, 1280, 3), np.uint8);image.flags.writeable = False
            if not bridge.publish("a" * 32, image, .1, time.monotonic()):
                raise RuntimeError("synthetic publish failed")
            wait(lambda: bridge.sent == 1)
            started = time.monotonic()
            first = bridge.close()
            elapsed = time.monotonic() - started
            cases.append(dict(mode=mode, first_close=first, first_close_elapsed_sec=elapsed,
                io_alive_after_close=bridge.thread.is_alive(),
                child_alive_after_close=bridge.process.poll() is None))
        finally:
            # Only this exact Popen child is eligible. No PID/name/process-group scan.
            if bridge.process is not None and bridge.process.poll() is None:
                bridge.process.kill();cleanup_kill = True
                bridge.process.wait(timeout=2.)
            final = bridge.close()
            if cases and cases[-1]["mode"] == mode:
                cases[-1].update(test_cleanup_kill_required=cleanup_kill, after_test_cleanup=final)
    payload = dict(schema="distance_child_shutdown_probe_v1", cases=cases,
        source_sha256={str(p): digest(p) for p in (Path(__file__), ROOT / "src/driver_motion_bridge.py",
                       ROOT / "src/driver_motion_protocol.py")},
        synthetic_local_child_only=True, actual_camera_gpu_ros_or_robot_started=False,
        real_run_shutdown_root_cause_proven=False)
    with (output / "summary.json").open("x") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False);stream.write("\n")
    print(json.dumps(cases, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    run(parser.parse_args().output_dir)
