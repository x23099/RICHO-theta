"""Pair the two transport-probe summaries and compute frame-level outcomes.

Transport only: this never claims fps, one-way delay, distance accuracy, ROS or
FFB suitability. It refuses mismatched scopes instead of guessing.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'frame_packet_transport_probe_v1'
ROLES = ('sender', 'receiver')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    value = json.loads(Path(path).read_bytes())
    require(value.get('schema') == SCHEMA, 'probe schema differs')
    require(value.get('role') in ROLES, 'probe role differs')
    for key in ('inference_started', 'ros_published', 'usable_for_ffb'):
        require(value.get(key) is False, 'probe claims authority: ' + key)
    profile = value.get('profile')
    require(type(profile) is dict, 'probe profile required')
    for key in ('sender_id', 'stream_id', 'rate_hz'):
        require(key in profile, 'probe profile field missing: ' + key)
    require(type(value.get('counters')) is dict, 'probe counters required')
    return value


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'nonnegative finite counter required')
    return value


def paired(sender, receiver):
    require(sender['role'] == 'sender' and receiver['role'] == 'receiver', 'probe roles reversed')
    for key in ('sender_id', 'stream_id', 'rate_hz'):
        require(sender['profile'][key] == receiver['profile'][key], 'probe scopes differ: ' + key)
    both_closed = bool(sender['closed']) and bool(receiver['closed'])
    sent = sender.get('channel') or {}
    received = receiver.get('channel') or {}
    require(sent.get('activated') is True, 'sender packet channel was not activated')
    require(received.get('configured') is True, 'receiver packet channel was not configured')
    scheduler = sent.get('scheduler') or {}
    assembler = received.get('assembler') or {}
    counters = receiver['counters']
    handed_off = number(scheduler.get('packets_handed_off', 0))
    chunks = number(scheduler.get('chunks_handed_off', 0))
    completed = number(assembler.get('completed', 0))
    delivered = number(assembler.get('delivered', 0))
    published = number(counters.get('frames_published', 0))
    messages = number(sent.get('messages_sent', 0))
    require(handed_off > 0 and chunks > 0, 'sender handed off no frames')
    require(messages <= chunks or chunks == 0, 'fragment messages exceed generated fragments')
    sender_elapsed = number(sender.get('elapsed_sec', 0))
    first, last = counters.get('first_published_at_sec'), counters.get('last_published_at_sec')
    span = number(last - first) if type(first) in (int, float) and type(last) in (int, float) else 0
    cap = sender['profile'].get('message_cap')
    return dict(
        schema='frame_packet_transport_pair_v1',
        state='transport_pair_verified_NOT_fps_or_ffb',
        rate_hz=sender['profile']['rate_hz'],
        both_closed=both_closed,
        sender_elapsed_sec=number(sender.get('elapsed_sec', 0)),
        receiver_elapsed_sec=number(receiver.get('elapsed_sec', 0)),
        frames_offered=number(scheduler.get('offered', 0)),
        frames_expired_before_send=number(scheduler.get('expired', 0)),
        frames_replaced_before_send=number(scheduler.get('pending_replaced', 0)),
        frames_handed_off=handed_off,
        fragments_generated=chunks,
        fragments_sent=messages,
        fragments_per_frame=(chunks / handed_off),
        message_cap_bytes=cap,
        payload_bytes_upper_bound=(chunks * cap if type(cap) is int else None),
        sender_effective_hz=(handed_off / sender_elapsed if sender_elapsed else None),
        receiver_observed_span_sec=span,
        receiver_published_hz=(published / span if span else None),
        receiver_frames_completed=completed,
        receiver_frames_delivered=delivered,
        receiver_frames_published=published,
        receiver_packets_replaced_before_completion=number(assembler.get('replaced', 0)),
        receiver_frames_expired=number(assembler.get('expired', 0)),
        receiver_duplicates=number(assembler.get('duplicates', 0)),
        receiver_invalid=number(assembler.get('invalid', 0)),
        receiver_conflicts=number(assembler.get('conflicts', 0)),
        receiver_capture_sequence_jumps=number(counters.get('sequence_gaps', 0)),
        receiver_capture_sequence_jumps_are_not_packet_loss=True,
        receiver_out_of_order=number(counters.get('out_of_order', 0)),
        frame_completion_ratio=(completed / handed_off),
        frame_publication_ratio=(published / handed_off),
        delivery_latency_min_sec=counters.get('delivery_latency_min_sec'),
        delivery_latency_max_sec=counters.get('delivery_latency_max_sec'),
        delivery_latency_mean_sec=counters.get('delivery_latency_mean_sec'),
        sender_error=sender.get('error') or sent.get('channel_error') or sent.get('binding_error'),
        receiver_error=receiver.get('error') or received.get('worker_error') or received.get('binding_error'),
        sender_bytes_not_measured=True,
        video_fps_measured=False,
        one_way_delay_measured=False,
        source_freshness_verified=False,
        physical_metric_verified=False,
        usable_for_ffb=False,
        published_to_ros=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sender', type=Path, required=True)
    parser.add_argument('--receiver', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    require(not output.exists(), 'unused output directory required')
    sender, receiver = load(args.sender), load(args.receiver)
    result = paired(sender, receiver)
    result['sources'] = {role: dict(file=Path(path).name,
                                    sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())
                         for role, path in (('sender', args.sender), ('receiver', args.receiver))}
    result['analysis_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'audit.json').open('x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({key: result[key] for key in ('state', 'frames_handed_off', 'receiver_frames_completed',
                                                   'receiver_frames_published', 'frame_completion_ratio')}, indent=2))


if __name__ == '__main__':
    main()
