"""Run the offline regression suite and record the probe-stage source manifest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TESTS = [
    'tests/test_frame_packet_gpu_recompression.py',
    'tests/test_frame_packet_gpu_submission_audit.py',
    'tests/test_driver_frame_packet.py',
    'tests/test_driver_frame_motion.py',
    'tests/test_cone_motion_range.py',
    'tests/test_driver_frame_packet_runtime.py',
    'tests/test_driver_frame_packet_channel.py',
    'tests/test_frame_packet_saved_suite.py',
    'tests/test_frame_packet_saved_suite_audit.py',
    'tests/test_frame_packet_preservation.py',
    'tests/test_driver_lossless_frame_packet.py',
    'tests/test_driver_lossless_frame_sender.py',
    'tests/test_lossless_sender_load_model.py',
    'tests/test_driver_frame_packet_flow.py',
    'tests/test_lossless_packet_gpu.py',
    'tests/test_lossless_packet_gpu_submission.py',
    'tests/test_network_coexistence_collect.py',
    'tests/test_network_coexistence_trial.py',
    'tests/test_network_udp_audit.py',
    'tests/test_network_udp_audit_v2.py',
    'tests/test_driver_frame_packet_probe.py',
    'tests/test_png_link_probe_audit.py',
]
SOURCES = [
    'src/driver_frame_packet_probe.py',
    'src/webrtc_stream.py',
    'src/webrtc_receive_ui.py',
    'src/start_theta_receive_rtc.sh',
    'Experimental_results/2026-11-18/png_link_probe_r01/audit_probe.py',
    'tests/test_driver_frame_packet_probe.py',
    'tests/test_png_link_probe_audit.py',
]


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or not output.is_relative_to(HERE):
        parser.error('unused local verification output required')
    for name in TESTS + SOURCES:
        if not (ROOT / name).is_file():
            parser.error('missing test/source: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'pytest', '-q', *TESTS]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120,
                            env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                                     OPENBLAS_NUM_THREADS='1'))
    log = result.stdout + result.stderr
    with (output / 'tests.txt').open('x') as target:
        target.write(log)
    count = re.search(r'(\d+) passed in ([0-9.]+)s', log)
    if result.returncode != 0 or count is None or 'skipped' in log:
        raise SystemExit('regression failure:\n' + log)
    report = dict(
        schema='png_link_probe_verification_v1', state='pass',
        tests_passed=int(count[1]), failed=0, skipped=0, elapsed_sec=float(count[2]),
        command=command, source_sha256={name: digest(name) for name in SOURCES},
        default_off_transport_only=True,
        inference_or_ros_path_started=False, real_network_test_started=False,
        video_or_control_modified_by_probe=False,
        network_udp_frozen_source_note=(
            'verify_udp.py/verify_udp_v2.py freeze the pre-probe SHA of '
            'src/webrtc_stream.py and src/webrtc_receive_ui.py; re-running them after this '
            'stage requires the 11/18 pre-probe commit. Saved UDP audits are unchanged.'),
        usable_for_ffb=False, physical_metric_verified=False, published_to_ros=False)
    with (output / 'audit.json').open('x') as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({key: report[key] for key in ('state', 'tests_passed', 'elapsed_sec')}, indent=2))


if __name__ == '__main__':
    main()
