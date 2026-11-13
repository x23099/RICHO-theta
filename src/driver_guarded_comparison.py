"""Opt-in async comparison ONLY. No camera, YOLO, network, UI, ROS or control.

offer borrows immutable native pixels and the exact immutable primary log line;
all parsing, comparison, encoding and file I/O occur on a serialized daemon.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time

from cone_fixed_floor_live_load import bounded_regular_bytes
from driver_withheld_evidence import _atomic_new
from theta_rtc_frames import native_frame

MAX_LINE = 1024*1024
MAX_ROW = 16384


def comparison_path(path, repo_root=None):
    root = (Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1])/'recordings'
    root, path = root.resolve(), Path(path).expanduser().resolve()
    if root not in path.parents or path.exists():
        raise ValueError('comparison requires a NEW subdirectory under repository recordings/')
    return path


def parse_json(data):
    def reject(value):
        raise ValueError('nonfinite JSON: '+value)
    return json.loads(data, parse_constant=reject)


@dataclass(frozen=True)
class ComparisonLimits:
    max_log_bytes: int = 64*1024*1024
    max_snapshots: int = 8
    max_requests: int = 128

    def __post_init__(self):
        for value, low, high in ((self.max_log_bytes, 1024, 64*1024*1024),
                                (self.max_snapshots, 1, 8), (self.max_requests, 1, 128)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('bounded integer comparison limits required')


class GuardedComparisonWorker:
    def __init__(self, directory, settings, camera, profile, profile_sha256, *, target_roi=None,
                 clock=time.monotonic, limits=None, stream_factory=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.clock, self.limits = clock, limits or ComparisonLimits()
        self.lock = threading.Lock()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.pending = self.ingress = self.latest = None
        self._display_reference = None
        self._display_verified_source = None
        self.offered = self.dropped = self.busy_drops = self.processed = 0
        self.saved = self.log_bytes = self.request_count = 0
        self.last_request = 0
        self.pin_pending = None
        self.error = None
        self.info = dict(state='starting', request_id=None, request_action=None, detail=None)
        self.source_sha256 = {}
        self._args = (copy.deepcopy(settings), camera, copy.deepcopy(profile), profile_sha256, target_roi)
        self._factory = stream_factory
        self.thread = threading.Thread(target=self._run, name='driver-guarded-comparison', daemon=True)
        self.thread.start()

    def offer(self, frame, primary_line):
        """Never wait/copy/hash/parse/encode/write on the main measurement path."""
        if not self.lock.acquire(blocking=False):
            self.busy_drops += 1
            return False
        try:
            if self.stop.is_set() or self.error:
                return False
            native_frame(frame.image)
            if (frame.image.flags.writeable or type(primary_line) is not str
                    or not 0 < len(primary_line) <= MAX_LINE or not primary_line.endswith('\n')):
                return False
            if self.pending is not None:
                self.dropped += 1
            if self.ingress is not None and self.ingress[0] != frame.session:
                self.latest = None
            self.pending = (frame, primary_line)
            self.ingress = frame.session, frame.sequence, frame.received_at
            self.offered += 1
            self.wake.set()
            return True
        finally:
            self.lock.release()

    def snapshot(self):
        with self.lock:
            latest = self.latest
            now = self.clock()
            if (self.stop.is_set() or self.error or latest is None or self.ingress is None
                    or latest['session'] != self.ingress[0]
                    or not 0 <= now-self.ingress[2] <= .5
                    or not 0 <= now-latest['source_time_sec'] <= .5):
                latest = None
            return dict(schema='driver_guarded_comparison_status_v1', **copy.deepcopy(self.info),
                offered=self.offered, latest_slot_overwrites=self.dropped, tap_busy_drops=self.busy_drops,
                processed=self.processed, snapshots_saved=self.saved, log_bytes=self.log_bytes,
                request_count=self.request_count, max_requests=self.limits.max_requests,
                max_log_bytes=self.limits.max_log_bytes, max_snapshots=self.limits.max_snapshots,
                error=self.error, latest=copy.deepcopy(latest),
                status_time_sec=now, ingress=list(self.ingress) if self.ingress else None,
                source_sha256=dict(self.source_sha256),
                main_display_modified=False, physical_metric_verified=False, floor_contact_verified=False,
                controlling_distance=False, usable_for_ffb=False, published_to_ros=False)

    def _state(self, state, **detail):
        with self.lock:
            self.info.update(state=state, **detail)

    def _clear(self):
        with self.lock:
            self.latest = None
            self._display_reference = self._display_verified_source = None

    def display_reference_snapshot(self):
        """Nonblocking small reference copy; never exposes an async distance."""
        if not self.lock.acquire(blocking=False):return None
        try:
            now=self.clock()
            ref=self._display_reference
            if (self.stop.is_set() or self.error or self.info['state']!='active' or ref is None
                    or self.ingress is None or self.ingress[0]!=ref['reference']['session']
                    or self._display_verified_source is None
                    or not 0<=now-self._display_verified_source<=.5 or not 0<=now-self.ingress[2]<=.5):return None
            return copy.deepcopy(ref)
        finally:self.lock.release()

    def _status(self, *, done=False):
        value = self.snapshot()
        value.update(writer_done=done, shutdown_complete=done and self.error is None)
        data = (json.dumps(value, allow_nan=False, indent=2)+'\n').encode()
        if len(data) > 16384:
            raise ValueError('comparison status exceeds bound')
        temporary = self.directory/'comparison_status.json.part'
        with temporary.open('xb') as stream:
            stream.write(data)
        os.replace(temporary, self.directory/'comparison_status.json')

    def _request(self, stream):
        path = self.directory/'request.json'
        try:
            request = parse_json(bounded_regular_bytes(path, 16384))
        except FileNotFoundError:
            return
        except Exception as error:
            # Unreadable/bad local request must not leave the old model active.
            stream.invalidate('comparison_invalid_request')
            self.pin_pending = None
            self._clear()
            self._state('request_rejected', detail=f'{type(error).__name__}: {error}'[:300])
            return
        if (not isinstance(request, dict) or set(request) != {'schema', 'request_id', 'action'}
                or request.get('schema') != 'driver_guarded_request_v1'
                or type(request.get('request_id')) is not int or not 1 <= request['request_id'] < 2**63
                or request.get('action') not in ('pin', 'load', 'invalidate')):
            stream.invalidate('comparison_invalid_request');self._clear()
            self.pin_pending = None
            self._state('request_rejected', detail='invalid bounded local request')
            return
        if request['request_id'] <= self.last_request:
            return
        self.last_request = request['request_id']
        self.request_count += 1
        if self.request_count > self.limits.max_requests:
            raise ValueError('comparison request budget exhausted')
        self._clear()
        self.pin_pending = None
        self._state('requested', request_id=self.last_request, request_action=request['action'], detail=None)
        action = request['action']
        if action == 'pin':
            stream.invalidate('comparison_pin_requested')
            self.pin_pending = self.last_request
            self._state('pin_pending')
        elif action == 'invalidate':
            stream.invalidate('explicit_comparison_invalidation')
            self._state('invalidated')
        else:
            # Clear the published status BEFORE any slow file/decode operation.
            self._state('loading');self._status()
            try:
                ref = parse_json(bounded_regular_bytes(self.directory/'reference.json', 32768))
                from cone_self_body_shadow import checked_reference
                ref = checked_reference(ref)
                name = f"decoded_{ref['session']}_f{ref['source_frame']:06d}.png"
                png = bounded_regular_bytes(self.directory/name, 4*1024*1024)
                stream.activate(ref, png)
                verified=stream.verified_reference_snapshot()
                with self.lock:
                    self._display_reference=verified
                    self._display_verified_source=verified['verified_source_time_sec']
                self._state('active')
            except Exception as error:
                stream.invalidate('comparison_reference_load_failed')
                self._state('load_rejected', detail=f'{type(error).__name__}: {error}'[:300])
        self._status()

    def _pin(self, stream, frame, line):
        import cv2
        if self.saved >= self.limits.max_snapshots:
            raise ValueError('comparison snapshot budget exhausted')
        stream.pin_reference_frame(frame)
        ok, encoded = cv2.imencode('.png', frame.image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise OSError('comparison snapshot encoding failed')
        png = encoded.tobytes()
        if len(png) > 3*1280*720+65536:
            raise ValueError('comparison snapshot exceeds native bound')
        if not 0 <= self.clock()-frame.received_at <= .5:
            raise ValueError('comparison pin processing too old')
        stem = f'decoded_{frame.session}_f{frame.sequence:06d}'
        metadata = dict(schema='driver_guarded_pin_v1', request_id=self.pin_pending,
            session=frame.session, frame=frame.sequence, source_time_sec=frame.received_at,
            png_sha256=hashlib.sha256(png).hexdigest(),
            decoded_bgr_sha256=hashlib.sha256(frame.image.tobytes()).hexdigest(),
            source_log_line_sha256=hashlib.sha256(line.encode()).hexdigest(),
            image_file=stem+'.png', image_size=[1280, 720], image_modified=False,
            physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)
        _atomic_new(self.directory/(stem+'.png'), png)
        _atomic_new(self.directory/(stem+'.json'), (json.dumps(metadata)+'\n').encode())
        self.saved += 1
        self.pin_pending = None
        self._state('pinned', pin=metadata)

    def _run(self):
        stream = None
        try:
            from cone_guarded_stream_comparison import GuardedStreamComparison
            settings, camera, profile, sha, roi = self._args
            factory = self._factory or GuardedStreamComparison
            stream = factory(settings, camera, profile, sha, target_roi=roi,
                acknowledged=True, clock=self.clock)
            names = ('driver_guarded_comparison.py', 'cone_guarded_stream_comparison.py',
                'cone_guarded_lower_edge_shadow.py', 'cone_bbox_boundary_shadow.py',
                'cone_self_body_shadow.py', 'cone_motion_range.py', 'cone_upper_support_candidate.py',
                'cone_support_completion_candidate.py', 'driver_motion_process.py')
            self.source_sha256 = {name: hashlib.sha256(bounded_regular_bytes(
                Path(__file__).with_name(name), 256*1024)).hexdigest() for name in names}
            self._state('waiting_reference')
            with (self.directory/'comparison_frames.jsonl').open('x') as log:
                self._status()
                last_status = self.clock()
                while not self.stop.is_set():
                    self._request(stream)
                    with self.lock:
                        item, self.pending = self.pending, None
                        self.wake.clear()
                    if item is None:
                        # poll performs expiry, but never invents an image/result.
                        with self.lock:
                            ingress = self.ingress
                        if ingress:
                            stream.poll(ingress[0])
                            if self.info['state'] == 'active' and stream.reason != 'comparison_reference_active_future_frames_only':
                                self._state('invalidated', detail=stream.reason)
                        if self.clock()-last_status >= .1:
                            self._status();last_status = self.clock()
                        self.wake.wait(.05)
                        continue
                    frame, line = item
                    original = parse_json(line)
                    from driver_motion_protocol import checked_result, compact_result
                    checked_result(compact_result(original), frame)
                    try:
                        stream.admit(frame.session, frame.sequence, frame.received_at)
                    except ValueError as error:
                        self._clear();self._state('invalidated', detail=str(error)[:300]);continue
                    if self.pin_pending is not None:
                        try:
                            self._pin(stream, frame, line)
                        except Exception as error:
                            stream.invalidate('comparison_pin_failed')
                            self.pin_pending = None
                            self._clear();self._state('pin_rejected', detail=str(error)[:300])
                        self._status()
                    row = stream.compare(frame, original.get('selected_detector_boxes') or [], original)
                    with self.lock:
                        if row['reference_scope_verified']:
                            self._display_verified_source=frame.received_at
                        else:
                            self._display_reference=self._display_verified_source=None
                    if self.info['state'] == 'active' and row['reference_scope_verified'] is not True:
                        self._state('invalidated', detail=row['reason'])
                    row['result_kind'] = 'async_current_frame_comparison_NOT_main_display'
                    with self.lock:
                        current = self.ingress
                    if (self.stop.is_set() or current is None or current[0] != frame.session
                            or not 0 <= self.clock()-frame.received_at <= .5):
                        row.update(comparison_distance_available=False, comparison_range_m=None,
                            comparison_support_pixel=None, reason='comparison_result_retired')
                    data = json.dumps(row, allow_nan=False)+'\n'
                    size = len(data.encode())
                    if size > MAX_ROW or self.log_bytes+size > self.limits.max_log_bytes:
                        raise ValueError('comparison log budget exhausted')
                    log.write(data);log.flush()
                    with self.lock:
                        self.processed += 1
                        self.log_bytes += size
                        self.latest = None if self.stop.is_set() else row
                    if self.clock()-last_status >= .1:
                        self._status();last_status = self.clock()
                stream.close()
            self._state('closed')
        except Exception as error:
            with self.lock:
                self.error = f'{type(error).__name__}: {error}'[:500]
                self.info['state'] = 'disabled'
        finally:
            if stream is not None:
                stream.close()
            self._clear()
            try:
                self._status(done=True)
            except Exception:
                pass  # Disk failure must not propagate to main range/control.

    def close(self, timeout=.25):
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 <= timeout <= 2:
            raise ValueError('bounded 0..2 second comparison close required')
        self.stop.set();self.wake.set()
        with self.lock:
            self.latest = self.pending = None
        self.thread.join(timeout)
        return dict(writer_stopped=not self.thread.is_alive(), shutdown_complete=not self.thread.is_alive()
            and self.error is None, error=self.error)
