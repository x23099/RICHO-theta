"""保存追加後の関連テスト／起動helpを実行。実カメラ・ROSは開始しない。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("new output required")
    suite = unittest.TestSuite()
    for pattern in ("test_driver_motion*.py", "test_driver_withheld_evidence.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    env = dict(os.environ, THETA_UI_NO_VENV="1", THETA_UI_PYTHON=sys.executable)
    checks = []
    for command in ([sys.executable, str(ROOT/"src/driver_motion_process.py"), "--help"],
                    ["bash", "-n", str(ROOT/"src/start_theta_receive_rtc.sh")],
                    ["bash", str(ROOT/"src/start_theta_receive_rtc.sh"), "--motion-distance", "--help"]):
        run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20.)
        checks.append(dict(command=command, exit_code=run.returncode, output=run.stdout+run.stderr))
    sources = [ROOT/"src"/name for name in ("driver_motion_process.py", "driver_motion_bridge.py",
        "driver_withheld_evidence.py", "verify_driver_withheld_evidence.py", "report_driver_motion_logs.py",
        "driver_motion_protocol.py", "webrtc_receive_ui.py", "webrtc_stream.py",
        "start_theta_receive_rtc.sh", "start_theta_stream_rtc.sh")]
    sources += list((ROOT/"tests").glob("test_driver_motion*.py"))
    sources += [ROOT/"tests/test_driver_withheld_evidence.py", Path(__file__)]
    summary = dict(status="PASS_OFFLINE_ONLY" if result.wasSuccessful() and all(c["exit_code"] == 0 for c in checks) else "FAIL",
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        checks=checks, source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        real_cuda_or_camera_started=False, actual_vehicle_or_control_latency_measured=False)
    output.mkdir(parents=True, exist_ok=False)
    (output/"tests.log").write_text(log.getvalue())
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("source_sha256", "checks")}, indent=2))
    return 0 if summary["status"] == "PASS_OFFLINE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
