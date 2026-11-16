"""Opt-in passive receiver telemetry log. No ROS, control, images or joining.

Only a bounded scalar copy is offered in RTC; all serialization and disk I/O
run on a dedicated thread. Legacy values are NOT verified motion samples.
"""
import hashlib
import json
import logging
import math
from pathlib import Path
import queue
import re
import threading
import time
import uuid

from driver_odometry_observation import SCHEMA as ODOM_SCHEMA, decode_observation
from driver_sender_clock_observation import SCHEMA as CLOCK_SCHEMA, decode_clock_observation

ROOT = Path(__file__).resolve().parents[1]
NUMBERS = {'linear_x': 'linear_mps', 'angular_z': 'angular_radps',
           'speed_mps': 'speed_mps', 'imu_yaw_rate': 'imu_yaw_rate_radps',
           'timestamp': 'sender_wall_time_ms'}
LIFECYCLE = {'peer_begin', 'peer_closed', 'peer_failed', 'peer_disconnected', 'video_track_ended'}
FALSE_FLAGS = dict(physical_metric_verified=False, controlling_distance=False,
                   usable_for_ffb=False, published_to_ros=False)


def finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and abs(value) <= 1e15
    except OverflowError:
        return False


def add_recording_arguments(parser):
    group = parser.add_argument_group('optional passive receiver telemetry recording')
    group.add_argument('--telemetry-record-dir', type=Path, help='OFF unless set; NEW directory under recordings/')
    group.add_argument('--telemetry-record-max-mib', type=int, default=16)
    group.add_argument('--telemetry-record-max-records', type=int, default=100000)
    group.add_argument('--telemetry-record-queue-size', type=int, default=128)


def recorder_from_args(args):
    limits = (args.telemetry_record_max_mib, args.telemetry_record_max_records, args.telemetry_record_queue_size)
    if args.telemetry_record_dir is None:
        if limits != (16, 100000, 128):
            raise ValueError('telemetry limits require --telemetry-record-dir')
        return None
    if any(type(v) is not int or not 1 <= v <= bound for v, bound in zip(limits, (1024, 1000000, 4096))):
        raise ValueError('bounded positive telemetry recording limits required')
    path = args.telemetry_record_dir.resolve()
    if ROOT/'recordings' not in path.parents or path.exists():
        raise ValueError('NEW telemetry directory under this repository recordings/ required')
    return TelemetryRecorder(path, max_bytes=limits[0]*1024**2, max_records=limits[1], queue_size=limits[2])


class TelemetryRecorder:
    def __init__(self, directory, *, max_bytes, max_records, queue_size, clock=time.monotonic):
        if any(type(v) is not int or not 1 <= v <= bound for v, bound in
               ((max_bytes, 1024**3), (max_records, 1000000), (queue_size, 4096))):
            raise ValueError('positive bounded recorder limits required')
        self.directory, self.clock = Path(directory), clock
        self.clock_id = 'receiver-process/'+uuid.uuid4().hex
        self.max_bytes, self.max_records = max_bytes, max_records
        self.queue = queue.Queue(queue_size)
        self.lock, self.stop, self.done = threading.Lock(), threading.Event(), threading.Event()
        self.started = False
        self.state, self.error = 'not_started', None
        self.offered = self.queued = self.queue_drops = self.busy_drops = self.rejected = 0
        self.written = self.bytes = self.discarded = self.in_flight = 0
        self.max_offer_ms = 0.
        self.thread = threading.Thread(target=self._run, name='driver-telemetry-writer', daemon=True)

    def start(self):
        if self.started or self.stop.is_set():
            raise ValueError('telemetry recorder can start once only')
        self.started = True
        try:
            self.thread.start()
        except Exception as error:
            self.started = False
            self.state, self.error = 'start_failed', type(error).__name__
            self.stop.set()
            raise

    def lifecycle(self, session, kind, received_at_sec):
        return self._offer(session, kind, None, received_at_sec)

    def offer(self, session, data, received_at_sec):
        return self._offer(session, 'telemetry', data, received_at_sec)

    def _offer(self, session, kind, data, received):
        started = time.perf_counter()
        if not self.lock.acquire(blocking=False):
            # RTC has one producer thread; this counter does not take the
            # writer's lock or wait for it. It is diagnostic, not control state.
            self.busy_drops += 1
            return False
        try:
            self.offered += 1
            if (not self.started or self.stop.is_set() or self.done.is_set()
                    or not isinstance(session, str) or re.fullmatch('[0-9a-f]{32}', session) is None
                    or not finite(received) or received < 0
                    or kind not in LIFECYCLE|{'telemetry'} or (kind == 'telemetry' and type(data) is not dict)):
                self.rejected += 1
                return False
            values, invalid = {}, []
            for source, target in NUMBERS.items():
                value = data.get(source) if kind == 'telemetry' else None
                if value is not None and (not finite(value) or (source == 'timestamp' and value < 0)):
                    invalid.append(source); value = None
                values[target] = value
            record = dict(schema='driver_received_telemetry_v1', session=session, sequence=self.offered,
                receiver_clock_id=self.clock_id, received_at_sec=received, event_kind=kind,
                source_kind='legacy_telemetry' if kind == 'telemetry' else None,
                source_clock_id=None, source_stamp_ns=None, motion_frame_id=None,
                measurement_valid=None, source_freshness_verified=False,
                invalid_fields=invalid, **values, **FALSE_FLAGS)
            if kind == 'telemetry' and 'odometry_observation' in data:
                observation, state = decode_observation(data['odometry_observation'])
                record.update(schema='driver_received_telemetry_v2', odometry_metadata_state=state,
                              odometry_observation=observation)
            if kind == 'telemetry' and 'sender_clock_observation' in data:
                clock, state = decode_clock_observation(data['sender_clock_observation'])
                observed = record.get('odometry_observation')
                if clock is not None and observed is not None and clock['sender_id'] != observed['sender_id']:
                    clock, state = None, 'sender_clock_scope_mismatch'
                record.update(schema='driver_received_telemetry_v3', sender_clock_metadata_state=state,
                              sender_clock_observation=clock)
            try:
                self.queue.put_nowait(record)
            except queue.Full:
                self.queue_drops += 1
                return False
            self.queued += 1
            return True
        finally:
            self.max_offer_ms = max(self.max_offer_ms, 1000*(time.perf_counter()-started))
            self.lock.release()

    def request_stop(self):
        self.stop.set()

    def snapshot(self):
        with self.lock:
            return dict(schema='driver_telemetry_recording_summary_v1', state=self.state, error=self.error,
                receiver_clock_id=self.clock_id, offered=self.offered, queued=self.queued,
                queue_drops=self.queue_drops, busy_drops=self.busy_drops, rejected=self.rejected,
                written=self.written, log_bytes=self.bytes, discarded_pending=self.discarded,
                pending=self.queue.qsize(), in_flight=self.in_flight,
                max_records=self.max_records, max_bytes=self.max_bytes,
                queue_capacity=self.queue.maxsize, max_offer_ms=self.max_offer_ms,
                stop_requested=self.stop.is_set(), writer_done=self.done.is_set(),
                shutdown_complete=self.done.is_set() or not self.started,
                source_time_or_validity_inferred=False, control_channel_modified=False,
                distance_computation_modified=False, **FALSE_FLAGS)

    def close(self, timeout_sec=2.):
        if not finite(timeout_sec) or not 0 <= timeout_sec <= 10:
            raise ValueError('bounded recorder shutdown timeout required')
        self.request_stop()
        if self.started:
            self.thread.join(timeout=timeout_sec)
        return self.snapshot()

    def _write_record(self, stream, wire):
        stream.write(wire)
        stream.flush()

    def _run(self):
        owned = False
        try:
            self.directory.mkdir(parents=True, exist_ok=False)
            owned = True
            metadata = dict(schema='driver_telemetry_recording_metadata_v1', receiver_clock_id=self.clock_id,
                clock_basis='time.monotonic_in_receiver_process_shared_with_native_video_receive',
                source_time_basis='unknown_NOT_sender_wall_timestamp',
                versioned_source_motion_metadata_supported=True, values_are_received_not_verified_measurements=True,
                supported_odometry_schema=ODOM_SCHEMA,
                supported_sender_clock_schema=CLOCK_SCHEMA,
                record_schemas=['driver_received_telemetry_v1', 'driver_received_telemetry_v2',
                                'driver_received_telemetry_v3'],
                image_or_arbitrary_message_saved=False, **FALSE_FLAGS)
            metadata['source_sha256'] = {name: hashlib.sha256((ROOT/'src'/name).read_bytes()).hexdigest()
                                        for name in ('driver_telemetry_recording.py', 'webrtc_receive_ui.py',
                                                     'driver_odometry_observation.py',
                                                     'driver_sender_clock_observation.py')}
            with (self.directory/'telemetry_recording_metadata.json').open('x') as stream:
                json.dump(metadata, stream, indent=2); stream.write('\n')
            with (self.directory/'received_telemetry.jsonl').open('xb') as stream:
                with self.lock:
                    self.state = 'recording'
                while not self.stop.is_set() or not self.queue.empty():
                    try:
                        record = self.queue.get(timeout=.02)
                    except queue.Empty:
                        continue
                    with self.lock:
                        self.in_flight = 1
                    now = self.clock()
                    if not finite(now) or now < record['received_at_sec']:
                        raise ValueError('invalid or reversed receiver writer clock')
                    record['logged_at_sec'] = now
                    wire = (json.dumps(record, allow_nan=False, separators=(',', ':'))+'\n').encode()
                    if len(wire) > 16*1024 or self.written >= self.max_records or self.bytes+len(wire) > self.max_bytes:
                        with self.lock:
                            self.state = 'limit_reached'; self.discarded += 1; self.in_flight = 0
                        self.stop.set()
                        logging.getLogger(__name__).warning('Telemetry recording limit reached; driver continues')
                        break
                    self._write_record(stream, wire)
                    with self.lock:
                        self.written += 1; self.bytes += len(wire); self.in_flight = 0
                with self.lock:
                    if self.state == 'recording':
                        self.state = 'closed'
        except Exception as error:
            with self.lock:
                self.state, self.error = 'writer_error', type(error).__name__+': '+str(error)[:250]
            self.stop.set()
            logging.getLogger(__name__).error('Telemetry writer stopped; driver continues: %s', self.error)
        finally:
            with self.lock:
                self.discarded += self.in_flight; self.in_flight = 0
            while True:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break
                with self.lock:
                    self.discarded += 1
            if owned:
                try:
                    with (self.directory/'telemetry_recording_summary.json').open('x') as stream:
                        summary = self.snapshot()
                        summary.update(writer_done=True, shutdown_complete=True)
                        json.dump(summary, stream, indent=2); stream.write('\n')
                except Exception as error:
                    with self.lock:
                        self.state = 'writer_error'
                        self.error = 'summary_write_failed: '+type(error).__name__
            self.done.set()
