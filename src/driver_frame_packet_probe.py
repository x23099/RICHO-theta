"""Opt-in transport-only probe for the independent PNG frame/motion channel.

Records what the *real* SCTP channel and the existing fragment/deadline path
delivered. It never runs inference, never publishes ROS and never touches FFB
or the existing video/control channels. OFF unless an explicit directory is
given on both ends.

The probe only counts; it does not alter reassembly, deadlines, pacing or
dropping. Counters that already exist in the channel adapters are read through
a provider so this module holds no copy of production state.
"""
import json
import os
from pathlib import Path
import threading
import time

SCHEMA = 'frame_packet_transport_probe_v1'


def probe_directory(value):
    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError('existing probe output directory required')
    return path


def _snapshot(value, depth=0):
    """Copy JSON-safe counters without ever blocking the transport thread."""
    if depth > 4:
        raise ValueError('bounded probe state required')
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError('finite probe values required')
        return value
    if type(value) in (list, tuple):
        return [_snapshot(item, depth + 1) for item in value]
    if type(value) is dict:
        return {str(key): _snapshot(item, depth + 1) for key, item in list(value.items())}
    raise ValueError('unexpected probe state type')


class ProbeRecorder:
    """Periodic atomic summary so an abrupt end still leaves readable counters."""

    def __init__(self, directory, role, profile, *, interval_sec=2., clock=time.monotonic):
        self.directory = probe_directory(directory)
        if role not in ('sender', 'receiver'):
            raise ValueError('explicit probe role required')
        if profile is not None and type(profile) is not dict:
            raise ValueError('explicit packet profile required')
        if type(interval_sec) not in (int, float) or not 0.1 <= interval_sec <= 10:
            raise ValueError('bounded probe flush interval required')
        self.role, self.clock, self.interval = role, clock, interval_sec
        self.path = self.directory / (role + '_probe.json')
        self.lock = threading.Lock()
        self.flush_lock = threading.Lock()
        self.stop = threading.Event()
        self.provider = None
        self.extra = {}
        self.started = clock()
        self.profile = dict(profile) if profile is not None else None
        self.error = None
        self.closed = False
        self.thread = threading.Thread(target=self._run, name='frame-packet-probe', daemon=True)
        self.flush()
        self.thread.start()

    def set_profile(self, profile):
        if type(profile) is not dict:
            raise ValueError('explicit packet profile required')
        with self.lock:
            self.profile = dict(profile)

    def set_provider(self, provider):
        if not callable(provider):
            raise ValueError('callable probe provider required')
        with self.lock:
            self.provider = provider

    def update(self, **values):
        with self.lock:
            self.extra.update(values)

    def _collect(self):
        with self.lock:
            provider, extra, error, closed = self.provider, dict(self.extra), self.error, self.closed
            profile = dict(self.profile) if self.profile is not None else None
        state = None
        if provider is not None:
            try:
                state = _snapshot(provider())
            except Exception as failure:
                state = dict(state_error=type(failure).__name__ + ': ' + str(failure)[:160])
        return dict(schema=SCHEMA, role=self.role, profile=profile,
                    elapsed_sec=round(self.clock() - self.started, 6), closed=closed, error=error,
                    counters=_snapshot(extra), channel=state,
                    inference_started=False, ros_published=False, usable_for_ffb=False)

    def flush(self):
        value = self._collect()
        temporary = self.path.with_suffix('.json.tmp')
        with self.flush_lock:
            with temporary.open('w') as target:
                json.dump(value, target, indent=2, allow_nan=False)
                target.write('\n')
            os.replace(temporary, self.path)

    def _run(self):
        while not self.stop.wait(self.interval):
            try:
                self.flush()
            except Exception as failure:
                with self.lock:
                    self.error = self.error or type(failure).__name__ + ': ' + str(failure)[:160]

    def close(self, error=None):
        with self.lock:
            self.error = self.error or error
            self.closed = True
        self.stop.set()
        if self.thread is not threading.current_thread():
            self.thread.join(1.)
        try:
            self.flush()
        except Exception as failure:
            self.error = self.error or type(failure).__name__ + ': ' + str(failure)[:160]
        return self.error is None


class ProbePacketSink:
    """Receiver-side bridge substitute: count decoded packets, keep nothing."""

    packet_input = True

    def __init__(self, recorder, *, clock=time.monotonic):
        if not isinstance(recorder, ProbeRecorder) or recorder.role != 'receiver':
            raise ValueError('receiver recorder required')
        self.recorder, self.clock = recorder, clock
        self.stop_event = threading.Event()
        self.profile = None
        self.lock = threading.Lock()
        self.frames = self.bytes = self.gaps = self.out_of_order = 0
        self.sequence = None
        self.first = self.last = None
        self.latency_min = self.latency_max = None
        self.latency_sum = 0.
        self.error = None
        self.reason = 'not_configured'
        self._publish()

    def begin_packet(self, profile):
        self.profile = dict(profile)
        self.reason = 'configured'
        self._publish()

    def publish_packet(self, packet):
        try:
            now = self.clock()
            sequence = packet.candidate['capture_sequence']
            with self.lock:
                if self.sequence is not None:
                    if sequence <= self.sequence:
                        self.out_of_order += 1
                    elif sequence > self.sequence + 1:
                        self.gaps += sequence - self.sequence - 1
                self.sequence = sequence
                self.frames += 1
                self.bytes += int(packet.image.nbytes)
                self.first = now if self.first is None else self.first
                self.last = now
                latency = max(0., now - packet.received_at_sec)
                self.latency_sum += latency
                self.latency_min = latency if self.latency_min is None else min(self.latency_min, latency)
                self.latency_max = latency if self.latency_max is None else max(self.latency_max, latency)
        except Exception as failure:
            self.error = self.error or type(failure).__name__ + ': ' + str(failure)[:160]
        self._publish()
        return True

    def end(self, session, reason='packet_connection_ended'):
        self.reason = str(reason)[:160]
        self._publish()

    def _publish(self):
        with self.lock:
            frames, total, gaps, out_of_order = self.frames, self.bytes, self.gaps, self.out_of_order
            first, last, low, high, count = self.first, self.last, self.latency_min, self.latency_max, self.frames
            reason, error = self.reason, self.error
        self.recorder.update(frames_published=frames, image_bytes=total, sequence_gaps=gaps,
                             out_of_order=out_of_order, reason=reason, sink_error=error,
                             first_published_at_sec=first, last_published_at_sec=last,
                             delivery_latency_min_sec=low, delivery_latency_max_sec=high,
                             delivery_latency_mean_sec=(self.latency_sum / count) if count else None)

    def reset_stop(self):
        self.stop_event.clear()


def sender_state(binding):
    """Read-only copy of the sender scheduler/encoder counters."""
    tx = binding.tx
    if tx is None:
        return dict(activated=False, activation_error=binding.error, source_error=binding.source.error)
    return dict(activated=True, messages_sent=tx.messages_sent,
                scheduler=dict(tx.scheduler.counts), peak_retained_bytes=tx.scheduler.peak_retained_bytes,
                encoder_replaced=tx.worker.replaced, encoder_peak_queued=tx.worker.peak_queued,
                channel_error=tx.error, binding_error=binding.error, source_error=binding.source.error)


def receiver_state(binding):
    """Read-only copy of the receiver assembler/inbox counters."""
    rx = binding.rx
    if rx is None:
        return dict(configured=False, binding_error=binding.error)
    return dict(configured=True, assembler=dict(rx.assembler.counts),
                inbox_replaced=rx.replaced, inbox_peak_queued=rx.peak_queued,
                assembler_peak_retained_bytes=rx.assembler.peak_retained_bytes,
                worker_error=rx.error, binding_error=binding.error)
