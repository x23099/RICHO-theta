"""OFFLINE fact transfer only. No clock inference or measurement certification."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_odometry_observation import checked_observation
from driver_motion_time_join import motion_record

spec = importlib.util.spec_from_file_location('handoff_envelope_validator', ROOT/
    'Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/review.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def transfer(row, *, session, receiver_clock_id):
    """Preserve observations, not a claim that they qualify for a risk model."""
    base.require(type(row) is dict and row.get('event_kind') == 'telemetry', 'telemetry record required')
    base.require(row.get('session') == session and row.get('receiver_clock_id') == receiver_clock_id,
                 'explicit received session and clock scope required')
    common = dict(row)
    observation, reasons = None, []
    if row.get('schema') == 'driver_received_telemetry_v2':
        state = common.pop('odometry_metadata_state', None)
        raw = common.pop('odometry_observation', None)
        common['schema'] = 'driver_received_telemetry_v1'
        if state == 'versioned_odometry_observation':
            observation = checked_observation(raw)
        else:
            base.require(state in ('invalid_odometry_metadata', 'unsupported_odometry_schema') and raw is None,
                         'explicit rejected metadata state required')
            reasons.append(state)
    else:
        base.require(row.get('schema') == 'driver_received_telemetry_v1', 'known received schema required')
        reasons.append('legacy_telemetry_not_a_measured_motion_sample')
    base.checked_row(common, receiver_clock_id)
    facts = {}
    if observation is not None:
        if observation['callback_received'] is True:
            facts.update(source_kind='measured_odometry',
                source_stamp_ns=observation['header_stamp_ns'], motion_frame_id=observation['motion_frame_id'],
                linear_mps=observation['linear_mps'], angular_radps=observation['angular_radps'])
            if not observation['sample_fields_valid']:
                reasons.append('observed_sample_fields_invalid')
            if observation['stamp_status'] in ('repeated', 'reversed', 'missing'):
                reasons.append('original_stamp_'+observation['stamp_status'])
            reasons.extend(('measurement_validity_unverified', 'original_clock_identity_unknown',
                            'clock_mapping_missing'))
        else:
            reasons.append('odometry_not_received' if observation['callback_received'] is False
                           else 'odometry_callback_state_unknown')
    record = motion_record(session=session, receiver_clock_id=receiver_clock_id,
        sequence=row['sequence'], received_at_sec=row['received_at_sec'], logged_at_sec=row['logged_at_sec'],
        source_clock_id=None, measurement_valid=None, **facts)
    return dict(schema='offline_received_odometry_handoff_v1', motion_record=record,
        observation=observation, hold_reasons=reasons, pairing_eligible=False,
        measurement_validity_independently_verified=False, clock_mapping_verified=False,
        replay_only=True, usable_for_ffb=False, published_to_ros=False)
