#!/usr/bin/env python3
"""Extend existing offline regression/evidence audit, without hardware/network."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    output = parser.parse_args().output_dir.expanduser().resolve()
    base = ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("distance_runtime_verification", base)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PATTERNS += ("test_summarize_cone_distance_live.py", "test_theta_rtc_capture_recovery.py")
    original = sys.argv
    try:
        sys.argv = [str(base), "--output-dir", str(output)]
        code = module.main()
    finally:
        sys.argv = original
    summary_file = output/"summary.json"
    summary = json.loads(summary_file.read_text())
    summary["work_date"] = "2026-10-28"
    paths = [Path(__file__), Path(__file__).with_name("user_observations.json"),
             ROOT/"src/theta_rtc_diagnostic.py", ROOT/"src/theta_rtc_frames.py",
             ROOT/"src/summarize_cone_distance_live.py", ROOT/"start_cone_distance.sh"]
    for source in paths:
        summary["source_sha256"][str(source.relative_to(ROOT))] = module.sha256(source)
    unchanged = {}
    for name in ("src/theta_rtc_frames.py", "src/cone_distance_core.py", "src/cone_scene_diagnostic.py",
                 "src/cone_distance_diagnostic_config.json", "src/webrtc_stream.py", "src/webrtc_receive_ui.py",
                 "src/start_theta_stream_rtc.sh", "src/start_theta_receive_rtc.sh"):
        old = subprocess.check_output(["git", "show", "HEAD:"+name])
        import hashlib
        unchanged[name] = hashlib.sha256(old).hexdigest() == module.sha256(ROOT/name)
    summary.update(unchanged_from_git_base=unchanged,
        capture_recovery_timeout_sec=3., frame_selection_max_age_sec=.2, receiver_result_max_age_sec=.5,
        scope_extension="Controlled fake-camera threads plus actual in-memory AV media track; 957.4 ms recovery, strict freshness, no repeated frames, bounded timeout, and local probe PNG provenance. No sockets, camera devices or CUDA opened.",
        no_signal_cause_resolved=False, physical_camera_validation_performed=False)
    if not all(unchanged.values()):
        code = 1
        summary["status"] = "FAIL_UNEXPECTED_UNCHANGED_SOURCE_DIFFERENCE"
    summary_file.write_text(json.dumps(summary, indent=2)+"\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
