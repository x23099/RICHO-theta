"""Preserved-image, real concurrent encoders, fake sink; NOT a live benchmark."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import patch
import uuid

import av
import cv2
import numpy as np
from aiortc.codecs.vpx import Vp8Encoder

import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
import driver_frame_packet_channel as packet_channel
from driver_frame_packet_flow import HEADER
from driver_frame_motion import SenderFrameMotion, FLAGS
from driver_odometry_observation import OdometryObserver
from theta_rtc_frames import native_frame

PIN = 'recordings/2026-11-16/body_display_full_intake_r02/comparison/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png'
EVIDENCE = 'recordings/2026-11-13/guarded_motion_full_intake_r02/logs/evidence/'
SOURCES = [(PIN, '7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89')]+[
    (EVIDENCE+'decoded_24aad0a8d31d46eeb33ef252b0d18475_f'+frame+'.png', digest)
    for frame, digest in (
        ('028980', '1d6aae33fefd99a58ddbe6c01d6b2fe02cb37f8961317b0d9a897cb6c6aac74f'),
        ('037696', '17ae1e55225ca083bd58bcac9097f19211fd0abfe52c0163a411f2f51088ae1d'),
        ('044793', 'bd6ebf33da1ac1e849a5bb3c277dd2ebc44ec23e8a69e0c0009e10d25d291230'))]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(values):
    if not values:
        return dict(count=0, minimum=None, median=None, p95=None, maximum=None)
    array = np.asarray(values, dtype=float)
    return dict(count=len(values), minimum=float(array.min()), median=float(np.median(array)),
                p95=float(np.percentile(array, 95)), maximum=float(array.max()))


def packet_due(tick, rate):
    if type(tick) is not int or tick < 0 or type(rate) is not int or rate not in (0, 5, 10, 30):
        raise ValueError('bounded 30Hz replay tick and explicit probe rate required')
    return rate != 0 and tick % (30//rate) == 0


def load_images():
    audit13 = json.loads((ROOT/'Experimental_results/2026-11-13/guarded_motion_live_audit_r02/results_r01/audit.json').read_bytes())
    audit16 = json.loads((ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    # Find the exact supplied-file manifest, not a new locally invented digest.
    def digests(value):
        if isinstance(value, dict):
            for key, val in value.items():
                if key.endswith('.png') and isinstance(val, str):
                    yield key, val
                else:
                    yield from digests(val)
        elif isinstance(value, list):
            for val in value:
                yield from digests(val)
    known = dict(digests(audit13)) | dict(digests(audit16))
    images = []
    for name, expected in SOURCES:
        if not any(key.endswith(Path(name).name) and val == expected for key, val in known.items()):
            raise ValueError('source SHA not found in original audit: '+name)
        if sha(ROOT/name) != expected:
            raise ValueError('source original changed: '+name)
        pixels = cv2.imread(str(ROOT/name), cv2.IMREAD_COLOR)
        native_frame(pixels)
        pixels.flags.writeable = False
        images.append(pixels)
    return images


class VideoWorker:
    """Persistent aiortc encoder; at most one active and one latest pending."""
    def __init__(self):
        self.lock, self.wake, self.stop = threading.Lock(), threading.Event(), threading.Event()
        self.pending = self.error = None
        self.replaced = self.expired = 0
        self.records = []  # Offline finite trial only; <= 151 jobs.
        self.thread = threading.Thread(target=self._run, name='benchmark-video', daemon=True)
        self.thread.start()

    def submit(self, sequence, image, captured):
        owned = image.copy()  # Producer copy also consumes real trial CPU.
        with self.lock:
            if self.pending is not None:
                self.replaced += 1
            self.pending = sequence, owned, captured
            self.wake.set()

    def _run(self):
        try:
            encoder = Vp8Encoder()
            encoder.target_bitrate = 1500000
            self.effective_bitrate = encoder.target_bitrate
            while not self.stop.is_set():
                self.wake.wait()
                with self.lock:
                    self.wake.clear()
                    job, self.pending = self.pending, None
                if job is None:
                    continue
                sequence, pixels, captured = job
                start = time.monotonic()
                if start-captured > .2:
                    self.expired += 1
                    continue
                frame = av.VideoFrame.from_ndarray(pixels, format='bgr24')
                source_pts = (sequence-1)*3000
                frame.pts, frame.time_base = source_pts, Fraction(1, 90000)
                payloads, pts = encoder.encode(frame)
                end = time.monotonic()
                # The installed streaming encoder can round by one 90 kHz
                # tick during its internal reformat/codec time-base conversion.
                # This RTP output is NOT used for the atomic packet identity.
                if abs(pts-source_pts) > 1:
                    raise ValueError('unexpected streaming codec timestamp span')
                self.records.append(dict(kind='video', sequence=sequence, captured_at_sec=captured,
                    started_at_sec=start, finished_at_sec=end, encode_ms=(end-start)*1000,
                    admission_to_finish_ms=(end-captured)*1000, payload_bytes=sum(map(len, payloads)),
                    messages=len(payloads), source_pts=source_pts, returned_pts=pts))
        except Exception as error:
            self.error = repr(error)

    def close(self):
        self.stop.set(); self.wake.set()
        self.thread.join(1.)
        if self.thread.is_alive() or self.error:
            raise ValueError('video worker failed/blocked: '+str(self.error))


class FakeSink:
    label = protocol = packet_channel.PROTOCOL
    ordered, maxRetransmits, maxPacketLifeTime = False, 0, None
    readyState, bufferedAmount = 'open', 0

    def __init__(self):
        self.records = []
        self.current = None
        self.message_bytes = self.messages = 0

    def send(self, message):
        # Immediate fake drain. No network queue, SCTP or receiver decode.
        _, _, _, sequence, _, index, count, _ = HEADER.unpack_from(message)
        if self.current is None or self.current[0] != sequence:
            self.current = [sequence, 0]
        if index != self.current[1] or len(message) > 16384:
            raise ValueError('fragment order/cap changed')
        self.current[1] += 1
        self.messages += 1
        self.message_bytes += len(message)
        if index+1 == count:
            self.records.append((sequence, time.monotonic()))
            self.current = None

    def close(self):
        self.readyState = 'closed'


def source_pair(observer, source, sequence):
    # Explicit replay fixture; NOT the stored camera image's odometry or capture.
    observer.observe(NS(header=NS(stamp=NS(sec=1000+sequence, nanosec=0), frame_id='odom'),
        child_frame_id='base_footprint', twist=NS(twist=NS(linear=NS(x=0.), angular=NS(z=0.)))))
    observation = observer.snapshot()
    if not source.offer(observation):
        raise ValueError('synthetic observer offer failed')
    admitted = time.monotonic()
    # callback and snapshot genuinely precede this synthetic replay admission.
    value = source.associate(capture_sequence=sequence, captured_at_sec=admitted,
        media_pts=(sequence-1)*3000, associated_at_sec=admitted)
    if not value['local_pair_available'] or any(value[key] for key in FLAGS):
        raise ValueError('synthetic candidate invalid or flags promoted')
    return value


def trial(images, workload, rate, repetition, *, duration=3., warmup=.5):
    video, sink = VideoWorker(), FakeSink()
    observer = OdometryObserver()
    stream = uuid.uuid4().hex
    source = SenderFrameMotion(sender_id=observer.sender_id, stream_id=stream, capacity=4,
        max_callback_lag_sec=.1, max_progress_lag_sec=.1, max_capture_wait_sec=.2,
        motion_frame_id='base_footprint')
    tx = packet_channel.FramePacketChannelSender(sink, sender_id=observer.sender_id,
        stream_id=stream, message_bytes=16384, max_capture_age_sec=.2, max_buffered_bytes=32768)
    encoded, admitted = [], []
    original = packet_channel.encode_packet
    def measured(image, value):
        start = time.monotonic()
        wire = original(image, value)
        end = time.monotonic()
        encoded.append(dict(kind='packet', sequence=value['capture_sequence'],
            captured_at_sec=value['captured_at_sec'], started_at_sec=start, finished_at_sec=end,
            encode_ms=(end-start)*1000, admission_to_finish_ms=(end-value['captured_at_sec'])*1000,
            payload_bytes=len(wire), messages=0,
            source_pts=value['sender_media_pts'], returned_pts=value['sender_media_pts']))
        return wire
    start = time.monotonic()
    begin, end = start+warmup, start+warmup+duration
    next_tick, skipped = 0, 0
    cpu_start = wall_start = cpu_end = wall_end = None
    try:
        with patch.object(packet_channel, 'encode_packet', measured):
            while True:
                now = time.monotonic()
                if cpu_start is None and now >= begin:
                    cpu_start, wall_start = time.process_time(), now
                if now >= end:
                    cpu_end, wall_end = time.process_time(), now
                    break
                tick = int((now-start)*30)
                if tick >= next_tick:
                    skipped += tick-next_tick
                    next_tick = tick+1
                    sequence = tick+1
                    pixels = images[0 if workload == 'static_repeat' else tick % len(images)]
                    video.submit(sequence, pixels, now)
                    if packet_due(tick, rate):
                        value = source_pair(observer, source, sequence)
                        if not tx.submit(pixels, value):
                            raise ValueError('packet producer rejected: '+str(tx.worker.error))
                        admitted.append((sequence, value['captured_at_sec']))
                tx.pump(budget=8)
                if tx.closed or tx.worker.retired.is_set():
                    raise ValueError('packet adapter retired: '+str(tx.error or tx.worker.error))
                time.sleep(.0005)
            # Tail only drains; never fabricate new captures or extend their age.
            tail_end = time.monotonic()+.22
            while time.monotonic() < tail_end:
                tx.pump(budget=8)
                time.sleep(.0005)
            worker_counts = dict(replaced=tx.worker.replaced, peak_queued=tx.worker.peak_queued)
            sender_counts = dict(tx.scheduler.counts)
            if not tx.close(timeout_sec=1.):
                raise ValueError('packet codec did not stop within finite join')
            video.close()
    finally:
        tx.close(timeout_sec=1.)
        video.close()
    def selected(row):
        return begin <= row['captured_at_sec'] < end
    video_rows, packet_rows = [r for r in video.records if selected(r)], [r for r in encoded if selected(r)]
    selected_admitted = {seq:t for seq,t in admitted if begin <= t < end}
    completed = [(seq,t) for seq,t in sink.records if seq in selected_admitted]
    missing = sorted(set(selected_admitted)-{seq for seq,_ in completed})
    if (len(completed) != len({seq for seq,_ in completed})
            or any(t-selected_admitted[seq] > .201 for seq,t in completed)):
        raise ValueError('duplicate completed group or sender age extended')
    rows = video_rows+packet_rows
    for row in rows:
        row.update(workload=workload, packet_hz=rate, repetition=repetition,
                   source_admission_time_is_synthetic=True)
    video_output = [r for r in video_rows if r['messages'] > 0]
    events = []
    admission_times = dict(admitted)
    for kind, values in (('offered', admitted), ('send_complete', sink.records)):
        for sequence, at in values:
            events.append(dict(workload=workload, packet_hz=rate, repetition=repetition,
                event=kind, sequence=sequence, local_time_sec=at,
                admitted_at_sec=admission_times[sequence],
                in_measurement_window=begin <= admission_times[sequence] < end))
    summary = dict(workload=workload, packet_hz=rate, repetition=repetition,
        requested_video_hz=30, duration_sec=duration, warmup_sec=warmup,
        process_cpu_sec=cpu_end-cpu_start, process_cpu_cores=(cpu_end-cpu_start)/(wall_end-wall_start),
        measured_cpu_window_wall_sec=wall_end-wall_start, video_encoded=len(video_output),
        video_codec_empty=len(video_rows)-len(video_output),
        video_completed_rate_hz=len(video_output)/duration,
        video_encode_ms=describe([r['encode_ms'] for r in video_rows]),
        video_admission_to_finish_ms=describe([r['admission_to_finish_ms'] for r in video_rows]),
        video_payload_mbps=sum(r['payload_bytes'] for r in video_rows)*8/duration/1e6,
        packet_offered=len(selected_admitted), packet_encoded=len(packet_rows), packet_completed=len(completed),
        packet_missing_sequences=missing,
        packet_encode_ms=describe([r['encode_ms'] for r in packet_rows]),
        packet_admission_to_fake_send_ms=describe([(t-selected_admitted[seq])*1000 for seq,t in completed]),
        packet_encoded_mbps=sum(r['payload_bytes'] for r in packet_rows)*8/duration/1e6,
        total_fake_sink_message_bytes_including_warmup_tail=sink.message_bytes,
        total_fake_sink_messages_including_warmup_tail=sink.messages,
        packet_wire_bytes=describe([r['payload_bytes'] for r in packet_rows]),
        timer_ticks_skipped_including_warmup=skipped, video_pending_replaced=video.replaced,
        video_expired_before_encode=video.expired, packet_worker_counts=worker_counts,
        packet_scheduler_counts=sender_counts, video_effective_bitrate_bps=video.effective_bitrate,
        all_workers_stopped=True, actual_network_measured=False)
    return summary, rows, events


def run(output):
    output = output.resolve()
    if ROOT/'Experimental_results/2026-11-18/frame_packet_load_r01' not in output.parents or output.exists():
        raise ValueError('unused result directory beneath this experiment required')
    baseline = json.loads((ROOT/'Experimental_results/2026-11-18/frame_packet_channel_r01/results_r01/audit.json').read_bytes())
    frozen = baseline['source_code_sha256'] | baseline['unchanged_runtime_source_sha256']
    if any(sha(ROOT/name) != digest for name,digest in frozen.items()):
        raise ValueError('prior channel or existing runtime changed')
    versions = {name:importlib.metadata.version(name) for name in ('av','aiortc','numpy')}
    versions['cv2_module'] = cv2.__version__  # May be apt/headless, not opencv-python distribution.
    encoder_path = Path(inspect.getfile(Vp8Encoder))
    images = load_images()
    pixel_hashes = [hashlib.sha256(p.tobytes()).hexdigest() for p in images]
    summaries, rows, events = [], [], []
    profiles = [(workload,rate) for workload in ('static_repeat','discontinuous_cycle') for rate in (0,5,10,30)]
    output.mkdir(parents=True,exist_ok=False)
    # Preserve each finite trial even if a later trial or final metadata fails.
    with (output/'trial_progress.jsonl').open('x') as progress:
        for repetition in (1,2):
            for workload,rate in profiles if repetition == 1 else reversed(profiles):
                summary, samples, trial_events = trial(images,workload,rate,repetition)
                summaries.append(summary); rows.extend(samples); events.extend(trial_events)
                progress.write(json.dumps(dict(summary=summary,samples=samples,events=trial_events),allow_nan=False)+'\n')
                progress.flush()
                print(json.dumps(dict(workload=workload,rate=rate,repeat=repetition,
                    video=summary['video_encoded'], packet=summary['packet_completed'],
                    missing=len(summary['packet_missing_sequences']),
                    cpu_cores=round(summary['process_cpu_cores'],3))), flush=True)
    if any(sha(ROOT/name) != digest for name,digest in SOURCES):
        raise ValueError('original source file changed')
    if pixel_hashes != [hashlib.sha256(p.tobytes()).hexdigest() for p in images]:
        raise ValueError('input pixels changed')
    if any(sha(ROOT/name) != digest for name,digest in frozen.items()):
        raise ValueError('existing sources changed during benchmark')
    audit = dict(schema='frame_packet_encode_load_local_v1', state='completed_NOT_live_adoption',
        work_date='2026-11-18', executed_utc=datetime.now(timezone.utc).isoformat(),
        timing_host='analysis_PC_NOT_matunuc_or_GPUPC', platform=platform.platform(),
        logical_cpu_count=os.cpu_count(), cpu_affinity=sorted(os.sched_getaffinity(0)),
        versions=versions, cv2_module_file=cv2.__file__,
        installed_video_encoder_file=str(encoder_path), installed_video_encoder_sha256=sha(encoder_path),
        packet_and_runtime_sources_unchanged=frozen,
        source_images=[dict(path=name,sha256=digest,pixel_sha256=pixel_hashes[i]) for i,(name,digest) in enumerate(SOURCES)],
        source_images_or_pixels_modified=False, compressed_or_decoded_camera_images_saved=False,
        replay_capture_and_motion_are_synthetic=True, source_sequence_not_real_video_timing=True,
        bitrate_is_explicit_fixed_codec_setting_NOT_negotiated_live=True,
        real_network_or_camera_or_ROS_or_G923_started=False,
        SCTP_DTLS_receiver_decode_YOLO_control_load_included=False,
        fake_sink_has_unlimited_instant_drain=True, trials=summaries,
        source_code_sha256={str(Path(__file__).resolve().relative_to(ROOT)):sha(Path(__file__))},
        source_freshness_verified=False, physical_metric_verified=False, usable_for_ffb=False,
        published_to_ros=False, live_transport_adopted=False, git_operations_performed=False)
    with (output/'samples.csv').open('x',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    with (output/'events.csv').open('x',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(events[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(events)
    with (output/'audit.json').open('x') as file:
        json.dump(audit,file,ensure_ascii=False,indent=2,allow_nan=False);file.write('\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
