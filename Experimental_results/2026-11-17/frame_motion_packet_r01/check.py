"""Offline packet correctness + one preserved native image codec comparison."""
import argparse
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import statistics
import sys
import time
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from driver_frame_packet import encode_packet, unpack_packet, FramePacketReceiver
from test_driver_frame_packet import candidate, SENDER, STREAM
import test_driver_frame_packet


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(values):
    return dict(count=len(values), minimum=min(values), median=statistics.median(values), maximum=max(values))


def run(output):
    output = output.resolve()
    if ROOT/'Experimental_results/2026-11-17' not in output.parents or output.exists():
        raise ValueError('unused 11/17 experiment output required')
    log = io.StringIO()
    test = unittest.TextTestRunner(stream=log, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_driver_frame_packet))
    if not test.wasSuccessful() or test.skipped:
        raise ValueError('all packet cases must pass without skipping: '+log.getvalue())
    previous = ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json'
    previous_audit = json.loads(previous.read_bytes())
    source = ROOT/'recordings/2026-11-16/body_display_full_intake_r02/comparison/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png'
    expected = previous_audit['supplied_files_sha256']['comparison/'+source.name]
    if sha(source) != expected:
        raise ValueError('source image differs from verified original')
    pixels = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if pixels is None or pixels.shape != (720, 1280, 3):
        raise ValueError('native source pixels required')
    before_pixels = hashlib.sha256(pixels.tobytes()).hexdigest()
    receiver = FramePacketReceiver(sender_id=SENDER, stream_id=STREAM, max_receive_age_sec=.2)
    cases = []
    for i in range(1, 6):
        meta = candidate(sequence=i, v=-.2 if i%2 else .2, w=.1)
        start = time.perf_counter_ns()
        wire = encode_packet(pixels, meta)
        encoded = time.perf_counter_ns()
        decoded = receiver.accept(wire, received_at_sec=1000.+i)
        finished = time.perf_counter_ns()
        if decoded.candidate != meta or decoded.image.shape != pixels.shape:
            raise ValueError('atomic candidate/image roundtrip failed')
        header, payload = unpack_packet(wire)
        png_start = time.perf_counter_ns()
        okay, png = cv2.imencode('.png', pixels)
        png_end = time.perf_counter_ns()
        if not okay or not np.array_equal(cv2.imdecode(png, cv2.IMREAD_COLOR), pixels):
            raise ValueError('PNG comparison lost source pixels')
        cases.append(dict(iteration=i, synthetic_capture_sequence=i, synthetic_motion_metadata=True,
            packet_bytes=len(wire), vp8_payload_bytes=len(payload), png_bytes=len(png), raw_bgr_bytes=pixels.nbytes,
            packet_encode_ms=(encoded-start)/1e6, packet_decode_and_copy_ms=(finished-encoded)/1e6,
            png_encode_ms=(png_end-png_start)/1e6, source_pts=meta['sender_media_pts'],
            encoded_pts=header['encoded_pts'], metadata_equal=True,
            decoded_is_pixel_identical=bool(np.array_equal(decoded.image, pixels)),
            decoded_mean_absolute_pixel_difference=float(np.mean(np.abs(decoded.image.astype(np.int16)-pixels.astype(np.int16)))),
            packet_sha256=hashlib.sha256(wire).hexdigest()))
    if sha(source) != expected or hashlib.sha256(pixels.tobytes()).hexdigest() != before_pixels:
        raise ValueError('source image or pixels were modified')
    frozen = json.loads((ROOT/'Experimental_results/2026-11-16/sender_frame_motion_r01/results_r01/audit.json').read_bytes())
    frozen_files = ['src/driver_frame_motion.py', 'src/driver_odometry_observation.py',
        'src/theta_rtc_diagnostic.py', 'src/webrtc_stream.py', 'src/webrtc_receive_ui.py',
        'src/collision_ffb_relay.py', 'src/collision_ffb_publisher.py']
    if not all(sha(ROOT/name) == frozen['source_sha256'][name] for name in frozen_files):
        raise ValueError('previous runtime or source associator changed')
    if not all(sha(ROOT/'src'/name) == value for name, value in previous_audit['source_code_sha256'].items()):
        raise ValueError('old distance/display changed')
    metric_names = ['packet_bytes', 'vp8_payload_bytes', 'png_bytes', 'packet_encode_ms',
                    'packet_decode_and_copy_ms', 'png_encode_ms', 'decoded_mean_absolute_pixel_difference']
    summary = {name:stats([row[name] for row in cases]) for name in metric_names}
    audit = dict(schema='frame_motion_packet_local_audit_v1', work_date='2026-11-17',
        executed_utc=datetime.now(timezone.utc).isoformat(), work_date_label_is_not_clock_adjustment=True,
        state='pass', packet_tests=test.testsRun, skipped=0, failed=0, source_image_sha256=expected,
        source_image_session=previous_audit['session'], source_image_frame=previous_audit['pin_frame'],
        original_source_file_unchanged=True, source_pixels_not_modified=True,
        synthetic_motion_metadata_NOT_actual_image_odometry_pairing=True,
        encoded_or_decoded_camera_images_saved=False, timing_host='local_analysis_PC_NOT_matunuc_or_GPU',
        iterations=len(cases), metrics=summary,
        nominal_30fps_estimates_NOT_actual_network_measurements=dict(
            vp8_packet_mbps=summary['packet_bytes']['median']*30*8/1e6,
            png_payload_mbps=summary['png_bytes']['median']*30*8/1e6,
            raw_bgr_mbps=pixels.nbytes*30*8/1e6),
        old_runtime_sources_unchanged=frozen_files, old_distance_display_sources_unchanged=12,
        source_code_sha256={name:sha(ROOT/name) for name in
            ('src/driver_frame_packet.py', 'src/driver_frame_motion.py', 'tests/test_driver_frame_packet.py',
             str(Path(__file__).resolve().relative_to(ROOT)))},
        library_versions={name:importlib.metadata.version(name) for name in ('av', 'numpy')},
        packet_is_authentication=False, original_RTP_received_frame_matched=False,
        network_started=False, live_camera_or_ROS_started=False, clock_binding_created=False,
        runtime_wiring_changed=False, live_transport_adopted=False,
        source_freshness_verified=False, exposure_time_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    with (output/'audit.json').open('x') as stream:
        json.dump(audit, stream, indent=2, allow_nan=False); stream.write('\n')
    with (output/'codec_samples.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(cases[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(cases)
    with (output/'tests.txt').open('x') as stream:
        stream.write(log.getvalue())
    print(json.dumps(dict(state=audit['state'], tests=test.testsRun, metrics=summary), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.output_dir)
