"""OFFLINE range handoff only. Not a ROS message, risk or G923 command.

The clock is the recorded receiver's monotonic clock, not wall/ROS time.
No live caller imports this module. A scalar radius never supplies vehicle XY.
"""
import math
import re
from types import SimpleNamespace

from driver_body_display_guard import checked_display_review
from driver_motion_protocol import checked_result

SCHEMA = 'offline_motion_range_handoff_v1'
MAX_AGE_SEC = .5
FALSE_FLAGS = ('physical_metric_verified', 'floor_contact_verified', 'controlling_distance',
               'usable_for_ffb', 'published_to_ros', 'target_association_verified',
               'steering_gradient_available', 'ffb_command_generated')
FIELDS = {'schema', 'session', 'frame', 'source_time_sec', 'review_completed_time_sec',
          'evaluated_time_sec', 'clock_basis', 'max_age_sec', 'metric', 'input_verified',
          'range_available', 'distance_m', 'reason', 'primary_model', 'reference_generation',
          'reference_frame', 'reference_png_sha256', 'vehicle_xy_m', 'object_id', 'replay_only', *FALSE_FLAGS}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def session_ok(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{32}', value) is not None


def make_range_sample(event, *, session, now_source_clock_sec):
    if not session_ok(session) or not finite(now_source_clock_sec):
        raise ValueError('explicit session and nonnegative source-clock evaluation time required')
    packet = dict(schema=SCHEMA, session=None, frame=None, source_time_sec=None,
        review_completed_time_sec=None, evaluated_time_sec=now_source_clock_sec,
        clock_basis='recorded_receiver_monotonic_NOT_ROS_or_wall_time', max_age_sec=MAX_AGE_SEC,
        metric='horizontal_camera_foot_range_m_NOT_base_link_or_contact', input_verified=False,
        range_available=False, distance_m=None, reason='handoff_invalid_event', primary_model=None,
        reference_generation=None, reference_frame=None, reference_png_sha256=None,
        vehicle_xy_m=None, object_id=None, replay_only=True, **{k: False for k in FALSE_FLAGS})

    def reject(reason):
        packet['reason'] = reason
        return packet

    if not isinstance(event, dict) or set(event) != {'result', 'display_review', 'accepted_current_session_and_age'}:
        return packet
    value = event['result']
    if not isinstance(value, dict):
        return packet
    if not (session_ok(value.get('session')) and type(value.get('frame')) is int
            and value['frame'] > 0 and finite(value.get('source_time_sec'))):
        return reject('handoff_invalid_identity')
    packet.update(session=value['session'], frame=value['frame'], source_time_sec=value['source_time_sec'])
    if value['session'] != session:
        return reject('handoff_session_mismatch')
    try:
        checked_result(value, SimpleNamespace(session=session, sequence=value['frame'], received_at=value['source_time_sec']))
        review = checked_display_review(event['display_review'], value)
    except (ValueError, TypeError, KeyError):
        return reject('handoff_invalid_source_review')
    packet.update(review_completed_time_sec=review['completed_time_sec'], primary_model=value['primary_model'],
        reference_generation=review['reference_generation'], reference_frame=review['reference_frame'],
        reference_png_sha256=review['reference_png_sha256'])
    if type(event['accepted_current_session_and_age']) is not bool:
        return reject('handoff_invalid_bridge_acceptance')
    if not event['accepted_current_session_and_age']:
        return reject('handoff_bridge_result_retired')
    if now_source_clock_sec < review['completed_time_sec']:
        return reject('handoff_source_or_review_in_future')
    if now_source_clock_sec-value['source_time_sec'] > MAX_AGE_SEC:
        return reject('handoff_sample_stale')
    packet.update(input_verified=True, range_available=review['display_available'],
                  distance_m=review['display_range_m'], reason=review['reason'])
    return packet


def checked_sample(packet):
    if (not isinstance(packet, dict) or set(packet) != FIELDS or packet['schema'] != SCHEMA
            or not session_ok(packet['session']) or type(packet['frame']) is not int or packet['frame'] < 1
            or not finite(packet['source_time_sec']) or not finite(packet['evaluated_time_sec'])
            or packet['clock_basis'] != 'recorded_receiver_monotonic_NOT_ROS_or_wall_time'
            or type(packet['max_age_sec']) is not float or packet['max_age_sec'] != MAX_AGE_SEC
            or packet['metric'] != 'horizontal_camera_foot_range_m_NOT_base_link_or_contact'
            or any(packet[k] is not False for k in FALSE_FLAGS) or packet['replay_only'] is not True
            or packet['vehicle_xy_m'] is not None or packet['object_id'] is not None
            or type(packet['input_verified']) is not bool or type(packet['range_available']) is not bool
            or not isinstance(packet['reason'], str) or not 0 < len(packet['reason']) <= 300):
        raise ValueError('bounded offline non-controlling range sample required')
    if packet['review_completed_time_sec'] is not None and not finite(packet['review_completed_time_sec']):
        raise ValueError('finite review time required')
    if packet['primary_model'] is not None and (not isinstance(packet['primary_model'], str) or len(packet['primary_model']) > 100):
        raise ValueError('bounded primary model required')
    if packet['input_verified'] and (packet['review_completed_time_sec'] is None
            or not packet['source_time_sec'] <= packet['review_completed_time_sec'] <= packet['evaluated_time_sec']
            or packet['evaluated_time_sec']-packet['source_time_sec'] > MAX_AGE_SEC):
        raise ValueError('verified sample must have causal fresh times')
    generation, frame, digest = (packet['reference_generation'], packet['reference_frame'], packet['reference_png_sha256'])
    bound = (type(generation) is int and generation > 0 and type(frame) is int and 0 < frame < packet['frame']
             and isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) is not None)
    if any(v is not None for v in (generation, frame, digest)) and not bound:
        raise ValueError('complete bounded reference identity required')
    if packet['range_available']:
        if (not packet['input_verified'] or not bound or not finite(packet['distance_m'])
                or not 0 < packet['distance_m'] <= 100):
            raise ValueError('numeric sample needs verified source/reference')
    elif packet['distance_m'] is not None:
        raise ValueError('withheld sample must have null distance')
    return dict(packet)


class OfflineRangeReceiver:
    """Explicit single-session consumer; invalid, withheld and stale clear value."""
    def __init__(self, session, *, reference_frame, reference_png_sha256, reference_generation=1):
        if (not session_ok(session) or type(reference_frame) is not int or reference_frame < 1
                or type(reference_generation) is not int or reference_generation < 1
                or not isinstance(reference_png_sha256, str)
                or re.fullmatch('[0-9a-f]{64}', reference_png_sha256) is None):
            raise ValueError('explicit replay session and reviewed reference identity required')
        self.session, self.last_frame, self.last_source = session, 0, None
        self.reference = (reference_generation, reference_frame, reference_png_sha256)
        self.current, self.reason = None, 'handoff_waiting_for_sample'

    def receive(self, packet, *, now_source_clock_sec):
        self.current = None
        self.reason = 'handoff_invalid_packet'
        if not finite(now_source_clock_sec):
            self.reason = 'handoff_invalid_clock'
            raise ValueError('finite nonnegative source-clock time required')
        try:
            value = checked_sample(packet)
        except (ValueError, TypeError, KeyError):
            return self.snapshot(now_source_clock_sec=now_source_clock_sec)
        if value['session'] != self.session:
            self.reason = 'handoff_session_mismatch'
        elif value['reference_generation'] is not None and (
                value['reference_generation'], value['reference_frame'], value['reference_png_sha256']) != self.reference:
            self.reason = 'handoff_reference_mismatch'
        elif value['frame'] <= self.last_frame or (self.last_source is not None and value['source_time_sec'] <= self.last_source):
            self.reason = 'handoff_duplicate_or_out_of_order'
        elif now_source_clock_sec < value['evaluated_time_sec']:
            self.reason = 'handoff_source_or_review_in_future'
        else:
            self.last_frame, self.last_source = value['frame'], value['source_time_sec']
            self.current, self.reason = value, value['reason']
        return self.snapshot(now_source_clock_sec=now_source_clock_sec)

    def snapshot(self, *, now_source_clock_sec):
        if not finite(now_source_clock_sec):
            self.current = None
            self.reason = 'handoff_invalid_clock'
            raise ValueError('finite nonnegative source-clock time required')
        value = self.current
        reason = self.reason
        available = False
        if value is not None:
            if now_source_clock_sec < value['evaluated_time_sec']:
                reason = 'handoff_source_or_review_in_future'
                self.current = None
            elif now_source_clock_sec-value['source_time_sec'] > MAX_AGE_SEC:
                reason = 'handoff_sample_stale'
                self.current = None
            else:
                available = value['input_verified'] and value['range_available']
        self.reason = reason
        current = self.current
        return dict(range_available=available, distance_m=value['distance_m'] if available else None,
            reason=reason, session=self.session, replay_only=True,
            frame=current['frame'] if current is not None else None,
            source_time_sec=current['source_time_sec'] if current is not None else None,
            age_sec=now_source_clock_sec-current['source_time_sec'] if current is not None else None,
            clock_basis='recorded_receiver_monotonic_NOT_ROS_or_wall_time',
            reference_generation=current['reference_generation'] if current is not None else None,
            reference_frame=current['reference_frame'] if current is not None else None,
            reference_png_sha256=current['reference_png_sha256'] if current is not None else None,
            metric='horizontal_camera_foot_range_m_NOT_base_link_or_contact',
            vehicle_xy_m=None, object_id=None, **{k: False for k in FALSE_FLAGS})
