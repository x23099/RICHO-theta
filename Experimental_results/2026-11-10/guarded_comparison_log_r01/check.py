"""比較コマンドの合成テストとhelpのみ。実機は開始しない。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    output = parser.parse_args().output_dir.resolve()
    if output.exists():raise ValueError("new output required")
    log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_guarded_recording_comparison.py")
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    help_run = subprocess.run([sys.executable, str(ROOT / "src/run_guarded_recording_comparison.py"), "--help"],
        capture_output=True, text=True, timeout=10.)
    sources = [Path(__file__), ROOT / "src/run_guarded_recording_comparison.py", ROOT / "tests/test_guarded_recording_comparison.py"]
    summary = dict(status="PASS_OFFLINE_ONLY" if result.wasSuccessful() and help_run.returncode == 0 else "FAIL",
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        help_exitcode=help_run.returncode, actual_camera_model_ros_or_vehicle_started=False,
        source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    output.mkdir(parents=True, exist_ok=False)
    (output / "tests.log").write_text(log.getvalue())
    (output / "help.txt").write_text(help_run.stdout + help_run.stderr)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}, indent=2))
    return 0 if summary["status"] == "PASS_OFFLINE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
