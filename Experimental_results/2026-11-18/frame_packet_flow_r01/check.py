"""Deterministic logical byte queues + actual packet fragmentation, no sockets."""
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

import cv2

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from driver_frame_packet import encode_packet, unpack_packet, _wrap
from driver_frame_packet_flow import HEADER, MAX_PACKET, LatestPacketSender, PacketReassembler
from test_driver_frame_packet import candidate, SENDER, STREAM
import test_driver_frame_packet_flow


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulate(header, payload, mbps, *, drop_one=False):
    tx = LatestPacketSender(sender_id=SENDER, stream_id=STREAM, message_bytes=16384,
        max_capture_age_sec=.2, max_buffered_bytes=32768)
    rx = PacketReassembler(sender_id=SENDER, stream_id=STREAM, message_bytes=16384, timeout_sec=.2)
    queue, expected, delivered, ages = deque(), {}, [], []
    produced = 0
    dropped = False
    peak_queued = peak_chunk = 0
    # This is a configured logical queue, NOT measured network/codec timing.
    for tick in range(751):
        elapsed = tick*.002
        send_now, receive_now = 10.+elapsed, 700000.+elapsed
        budget = mbps*1e6/8*.002
        while queue and budget > 0:
            chunk, remaining = queue[0]
            used = min(remaining, budget)
            queue[0][1] -= used
            budget -= used
            if queue[0][1] > .000001:
                break
            queue.popleft()
            values = HEADER.unpack_from(chunk)
            if drop_one and not dropped and (values[3], values[5]) == (5, 1):
                dropped = True
            else:
                rx.accept(chunk, received_at_sec=receive_now)
            packet = rx.take(receive_now)
            if packet is not None:
                if packet.wire != expected[packet.sequence]:
                    raise ValueError('reassembled packet mixed source images or metadata')
                delivered.append(packet.sequence)
                ages.append(receive_now-packet.first_received_at_sec)
        # 20 source frames at 20 Hz. Construct new metadata around a static
        # encoded fixture; this does not represent actual motion/image capture.
        if tick and tick%25 == 0 and produced < 20:
            produced += 1
            meta = candidate(sequence=produced, v=.2, w=-.1)
            meta['sender_media_pts'] = (produced-1)*4500
            wire = _wrap(dict(header, candidate=meta, encoded_pts=meta['sender_media_pts']), payload)
            expected[produced] = wire
            if not tx.offer(wire, now=send_now):
                raise ValueError('valid synthetic source offer rejected')
        for _ in range(32):  # Bounded pump budget per logical event.
            amount = int(sum(item[1] for item in queue)+.999999)
            chunk = tx.next_fragment(now=send_now, buffered_amount=amount, channel_open=True)
            if chunk is None:
                break
            queue.append([chunk, float(len(chunk))])
            peak_chunk = max(peak_chunk, len(chunk))
            peak_queued = max(peak_queued, sum(item[1] for item in queue))
        rx.take(receive_now)  # Also runs timeout checks when no packet arrives.
    if not (delivered == sorted(set(delivered)) and peak_queued <= 32768
            and peak_chunk <= 16384 and tx.peak_retained_bytes <= 2*MAX_PACKET
            and rx.peak_retained_bytes <= MAX_PACKET and all(a <= .2 for a in ages)):
        raise ValueError('ordering, queue, frame bound or initial-arrival deadline violated')
    if mbps == 32 and not drop_one and delivered != list(range(1, 21)):
        raise ValueError('uncongested logical model failed complete delivery')
    if drop_one and (5 in delivered or not dropped):
        raise ValueError('missing fragment was silently repaired or test did not inject loss')
    if mbps == 1 and delivered:
        raise ValueError('deadline-infeasible link falsely reported a complete frame')
    tx.close(); rx.close()
    return dict(logical_link_mbps=mbps, drop_frame5_fragment1=drop_one, produced=produced,
        delivered_sequences=delivered, completed=len(delivered), injected_chunk_dropped=dropped,
        sender_counts=tx.counts, receiver_counts=rx.counts,
        max_message_bytes=peak_chunk, max_logical_buffered_bytes=peak_queued,
        peak_sender_retained_packet_bytes=tx.peak_retained_bytes,
        peak_receiver_retained_packet_bytes=rx.peak_retained_bytes,
        max_initial_fragment_to_complete_sec=max(ages) if ages else None,
        retained_after_close=dict(sender=tx.retained_bytes, receiver=rx.retained_bytes),
        simulated_not_measured_network=True, codec_CPU_and_other_traffic_not_modelled=True,
        source_freshness_verified=False, usable_for_ffb=False, published_to_ros=False)


def run(output):
    output = output.resolve()
    if ROOT/'Experimental_results/2026-11-18' not in output.parents or output.exists():
        raise ValueError('unused 11/18 result output required')
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(test_driver_frame_packet_flow))
    if not result.wasSuccessful() or result.skipped:
        raise ValueError('all local flow tests must pass: '+log.getvalue())
    source = ROOT/'recordings/2026-11-16/body_display_full_intake_r02/comparison/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png'
    expected = '7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89'
    if sha(source) != expected:
        raise ValueError('unmodified original pin required')
    pixels = cv2.imread(str(source), cv2.IMREAD_COLOR)
    wire = encode_packet(pixels, candidate())
    header, payload = unpack_packet(wire)
    profiles = [simulate(header, payload, mbps) for mbps in (32, 8, 1)]
    profiles.append(simulate(header, payload, 32, drop_one=True))
    if sha(source) != expected:
        raise ValueError('source file changed')
    previous_path = ROOT/'Experimental_results/2026-11-17/frame_motion_packet_r01/results_r01/audit.json'
    previous = json.loads(previous_path.read_bytes())
    if not all(sha(ROOT/name) == h for name, h in previous['source_code_sha256'].items()):
        raise ValueError('previous packet/source implementation changed')
    body = json.loads((ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    if not all(sha(ROOT/'src'/name) == h for name, h in body['source_code_sha256'].items()):
        raise ValueError('old distance/display changed')
    audit = dict(schema='frame_packet_flow_local_audit_v1', work_date='2026-11-18',
        executed_utc=datetime.now(timezone.utc).isoformat(), work_date_label_is_not_clock_adjustment=True,
        state='pass', tests=result.testsRun, failed=0, skipped=0, logical_profiles=len(profiles),
        representative_packet_bytes=len(wire), source_image_sha256=expected,
        source_image_date='2026-11-16', source_motion_fixture_is_synthetic=True,
        source_images_modified_or_resaved=False,
        previous_packet_audit_sha256=sha(previous_path), old_distance_display_sources_unchanged=12,
        source_code_sha256={name:sha(ROOT/name) for name in
            ('src/driver_frame_packet_flow.py', 'tests/test_driver_frame_packet_flow.py',
             str(Path(__file__).resolve().relative_to(ROOT)))},
        profiles=profiles, existing_RTC_ROS_FFB_wiring_modified=False,
        real_network_or_camera_or_G923_started=False, live_transport_adopted=False,
        clock_binding_created=False, source_freshness_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    with (output/'audit.json').open('x') as stream:
        json.dump(audit, stream, indent=2, allow_nan=False); stream.write('\n')
    with (output/'tests.txt').open('x') as stream:
        stream.write(log.getvalue())
    print(json.dumps(dict(state='pass', tests=result.testsRun,
        profiles=[dict(mbps=p['logical_link_mbps'], loss=p['drop_frame5_fragment1'],
                       completed=p['completed'], replaced=p['sender_counts']['pending_replaced']) for p in profiles]), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args().output_dir)
