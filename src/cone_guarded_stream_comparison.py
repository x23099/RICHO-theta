"""Comparison-stream lifecycle prototype; NOT wired into any live entry point.

Single serialized owner, no threads, file/network I/O, model, ROS or control.
The owner must call admit for each processed input and invalidate on disconnect.
Pin an actually admitted native image, then explicitly activate an analyst's
reference against its original PNG bytes. No historical result is recomputed.
"""
import copy
import hashlib
import re
import struct
import time

import cv2
import numpy as np

from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge
from cone_motion_range import FLAGS, MotionRangeEngine
from cone_self_body_shadow import checked_reference
from cone_upper_support_candidate import observe_upper_completion
from theta_rtc_frames import finite_time, native_frame


class GuardedStreamComparison:
    """Fixed-mount, same-session comparison only. External serialization required.

    No caller-supplied `reference_matches=True` bypass. Up to eight explicitly
    pinned image digests, no image history. A gap longer than the existing frame
    age limit clears both reference and witnesses. After activation only newer
    admitted frames can be compared. poll never holds a stale number.
    """
    def __init__(self, settings, camera, profile, profile_sha256, *, target_roi=None,
                 acknowledged=False, clock=time.monotonic):
        if acknowledged is not True:
            raise ValueError("explicit experimental comparison acknowledgement required")
        self._engine = MotionRangeEngine(settings, camera, profile, profile_sha256,
            acknowledged=True, target_roi=target_roi, observer=observe_upper_completion)
        self._clock = clock
        self._limit = self._engine.settings['frame_max_age_sec']
        self._current = self._latest = self._reference = None
        self._witnesses = {}
        self._generation = 0
        self._retired_sessions = set()
        self._activation_frame = None
        self._closed = False
        self.reason = 'comparison_reference_not_loaded'

    def invalidate(self, reason='comparison_input_interrupted'):
        self._reference = self._latest = self._activation_frame = None
        self._witnesses.clear()
        self.reason = reason

    def _fresh(self, now):
        now = finite_time(now)
        if self._closed:
            raise ValueError('comparison_closed')
        if self._current is None or not 0 <= now-self._current[2] <= self._limit:
            self.invalidate('comparison_input_stale')
            raise ValueError(self.reason)
        return now

    def admit(self, session, sequence, received_at, *, now=None):
        """Admit processed-input identity, NOT a verified physical measurement."""
        if self._closed:
            raise ValueError('comparison_closed')
        try:
            now = finite_time(self._clock() if now is None else now)
            source = finite_time(received_at)
            if (not isinstance(session, str) or not re.fullmatch('[0-9a-f]{32}', session)
                    or type(sequence) is not int or sequence < 1
                    or not 0 <= now-source <= self._limit):
                raise ValueError('fresh bounded native identity required')
            if self._current is not None:
                old_session, old_seq, old_source = self._current
                if session != old_session:
                    self.invalidate('comparison_session_changed')
                    self._retired_sessions.add(old_session)
                    if session in self._retired_sessions or len(self._retired_sessions) > 64:
                        self._closed = True
                        raise ValueError('retired session or session lifetime capacity; new stream required')
                elif sequence <= old_seq or source <= old_source:
                    raise ValueError('strictly increasing comparison input required')
                elif source-old_source > self._limit:
                    self.invalidate('comparison_input_gap')
            self._current = session, sequence, source
        except Exception:
            self.invalidate('comparison_invalid_input')
            raise

    def _matching_frame(self, frame):
        native_frame(frame.image)
        if (frame.session, frame.sequence, frame.received_at) != self._current:
            raise ValueError('comparison requires the currently admitted native frame')

    def pin_reference_frame(self, frame):
        """Explicit snapshot event; pin at most 8 digests, no stored pixels."""
        try:
            self._fresh(self._clock())
            self._matching_frame(frame)
            witness = (frame.received_at, hashlib.sha256(frame.image.tobytes()).hexdigest())
            old = self._witnesses.get(frame.sequence)
            if old is not None and old != witness:
                raise ValueError('pinned frame pixels changed')
            if old is None and len(self._witnesses) >= 8:
                raise ValueError('reference witness capacity reached; do not silently evict')
            self._fresh(self._clock())
            self._witnesses[frame.sequence] = witness
        except Exception:
            self.invalidate('comparison_reference_pin_rejected')
            raise

    def activate(self, reference, png_bytes):
        """Explicit local request, invalidates previous generation even on failure."""
        self._reference = self._latest = self._activation_frame = None
        self._generation += 1
        self.reason = 'comparison_reference_load_failed'
        try:
            self._fresh(self._clock())
            ref = checked_reference(reference)
            if ref['session'] != self._current[0]:
                raise ValueError('reference session mismatch; no rebinding')
            witness = self._witnesses.get(ref['source_frame'])
            if witness is None:
                raise ValueError('reference source was not explicitly pinned in this stream')
            if (type(png_bytes) is not bytes or not 24 <= len(png_bytes) <= 4*1024*1024
                    or png_bytes[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
                    or struct.unpack('>II', png_bytes[16:24]) != (1280, 720)
                    or hashlib.sha256(png_bytes).hexdigest() != ref['source_png_sha256']):
                raise ValueError('bounded native reference PNG/hash required')
            image = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
            native_frame(image)
            if hashlib.sha256(image.tobytes()).hexdigest() != witness[1]:
                raise ValueError('reference PNG does not match admitted native pixels')
            # Loading cost also counts toward input freshness.
            self._fresh(self._clock())
            self._reference = ref
            self._activation_frame = self._current[1]
            self.reason = 'comparison_reference_active_future_frames_only'
        except Exception:
            self._reference = self._latest = self._activation_frame = None
            raise

    def _row(self, frame, original):
        return dict(schema='guarded_stream_comparison_v1', session=frame.session,
            frame=frame.sequence, source_time_sec=frame.received_at,
            result_kind='stream_comparison_prototype_NOT_deployed',
            original_distance_available=original.get('distance_available'),
            original_range_m=original.get('horizontal_camera_foot_range_m'),
            comparison_distance_available=False, comparison_range_m=None,
            comparison_support_pixel=None, reason=self.reason,
            baseline_reproduced=False, reference_generation=self._generation,
            reference_frame=self._reference['source_frame'] if self._reference else None,
            reference_scope_verified=self._reference is not None,
            reference_used_posthoc=False, main_display_modified=False, **FLAGS)

    def compare(self, frame, boxes, original):
        """Compute a separate row; input result/boxes/pixels are never modified."""
        row = self._row(frame, original)
        try:
            started = self._fresh(self._clock())
            self._matching_frame(frame)
            if (original.get('schema') != 'cone_motion_range_v1'
                    or (original.get('session'), original.get('frame'), original.get('source_time_sec'))
                       != self._current
                    or original.get('profile_sha256') != self._engine.profile_sha256
                    or any(original.get(k) is not False for k in FLAGS)
                    or not frame.received_at <= finite_time(original.get('completed_time_sec')) <= started):
                raise ValueError('matching non-controlling main result required')
            if self._reference is None:
                row['reason'] = self.reason
            elif frame.sequence <= self._activation_frame:
                row['reason'] = 'comparison_waiting_for_post_activation_frame'
            else:
                selected = original.get('selected_detector_boxes') or []
                comparison = None
                if len(selected) == 1:
                    comparison = compare_guarded_lower_edge(frame.image, selected[0], self._engine.camera,
                        self._reference, session=frame.session, reference_matches=True)
                baseline = self._engine.measure(frame, boxes, started)
                fields = ('distance_available', 'horizontal_camera_foot_range_m', 'reason',
                          'support_pixel', 'models', 'selected_detector_boxes', 'support_observation')
                if any(baseline.get(k) != original.get(k) for k in fields):
                    raise ValueError('stream baseline cannot be reproduced')
                row['baseline_reproduced'] = True
                proposal = baseline
                if comparison is not None:
                    if comparison['baseline'] != baseline.get('support_observation'):
                        raise ValueError('comparison observation does not match baseline')
                    engine = MotionRangeEngine(self._engine.settings, self._engine.camera,
                        self._engine.profile, self._engine.profile_sha256, acknowledged=True,
                        target_roi=self._engine.target_roi,
                        observer=lambda *args: comparison['proposed_observation'])
                    proposal = engine.measure(frame, boxes, started)
                    row.update(body_review_reason=comparison['proposed_body_review']['reason'],
                        lower_half_pixel_eligible=comparison['lower_half_pixel_eligible'])
                row.update(comparison_distance_available=proposal['distance_available'],
                    comparison_range_m=proposal['horizontal_camera_foot_range_m'],
                    comparison_support_pixel=proposal['support_pixel'], reason=proposal['reason'])
            finished = finite_time(self._clock())
            if finished < started or finished-frame.received_at > self._limit:
                raise ValueError('comparison_processing_too_old')
            row.update(completed_time_sec=finished, comparison_service_ms=1000*(finished-started))
            self._latest = copy.deepcopy(row)
            return copy.deepcopy(row)
        except Exception as error:
            self.invalidate('comparison_failed')
            row.update(comparison_distance_available=False, comparison_range_m=None,
                comparison_support_pixel=None, reference_scope_verified=False,
                reason='comparison_failed', error=f'{type(error).__name__}: {error}'[:300])
            return row

    def poll(self, session):
        """Caller obtains a copy paired to its OWN frame; no reuse after expiry."""
        try:
            now = self._fresh(self._clock())
            if session != self._current[0]:
                self.invalidate('comparison_session_changed')
                return None
            if self._latest is None:
                return None
            if not 0 <= now-self._latest['source_time_sec'] <= self._limit:
                self._latest = None
                return None
            return copy.deepcopy(self._latest)
        except ValueError:
            return None

    def close(self):
        self.invalidate('comparison_closed')
        self._closed = True
