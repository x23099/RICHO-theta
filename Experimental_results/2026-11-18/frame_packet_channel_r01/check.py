"""Fake channel regression + source invariance; no peer/socket/device startup."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
TESTS = [
    'test_driver_frame_packet_channel.py', 'test_driver_frame_packet_flow.py',
    'test_driver_frame_packet.py', 'test_driver_frame_motion.py',
    'test_driver_odometry_observation.py', 'test_driver_motion_integration.py',
    'test_collision_ffb_relay.py', 'test_collision_ffb_publisher.py',
    'test_driver_sender_clock_observation.py', 'test_driver_telemetry_recording.py',
    'test_theta_rtc_diagnostic.py']
RUNTIME = ['src/webrtc_stream.py', 'src/webrtc_receive_ui.py', 'src/theta_rtc_frames.py',
    'src/driver_odometry_observation.py', 'src/driver_sender_clock_observation.py',
    'src/driver_telemetry_recording.py', 'src/collision_ffb_relay.py', 'src/collision_ffb_publisher.py']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    output = output.resolve()
    if ROOT/'Experimental_results/2026-11-18/frame_packet_channel_r01' not in output.parents or output.exists():
        raise ValueError('unused output beneath this experiment required')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    runtime_hashes = {}
    for name in RUNTIME:
        before = subprocess.check_output(['git', 'show', head+':'+name], cwd=ROOT)
        if hashlib.sha256(before).hexdigest() != sha(ROOT/name):
            raise ValueError('existing runtime changed: '+name)
        runtime_hashes[name] = sha(ROOT/name)
    distance_path = ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json'
    distance = json.loads(distance_path.read_bytes())
    for name, digest in distance['source_code_sha256'].items():
        if sha(ROOT/'src'/name) != digest:
            raise ValueError('old distance/display changed: '+name)
    old_packet_path = ROOT/'Experimental_results/2026-11-17/frame_motion_packet_r01/results_r01/audit.json'
    previous = json.loads(old_packet_path.read_bytes())
    for name, digest in previous['source_code_sha256'].items():
        if sha(ROOT/name) != digest:
            raise ValueError('previous source/codec implementation changed: '+name)
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    command = [sys.executable, '-m', 'pytest', '-q']+['tests/'+name for name in TESTS]
    test = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    log = test.stdout+test.stderr
    count = re.search(r'(\d+) passed in ([0-9.]+)s', log)
    if test.returncode or count is None or 'skipped' in log:
        raise ValueError('all regression tests must pass: '+log)
    sources = ['src/driver_frame_packet_channel.py', 'src/driver_frame_packet_flow.py',
               'tests/test_driver_frame_packet_channel.py', str(Path(__file__).resolve().relative_to(ROOT))]
    # Last checks are byte comparisons, not a claim of verified live equivalence.
    if any(sha(ROOT/name) != digest for name, digest in runtime_hashes.items()):
        raise ValueError('existing runtime modified during tests')
    audit = dict(schema='frame_packet_channel_fake_audit_v1', state='pass', work_date='2026-11-18',
        executed_utc=datetime.now(timezone.utc).isoformat(), baseline_head=head,
        tests_passed=int(count[1]), failed=0, skipped=0, regression_elapsed_sec=float(count[2]),
        pytest_command=command, source_code_sha256={name:sha(ROOT/name) for name in sources},
        unchanged_runtime_source_sha256=runtime_hashes,
        old_distance_display_sources_unchanged=len(distance['source_code_sha256']),
        distance_audit_sha256=sha(distance_path), previous_packet_audit_sha256=sha(old_packet_path),
        new_channel_tests=34, codec_and_packet_workers_real=True, transport_is_fake=True,
        synthetic_native_image_and_motion=True, camera_image_read_or_modified=False,
        sender_clock_fixture_sec=10.05, receiver_clock_fixture_sec=700000.,
        message_policy_bytes=16384, channel_buffer_policy_bytes=32768,
        receiver_inbox_max_messages=128, receiver_inbox_max_payload_bytes=128*16384,
        receiver_assembly_max_packet_bytes=2105399, receiver_deadline_fixture_sec=.2,
        deadline_is_first_fragment_not_source_age=True,
        nonblocking_ingress_lock=True, callback_hash_or_codec_or_disk_io=False,
        encoder_active_jobs=1, encoder_latest_pending_jobs=1,
        hung_codec_close_does_not_claim_worker_stopped=True,
        source_freshness_verified=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False, live_transport_adopted=False,
        real_peer_or_socket_or_ROS_or_camera_or_G923_started=False,
        existing_control_or_display_wiring_modified=False, clock_binding_created=False,
        git_commit_push_pull_performed=False)
    output.mkdir(parents=True, exist_ok=False)
    with (output/'tests.txt').open('x') as stream:
        stream.write(log)
    with (output/'audit.json').open('x') as stream:
        json.dump(audit, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(state='pass', tests_passed=int(count[1]), runtime_sources_unchanged=len(runtime_hashes),
        old_distance_display_sources_unchanged=audit['old_distance_display_sources_unchanged'],
        real_network_started=False), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args().output_dir)
