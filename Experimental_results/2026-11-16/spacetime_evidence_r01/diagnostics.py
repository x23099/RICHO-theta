"""Conditional arithmetic only; no real transform or clock is certified."""
import math
import numpy as np


def real(value):
    return type(value) in (int, float) and abs(value) < 1e12 and math.isfinite(value)


def one_way_examples(sender, receiver, *, alternative_shift_sec):
    if (not sender or len(sender) != len(receiver) or not real(alternative_shift_sec)
            or alternative_shift_sec <= 0 or any(not real(t) or t < 0 for t in [*sender, *receiver])
            or any(a > b for values in (sender, receiver) for a, b in zip(values, values[1:]))):
        raise ValueError('bounded ordered clock observations and positive example shift required')
    differences = [r-s for s, r in zip(sender, receiver)]
    offset = min(differences)
    examples = []
    for candidate in (offset, offset-alternative_shift_sec):
        residuals = [d-candidate for d in differences]
        examples.append(dict(assumed_receiver_minus_sender_offset_sec=candidate,
            conditional_delay_min_sec=min(residuals), conditional_delay_max_sec=max(residuals)))
    return dict(conditional_unit_relative_rate_only=True, examples=examples,
        observed_difference_span_sec=max(differences)-min(differences),
        true_offset_identified=False, upper_latency_bound_identified=False,
        clock_alignment_verified=False, usable_for_ffb=False)


def four_stamp_interval(receiver_send, sender_receive, sender_send, receiver_receive):
    values = (receiver_send, sender_receive, sender_send, receiver_receive)
    if (any(not real(t) or t < 0 for t in values)
            or sender_send < sender_receive or receiver_receive < receiver_send):
        raise ValueError('finite locally ordered exchange timestamps required')
    low, high = receiver_send-sender_receive, receiver_receive-sender_send
    if low > high:
        raise ValueError('exchange incompatible with constant offset and nonnegative delays')
    return dict(receiver_minus_sender_offset_lower_sec=low,
        receiver_minus_sender_offset_upper_sec=high, interval_width_sec=high-low,
        midpoint_sec=low+(high-low)/2, conditional_half_width_sec=(high-low)/2,
        conditional_constant_relative_rate_only=True, path_symmetry_assumed=False,
        clock_alignment_verified=False, usable_for_ffb=False)


def array(value, shape):
    original = np.asarray(value, dtype=object)
    if (original.shape != shape or any(isinstance(x, (bool, np.bool_)) for x in original.flat)):
        raise ValueError('explicit nonboolean real array required')
    raw = np.asarray(value)
    if raw.dtype.kind not in 'iuf' or not np.isfinite(raw).all() or (np.abs(raw) > 1e6).any():
        raise ValueError('bounded finite real array required')
    return raw.astype(float)


def conditional_body_geometry(q, up, height, rotation, translation):
    q, up = array(q, (3,)), array(up, (3,))
    rotation, translation = array(rotation, (3, 3)), array(translation, (3,))
    if (not real(height) or not 0 < height < 3
            or not np.isclose(np.linalg.norm(up), 1., atol=1e-10, rtol=0)
            or not np.isclose(q @ up, 0., atol=1e-10, rtol=0)
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-10, rtol=0)
            or not np.isclose(np.linalg.det(rotation), 1., atol=1e-10, rtol=0)
            or not np.allclose(rotation @ up, [0., 0., 1.], atol=1e-10, rtol=0)):
        raise ValueError('unit floor up, in-plane offset and proper floor-aligned rotation required')
    plumb_foot = translation-height*(rotation @ up)
    support = rotation @ (q-height*up)+translation
    return dict(conditional_support_body_m=support.tolist(),
        conditional_camera_plumb_foot_body_m=plumb_foot.tolist(),
        body_displacement_from_plumb_foot_m=(rotation @ q).tolist(),
        vehicle_xy_m=None, real_mount_transform_verified=False,
        floor_contact_verified=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False)
