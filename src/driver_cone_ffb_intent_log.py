"""Opt-in dry-run cone FFB intent log for the receiver UI.

Consumes the same-frame motion result (measured range and detector-box centre)
and the receiver telemetry (linear/angular command), then writes the policy-B
intent to JSONL. It never publishes to ROS, never writes to the G923 and
carries no control authority. OFF unless an explicit directory and calibration
are given.

The gate counts *distinct motion results*, not UI refreshes: the receiver UI
calls ``observe`` at video cadence, but a repeated frame is never fed twice.
"""
import json
import math
import queue
from pathlib import Path
import threading
import time

from driver_cone_ffb_intent import ConeFfbIntent, checked_calibration

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'cone_ffb_intent_live_v1'
SUMMARY_SCHEMA = 'cone_ffb_intent_live_summary_v1'
TRANSIENT_REASONS = {'motion_tap_busy'}


def add_cone_intent_arguments(parser):
    group = parser.add_argument_group('optional cone FFB intent dry-run log')
    group.add_argument('--cone-ffb-intent-dir', type=Path,
        help='OFF unless set; NEW directory under recordings/ for the intent JSONL')
    group.add_argument('--cone-ffb-calibration', type=Path,
        help='lateral calibration table JSON (required with --cone-ffb-intent-dir)')


def load_calibration(path):
    value = json.loads(Path(path).read_bytes())
    if type(value) is not dict:
        raise ValueError('lateral calibration object required')
    return checked_calibration(value)


def recorder_from_args(args):
    directory = args.cone_ffb_intent_dir
    calibration = args.cone_ffb_calibration
    if directory is None:
        if calibration is not None:
            raise ValueError('--cone-ffb-calibration requires --cone-ffb-intent-dir')
        return None
    if calibration is None:
        raise ValueError('--cone-ffb-intent-dir requires --cone-ffb-calibration')
    path = directory.resolve()
    if ROOT/'recordings' not in path.parents or path.exists():
        raise ValueError('NEW cone intent directory under this repository recordings/ required')
    return ConeFfbIntentRecorder(path, load_calibration(calibration))


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _center(box):
    if type(box) is not dict:
        return None
    try:
        x1, x2 = float(box['x1']), float(box['x2'])
    except (KeyError, TypeError, ValueError):
        return None
    return (x1 + x2) / 2 if math.isfinite(x1) and math.isfinite(x2) and x1 < x2 else None


def _number_or_none(value):
    return float(value) if _finite(value) else None


class ConeFfbIntentRecorder:
    def __init__(self, directory, calibration, *, clock=time.monotonic, queue_size=256):
        self.directory = Path(directory)
        if self.directory.exists():
            raise ValueError('NEW cone intent directory required')
        self.calibration = checked_calibration(calibration)
        self.intent = ConeFfbIntent(self.calibration)
        self.clock = clock
        self.path = self.directory / 'cone_ffb_intent.jsonl'
        self.summary_path = self.directory / 'cone_ffb_intent_summary.json'
        self.queue = queue.Queue(queue_size)
        self.stop = threading.Event()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name='cone-ffb-intent-writer', daemon=True)
        self.started = self.closed = False
        self.error = None
        self.last_key = None
        self.last_record = None
        self.offered = self.written = self.dropped = self.confirmed = 0
        self.directions = {'-1': 0, '0': 0, '1': 0}
        self.max_magnitude = 0.0
        self.first_at = self.last_at = None

    def start(self):
        if self.started or self.closed or self.stop.is_set():
            raise ValueError('cone intent recorder can start once only')
        self.directory.mkdir(parents=True, exist_ok=False)
        self.started = True
        try:
            self.thread.start()
        except Exception:
            self.started = False
            self.stop.set()
            raise

    def observe(self, snapshot, linear_mps, angular_radps, *, now=None):
        """Feed one UI refresh; only a distinct motion result reaches the gate."""
        if not self.started or self.closed:
            return None
        now = self.clock() if now is None else now
        if not _finite(now):
            return None
        key, values = self._extract(snapshot, linear_mps, angular_radps, now)
        if key is None or key == self.last_key:
            return None
        self.last_key = key
        result = self.intent.offer(values['range_m'], values['box_center_x'],
                                   values['linear_mps'], values['angular_radps'],
                                   valid=values['valid'], at_sec=values['at_sec'])
        record = dict(result)
        record.update(dict(schema=SCHEMA, intent_schema=result.get('schema'),
                      dry_run=True, published_to_ros=False,
                      control_authority=False, calibration_mounting_dependent=True,
                      recorded_at_sec=round(float(now), 6),
                      snapshot_available=values['snapshot_available'],
                      snapshot_reason=values['snapshot_reason'],
                      session=values['session'], frame=values['frame'],
                      box_count=values['box_count'],
                      range_m=None if values['range_m'] is None else round(float(values['range_m']), 6),
                      box_center_x=None if values['box_center_x'] is None else round(float(values['box_center_x']), 3),
                      linear_mps=values['linear_mps'], angular_radps=values['angular_radps']))
        self.offered += 1
        self.last_record = record
        self.last_at = now
        if self.first_at is None:
            self.first_at = now
        self.confirmed += int(bool(result['confirmed']))
        self.directions[str(int(result['direction']))] += 1
        self.max_magnitude = max(self.max_magnitude, float(result['normalized_magnitude']))
        self._enqueue(record)
        return record

    def _extract(self, snapshot, linear_mps, angular_radps, now):
        linear, angular = _number_or_none(linear_mps), _number_or_none(angular_radps)
        values = dict(snapshot_available=False, snapshot_reason='unavailable', session=None,
                      frame=None, box_count=0, range_m=None, box_center_x=None,
                      linear_mps=linear, angular_radps=angular,
                      valid=False, at_sec=now)
        if type(snapshot) is not dict:
            return ('unavailable', 'no_snapshot'), values
        reason = snapshot.get('reason')
        values['snapshot_reason'] = reason if isinstance(reason, str) and len(reason) <= 200 else 'unavailable'
        result = snapshot.get('result')
        if type(result) is dict:
            values['session'] = result.get('session') if isinstance(result.get('session'), str) else None
            values['frame'] = result.get('frame') if type(result.get('frame')) is int else None
            boxes = result.get('selected_detector_boxes')
            values['box_count'] = len(boxes) if type(boxes) is list else 0
            if type(boxes) is list and len(boxes) == 1:
                values['box_center_x'] = _center(boxes[0])
            if snapshot.get('available') is True and result.get('distance_available') is True:
                ranges = result.get('horizontal_camera_foot_range_m')
                if _finite(ranges) and ranges > 0:
                    values['range_m'] = float(ranges)
            values['valid'] = (snapshot.get('available') is True
                               and values['range_m'] is not None
                               and values['box_center_x'] is not None
                               and linear is not None and angular is not None)
            source = result.get('source_time_sec')
            if _finite(source) and source >= 0:
                values['at_sec'] = float(source)
            key = ('result', values['session'], values['frame'])
            values['snapshot_available'] = bool(snapshot.get('available') is True)
            return key, values
        if values['snapshot_reason'] in TRANSIENT_REASONS:
            return None, values
        return ('unavailable', values['snapshot_reason']), values

    def _enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1

    def _run(self):
        try:
            with self.path.open('x') as stream:
                while True:
                    try:
                        item = self.queue.get(timeout=0.1)
                    except queue.Empty:
                        if self.stop.is_set():
                            break
                        continue
                    if item is None:
                        break
                    stream.write(json.dumps(item, allow_nan=False) + '\n')
                    self.written += 1
            self._write_summary()
        except Exception as error:
            self.error = type(error).__name__ + ': ' + str(error)[:200]
        finally:
            self.done.set()

    def _write_summary(self):
        summary = dict(schema=SUMMARY_SCHEMA, dry_run=True, published_to_ros=False,
                       control_authority=False, records_offered=self.offered,
                       records_written=self.written, queue_drops=self.dropped,
                       confirmed_records=self.confirmed, directions=self.directions,
                       max_magnitude=round(self.max_magnitude, 4),
                       first_recorded_at_sec=self.first_at, last_recorded_at_sec=self.last_at,
                       calibration=self.calibration, error=self.error,
                       path=str(self.path))
        self.summary_path.write_text(json.dumps(summary, indent=2) + '\n')

    def request_stop(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.started:
            try:
                self.queue.put(None, timeout=1.0)
            except queue.Full:
                pass
            self.thread.join(timeout=5.0)
            if self.done.is_set() and self.error is None:
                self._write_summary()

    def last_text(self):
        record = self.last_record
        if record is None:
            return 'CONE INTENT (dry-run): waiting for one motion result'
        state = 'CONFIRMED' if record['confirmed'] else record['consistency_reason']
        return (f"CONE INTENT (dry-run): dir={int(record['direction']):+d} "
                f"mag={float(record['normalized_magnitude']):.2f} "
                f"{record['risk_level'] or '-'} {state}")
