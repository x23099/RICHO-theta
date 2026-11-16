"""Sender-local frame/motion candidates, NOT live wiring or clock sync.

Capture time means camera read-return, not exposure. Callback age is not
measurement age. Receiver RTP PTS must NOT be assumed to equal sender PTS.
No ROS, network, images, filesystem IO, interpolation or FFB authority.
"""
from collections import deque
import threading

from driver_odometry_observation import checked_observation, clock_time
from driver_motion_handoff import session_ok

SCHEMA = 'sender_frame_motion_candidate_v1'
FLAGS = dict(receiver_frame_identity_verified=False, exposure_time_verified=False,
    header_clock_relation_verified=False, source_freshness_verified=False,
    physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False,
    published_to_ros=False)
SAMPLE_IDENTITY = ('callback_sequence', 'callback_received_mono_sec', 'header_stamp_ns',
    'motion_frame_id', 'pose_frame_id', 'linear_mps', 'angular_radps', 'stamp_status',
    'stamp_progress_mono_sec', 'sample_fields_valid', 'invalid_fields')


def positive_limit(value):
    return type(value) in (int, float) and clock_time(value) and 0 < value <= 1


class SenderFrameMotion:
    """One stream, bounded observation history, nonblocking offers/selection.

    The caller must use the SAME sender monotonic clock as the odom observer.
    Timestamp regressions/scope violations retire this instance. Bad current
    samples remain barriers: selection never skips back over them for rescue.
    """
    def __init__(self, *, sender_id, stream_id, capacity, max_callback_lag_sec,
                 max_progress_lag_sec, max_capture_wait_sec, motion_frame_id):
        from driver_odometry_observation import frame_id
        if (not session_ok(sender_id) or not session_ok(stream_id)
                or type(capacity) is not int or not 1 <= capacity <= 1024
                or not all(positive_limit(v) for v in (max_callback_lag_sec,
                    max_progress_lag_sec, max_capture_wait_sec)) or not frame_id(motion_frame_id)):
            raise ValueError('explicit source identity, bounded history and local policies required')
        self.sender_id, self.stream_id = sender_id, stream_id
        self.clock_id = 'sender-process/'+sender_id
        self.policy = dict(capacity=capacity, max_callback_lag_sec=max_callback_lag_sec,
            max_progress_lag_sec=max_progress_lag_sec, max_capture_wait_sec=max_capture_wait_sec,
            motion_frame_id=motion_frame_id)
        self.history = deque(maxlen=capacity)
        self.lock = threading.Lock()
        self.fault = None
        self.last_snapshot = self.last_capture = self.last_associate = None
        self.last_frame = self.last_pts = 0
        self.last_observation = None
        self.evicted = self.busy_offers = 0
        self.accepted_busy_count = 0
        self.last_dropped_callbacks = 0

    def _retire(self, reason):
        self.history.clear()
        self.fault = reason
        return False

    def offer(self, observation):
        """Copy an existing versioned snapshot; no original values are modified."""
        if not self.lock.acquire(blocking=False):
            self.busy_offers += 1
            return False
        try:
            if self.fault is not None:
                return False
            if self.accepted_busy_count != self.busy_offers:
                # A failed offer may have contained an invalid/newer callback.
                # Do not reuse the old history across this unobserved gap.
                self.history.clear()
                self.accepted_busy_count = self.busy_offers
            try:
                value = checked_observation(observation)
            except (ValueError, TypeError, KeyError, OverflowError):
                return self._retire('invalid_odometry_observation')
            if value['sender_id'] != self.sender_id or value['sender_monotonic_clock_id'] != self.clock_id:
                return self._retire('foreign_sender_observation')
            now = value['snapshot_mono_sec']
            if (now is None or value['stamp_status'] == 'clock_invalid'
                    or self.last_snapshot is not None and now < self.last_snapshot
                    or self.last_associate is not None and now < self.last_associate):
                return self._retire('sender_clock_reversed_or_invalid')
            previous = self.last_observation
            self.last_snapshot = now
            drops = value['dropped_callbacks']
            if drops < self.last_dropped_callbacks:
                return self._retire('odometry_drop_counter_reversed')
            if drops > self.last_dropped_callbacks:
                self.history.clear()
            self.last_dropped_callbacks = drops
            # Unknown/busy observations cannot safely be skipped in favour of
            # a formerly valid sample. A new fully observed callback may recover.
            if value['callback_received'] is not True:
                self.history.clear()
                if value['callback_received'] is False and self.last_observation is not None:
                    return self._retire('odometry_state_reset')
                return True
            if previous is not None and previous['callback_received'] is True:
                if (value['callback_sequence'] < previous['callback_sequence']
                        or value['callback_received_mono_sec'] < previous['callback_received_mono_sec']):
                    return self._retire('odometry_order_reversed')
                if value['callback_sequence'] == previous['callback_sequence']:
                    if any(value[k] != previous[k] for k in SAMPLE_IDENTITY):
                        return self._retire('same_callback_identity_changed')
                    return True
                if value['callback_sequence'] > previous['callback_sequence']+1:
                    # Missing callbacks may include invalid samples. They are
                    # not evidence that a previously observed value persisted.
                    self.history.clear()
            self.last_observation = value
            if len(self.history) == self.history.maxlen:
                self.evicted += 1
            self.history.append(value)
            return True
        finally:
            self.lock.release()

    def associate(self, *, capture_sequence, captured_at_sec, media_pts, associated_at_sec):
        """Select the latest OBSERVED callback no later than read-return time.

        media_pts is the sender track's 90 kHz timestamp, not a receiver key.
        A caller must not turn local_pair_available into measurement validity.
        """
        if (type(capture_sequence) is not int or not 0 < capture_sequence < 2**63
                or type(media_pts) is not int or not 0 <= media_pts < 2**63
                or not clock_time(captured_at_sec) or not clock_time(associated_at_sec)
                or captured_at_sec > associated_at_sec):
            # Invalid frame identity must never leave historical values reusable.
            self.fault = 'invalid_frame_identity_or_time'
            if self.lock.acquire(blocking=False):
                try:
                    self.history.clear()
                finally:
                    self.lock.release()
            raise ValueError('explicit causal source capture identity required')
        result = dict(schema=SCHEMA, sender_id=self.sender_id, stream_id=self.stream_id,
            sender_monotonic_clock_id=self.clock_id, capture_sequence=capture_sequence,
            captured_at_sec=captured_at_sec, associated_at_sec=associated_at_sec,
            capture_time_basis='camera_read_return_NOT_sensor_exposure',
            sender_media_pts=media_pts, media_clock_rate=90000,
            receiver_media_pts=None, local_pair_available=False, odometry_observation=None,
            callback_to_capture_sec=None, progress_to_capture_sec=None,
            capture_wait_sec=associated_at_sec-captured_at_sec,
            policy=dict(self.policy), **FLAGS)
        def withheld(reason):
            result['reason'] = reason
            return result
        if not self.lock.acquire(blocking=False):
            return withheld('association_busy')
        try:
            if self.fault is not None:
                return withheld(self.fault)
            if self.accepted_busy_count != self.busy_offers:
                self.history.clear()
                return withheld('odometry_history_gap')
            if (capture_sequence <= self.last_frame
                    or self.last_capture is not None and captured_at_sec <= self.last_capture
                    or self.last_associate is not None and associated_at_sec < self.last_associate
                    or self.last_snapshot is not None and associated_at_sec < self.last_snapshot
                    or self.last_capture is not None and media_pts <= self.last_pts):
                self._retire('source_frame_or_clock_order_reversed')
                return withheld(self.fault)
            self.last_frame, self.last_pts = capture_sequence, media_pts
            self.last_capture, self.last_associate = captured_at_sec, associated_at_sec
            if result['capture_wait_sec'] > self.policy['max_capture_wait_sec']:
                return withheld('capture_wait_exceeded')
            past = next((v for v in reversed(self.history)
                         if v['callback_received_mono_sec'] <= captured_at_sec), None)
            if past is None:
                return withheld('no_observed_past_callback')
            if not past['sample_fields_valid']:
                return withheld('latest_past_callback_invalid')
            if past['motion_frame_id'] != self.policy['motion_frame_id']:
                return withheld('motion_frame_mismatch')
            if past['stamp_status'] not in ('first', 'advanced'):
                return withheld('latest_past_source_stamp_not_advanced')
            lag = captured_at_sec-past['callback_received_mono_sec']
            progress_lag = captured_at_sec-past['stamp_progress_mono_sec']
            if lag > self.policy['max_callback_lag_sec']:
                return withheld('callback_to_capture_limit_exceeded')
            if progress_lag > self.policy['max_progress_lag_sec']:
                return withheld('source_stamp_progress_limit_exceeded')
            result.update(local_pair_available=True, reason='sender_local_candidate_NOT_verified_measurement',
                odometry_observation=checked_observation(past), callback_to_capture_sec=lag,
                progress_to_capture_sec=progress_lag)
            if self.accepted_busy_count != self.busy_offers:
                result.update(local_pair_available=False, odometry_observation=None,
                    callback_to_capture_sec=None, progress_to_capture_sec=None)
                self.history.clear()
                return withheld('odometry_history_gap')
            return result
        finally:
            self.lock.release()
