"""Fake explicitly scoped channel + real codec workers; no network or devices."""
import copy
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import driver_frame_packet_channel as channel_module
from driver_frame_packet_channel import (PROTOCOL, negotiated_message_bytes,
    FramePacketChannelSender, FramePacketReceiveWorker)
from driver_frame_packet_flow import fragment_plan
from driver_frame_packet import encode_packet, FramePacketReceiver
from driver_frame_motion import FLAGS
from test_driver_frame_packet import candidate, image, SENDER, STREAM


def sdp(size='16384', *, mid='data', port='9', proto='UDP/DTLS/SCTP'):
    value = ('v=0\r\nm=application '+port+' '+proto+' webrtc-datachannel\r\n'
             'a=mid:'+mid+'\r\na=sctp-port:5000\r\n')
    return value if size is None else value+'a=max-message-size:'+size+'\r\n'


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeChannel:
    label = protocol = PROTOCOL
    ordered, maxRetransmits, maxPacketLifeTime = False, 0, None

    def __init__(self, receiver=None):
        self.receiver = receiver
        self.readyState, self.bufferedAmount = 'open', 0
        self.sent, self.thread_ids = [], []
        self.fail = False
        self.closed_count = 0

    def send(self, message):
        self.thread_ids.append(threading.get_ident())
        if self.fail:
            raise RuntimeError('injected send failure')
        self.sent.append(message)
        self.bufferedAmount += len(message)
        if self.receiver is not None:
            self.receiver.offer_message(message)

    def close(self):
        self.closed_count += 1
        self.readyState = 'closed'


def await_condition(predicate, timeout=2.):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('worker did not reach expected state')
        time.sleep(.002)


def output_ready(worker):
    with worker.lock:
        return worker.output is not None


class NegotiationTests(unittest.TestCase):
    def limit(self, value, **kwargs):
        return negotiated_message_bytes(value, mid='data', local_max_message_size=65536, **kwargs)

    def test_default_zero_and_directional_small_caps(self):
        for size in (None, '0', '65536', '999999999'):
            self.assertEqual(self.limit(sdp(size)), 16384)
        self.assertEqual(self.limit(sdp('2048')), 2048)
        self.assertEqual(negotiated_message_bytes(sdp('0'), mid='data', local_max_message_size=4096), 4096)
        self.assertEqual(negotiated_message_bytes(sdp('0'), mid='data', local_max_message_size=0), 16384)
        self.assertEqual(self.limit(sdp(), app_cap=1024), 1024)

    def test_canonical_integer_and_too_small_peer(self):
        for size in ('', '-1', '+2048', '016384', '1.5', '1e4', '1023', '9'*20):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.limit(sdp(size))

    def test_duplicate_unknown_or_rejected_application(self):
        for value in (sdp()+'a=max-message-size:2048\r\n', sdp(mid='elsewhere'),
                      sdp(port='0'), sdp(proto='DTLS/SCTP'), sdp()+'a=mid:data\r\n',
                      sdp()+sdp(), sdp().replace('a=sctp-port:5000\r\n', ''),
                      'a=max-message-size:2048\r\n'+sdp(), sdp()+'a=foo:\x00\r\n',
                      sdp()+'a=inactive\r\n', sdp().replace('\r\n', '\u2028')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.limit(value)

    def test_selects_explicit_mid_not_first_media_section(self):
        remote = 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=mid:audio\r\n'+sdp('4096')
        self.assertEqual(self.limit(remote), 4096)

    def test_bad_local_or_unbounded_description(self):
        for value in (True, -1, 100., 2**63):
            with self.assertRaises(ValueError):
                negotiated_message_bytes(sdp(), mid='data', local_max_message_size=value)
        for remote in ('', 'x'*65537, None):
            with self.assertRaises(ValueError):
                self.limit(remote)

    def test_installed_aiortc_public_capability_and_sdp_without_peer_start(self):
        from aiortc import RTCSctpTransport
        from aiortc.sdp import SessionDescription
        local = RTCSctpTransport.getCapabilities().maxMessageSize
        remote = SessionDescription.parse(sdp('4096')).media[0].sctpCapabilities.maxMessageSize
        self.assertEqual(remote, 4096)
        self.assertEqual(negotiated_message_bytes(sdp('4096'), mid='data',
            local_max_message_size=local), min(16384, remote, local or 16384))


class WorkerChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wire = encode_packet(image(), candidate())
        cls.plan = fragment_plan(cls.wire, message_bytes=16384)

    def setUp(self):
        self.workers = []

    def tearDown(self):
        for obj in self.workers:
            self.assertTrue(obj.close(timeout_sec=1.))

    def receiver(self, **kwargs):
        opts = dict(sender_id=SENDER, stream_id=STREAM, message_bytes=16384,
                    timeout_sec=.2, clock=Clock(500.))
        opts.update(kwargs)
        obj = FramePacketReceiveWorker(**opts)
        self.workers.append(obj)
        return obj

    def sender(self, channel=None, **kwargs):
        opts = dict(sender_id=SENDER, stream_id=STREAM, message_bytes=16384,
                    max_capture_age_sec=.2, max_buffered_bytes=32768, clock=Clock(10.05))
        opts.update(kwargs)
        obj = FramePacketChannelSender(channel or FakeChannel(), **opts)
        self.workers.append(obj)
        return obj

    def deliver(self, rec, plan=None):
        plan = plan or self.plan
        for i in range(plan.count):
            self.assertTrue(rec.offer_message(plan.fragment(i)))

    def test_real_worker_to_fake_channel_to_real_decode_with_unrelated_clocks(self):
        rec = self.receiver(clock=Clock(700000.))
        channel = FakeChannel(rec)
        tx = self.sender(channel)
        producer, encoders, decoders = threading.get_ident(), [], []
        original_encode, original_decode = channel_module.encode_packet, FramePacketReceiver.accept
        def encode(*args):
            encoders.append(threading.get_ident())
            return original_encode(*args)
        def decode(*args, **kwargs):
            decoders.append(threading.get_ident())
            return original_decode(*args, **kwargs)
        with patch.object(channel_module, 'encode_packet', encode), patch.object(FramePacketReceiver, 'accept', decode):
            self.assertTrue(tx.submit(image(130), candidate(v=-.2, w=.1)))
            await_condition(lambda: output_ready(tx.worker))
            while tx.worker.output is not None or tx.scheduler.active is not None or tx.scheduler.pending is not None:
                tx.pump(budget=2)
                channel.bufferedAmount = 0  # Fake drain, NOT measured SCTP throughput.
            await_condition(lambda: output_ready(rec))
        result = rec.take()
        self.assertEqual(result.candidate['capture_sequence'], 1)
        self.assertEqual(result.candidate['odometry_observation']['linear_mps'], -.2)
        self.assertGreater(result.image.mean(), 120.)
        self.assertTrue(all(result.candidate[f] is False for f in FLAGS))
        self.assertEqual(result.received_at_sec, 700000.)
        self.assertIsNone(rec.take())
        self.assertEqual(encoders, [tx.worker.thread.ident])
        self.assertEqual(decoders, [rec.thread.ident])
        self.assertNotEqual(encoders[0], producer)
        self.assertNotEqual(decoders[0], producer)
        self.assertTrue(all(t == producer for t in channel.thread_ids))
        self.assertTrue(all(len(msg) <= 16384 for msg in channel.sent))

    def test_receiver_keeps_initial_deadline_at_consumption(self):
        clock = Clock(500.)
        rec = self.receiver(clock=clock)
        self.deliver(rec)
        await_condition(lambda: output_ready(rec))
        clock.now = 500.201
        self.assertIsNone(rec.take())

    def test_receiver_queue_time_does_not_invent_clock_reversal(self):
        clock, gate, entered = Clock(500.), threading.Event(), threading.Event()
        rec = self.receiver(clock=clock)
        original = rec._process
        def blocked(item):
            entered.set()
            gate.wait(2.)
            return original(item)
        with patch.object(rec, '_process', blocked):
            self.assertTrue(rec.offer_message(self.plan.fragment(0)))
            self.assertTrue(entered.wait(1.))
            clock.now = 500.01
            for i in range(1, self.plan.count):
                self.assertTrue(rec.offer_message(self.plan.fragment(i)))
            clock.now = 500.05  # Current processing time ahead of all queued arrival times.
            gate.set()
            await_condition(lambda: output_ready(rec))
        self.assertIsNotNone(rec.take())
        self.assertFalse(rec.retired.is_set())

    def test_decode_completing_after_deadline_is_discarded(self):
        clock = Clock(500.)
        rec = self.receiver(clock=clock)
        original = FramePacketReceiver.accept
        def delayed(*args, **kwargs):
            result = original(*args, **kwargs)
            clock.now = 500.201
            return result
        with patch.object(FramePacketReceiver, 'accept', delayed):
            self.deliver(rec)
            await_condition(lambda: rec.decoder.high_sequence == 1)
            await_condition(lambda: not rec.queue)
        self.assertIsNone(rec.take())

    def test_blocked_decode_finite_close_and_late_result_cannot_revive(self):
        gate, entered = threading.Event(), threading.Event()
        rec = self.receiver()
        original = FramePacketReceiver.accept
        def blocked(*args, **kwargs):
            entered.set()
            gate.wait(2.)
            return original(*args, **kwargs)
        with patch.object(FramePacketReceiver, 'accept', blocked):
            self.deliver(rec)
            self.assertTrue(entered.wait(1.))
            start = time.monotonic()
            self.assertFalse(rec.close(timeout_sec=.01))
            self.assertLess(time.monotonic()-start, .5)
            self.assertIsNone(rec.take())
            self.assertFalse(rec.offer_message(self.plan.fragment(0)))
            gate.set()
            self.assertTrue(rec.done.wait(1.))
        self.assertIsNone(rec.take())

    def test_inbox_overflow_retires_without_resurrecting_old_output(self):
        gate, entered = threading.Event(), threading.Event()
        rec = self.receiver(inbox_capacity=1)
        original = rec._process
        def blocked(item):
            entered.set()
            gate.wait(2.)
            return original(item)
        with patch.object(rec, '_process', blocked):
            rec.offer_message(self.plan.fragment(0))
            self.assertTrue(entered.wait(1.))
            self.assertTrue(rec.offer_message(self.plan.fragment(0)))
            self.assertFalse(rec.offer_message(self.plan.fragment(0)))
            self.assertEqual(rec.error, 'inbox_overflow')
            self.assertIsNone(rec.take())
            self.assertLessEqual(rec.peak_queued, 1)
            gate.set()
            self.assertTrue(rec.done.wait(1.))

    def test_callback_lock_contention_does_not_wait(self):
        rec = self.receiver()
        with rec.lock:
            self.assertFalse(rec.offer_message(self.plan.fragment(0)))
            self.assertEqual(rec.error, 'inbox_busy')
        self.assertTrue(rec.done.wait(1.))

    def test_invalid_ingress_and_reversed_clock_retire(self):
        for bad in ('text', bytes(16385), b''):
            rec = self.receiver()
            self.assertFalse(rec.offer_message(bad))
            self.assertIsNone(rec.take())
        clock = Clock(500.)
        rec = self.receiver(clock=clock)
        rec.offer_message(self.plan.fragment(0))
        clock.now = 499.
        self.assertFalse(rec.offer_message(self.plan.fragment(0)))

    def test_withheld_motion_stays_withheld(self):
        rec = self.receiver()
        plan = fragment_plan(encode_packet(image(), candidate(withheld=True)), message_bytes=16384)
        self.deliver(rec, plan)
        await_condition(lambda: output_ready(rec))
        value = rec.take()
        self.assertFalse(value.candidate['local_pair_available'])
        self.assertIsNone(value.candidate['odometry_observation'])

    def test_failed_channel_send_only_closes_supplied_channel(self):
        channel, unrelated_control = FakeChannel(), FakeChannel()
        channel.fail = True
        tx = self.sender(channel)
        tx.submit(image(), candidate())
        await_condition(lambda: output_ready(tx.worker))
        self.assertEqual(tx.pump(), 0)
        self.assertTrue(tx.closed)
        self.assertIn('injected send failure', tx.error)
        self.assertEqual(tx.messages_sent, 0)
        self.assertEqual(tx.scheduler.retained_bytes, 0)
        self.assertEqual(unrelated_control.readyState, 'open')
        self.assertEqual(unrelated_control.sent, [])
        self.assertFalse(tx.submit(image(), candidate(sequence=2)))

    def test_sender_backpressure_then_capture_expiration(self):
        clock, channel = Clock(10.05), FakeChannel()
        tx = self.sender(channel, clock=clock)
        channel.bufferedAmount = 32768
        tx.submit(image(), candidate())
        await_condition(lambda: output_ready(tx.worker))
        self.assertEqual(tx.pump(), 0)
        clock.now = 10.251
        channel.bufferedAmount = 0
        self.assertEqual(tx.pump(), 0)
        self.assertEqual(tx.scheduler.counts['expired'], 1)

    def test_sender_owner_thread_enforced(self):
        tx, errors = self.sender(), []
        def wrong_owner():
            try:
                tx.pump()
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=wrong_owner)
        thread.start(); thread.join(1.)
        self.assertEqual(len(errors), 1)
        self.assertEqual(tx.channel.sent, [])

    def test_sender_closed_channel_bad_buffer_or_clock_retire(self):
        for state, buffer, now in (('closed', 0, 10.05), ('open', True, 10.05), ('open', 0, float('nan'))):
            tx = self.sender(clock=Clock(now))
            tx.channel.readyState, tx.channel.bufferedAmount = state, buffer
            tx.pump()
            self.assertTrue(tx.closed)

    def test_latest_encoder_pending_only_and_shutdown_during_encode(self):
        gate, entered = threading.Event(), threading.Event()
        tx = self.sender()
        original = channel_module.encode_packet
        def blocked(*args):
            entered.set()
            gate.wait(2.)
            return original(*args)
        with patch.object(channel_module, 'encode_packet', blocked):
            tx.submit(image(), candidate())
            self.assertTrue(entered.wait(1.))
            tx.submit(image(), candidate(sequence=2))
            tx.submit(image(), candidate(sequence=3))
            self.assertEqual(tx.worker.replaced, 1)
            self.assertEqual(tx.worker.peak_queued, 1)
            self.assertFalse(tx.close(timeout_sec=.01))
            self.assertEqual(len(tx.worker.queue), 0)
            gate.set()
            self.assertTrue(tx.worker.done.wait(1.))
        self.assertEqual(tx.pump(), 0)
        self.assertEqual(tx.channel.sent, [])

    def test_encode_exception_retires_packet_adapter(self):
        tx = self.sender()
        with patch.object(channel_module, 'encode_packet', side_effect=ValueError('injected encode failure')):
            tx.submit(image(), candidate())
            self.assertTrue(tx.worker.done.wait(1.))
        tx.pump()
        self.assertTrue(tx.closed)
        self.assertIn('injected encode failure', tx.error)

    def test_new_connection_rejects_old_stream(self):
        rec = self.receiver(stream_id='c'*32)
        self.deliver(rec)
        await_condition(lambda: rec.assembler.counts['foreign'] == self.plan.count)
        self.assertIsNone(rec.take())
        fresh = fragment_plan(encode_packet(image(), candidate(stream='c'*32)), message_bytes=16384)
        self.deliver(rec, fresh)
        await_condition(lambda: output_ready(rec))
        self.assertEqual(rec.take().candidate['stream_id'], 'c'*32)

    def test_dedicated_channel_configuration_required(self):
        for key, val in (('label', 'control'), ('protocol', ''), ('ordered', True),
                         ('maxRetransmits', None), ('maxPacketLifeTime', 10)):
            obj = FakeChannel()
            setattr(obj, key, val)
            with self.assertRaises(ValueError):
                self.sender(obj)

    def test_producer_copies_before_worker_and_does_not_mutate_input(self):
        tx, source, meta = self.sender(), image(), candidate()
        original = copy.deepcopy(meta)
        tx.submit(source, meta)
        source[:] = 0
        meta['capture_sequence'] = 999
        await_condition(lambda: output_ready(tx.worker))
        plan = tx.worker._take()
        dec = FramePacketReceiver(sender_id=SENDER, stream_id=STREAM, max_receive_age_sec=.2)
        value = dec.accept(plan.wire, received_at_sec=500.)
        self.assertEqual(value.candidate, original)
        self.assertGreater(value.image.mean(), 70.)

    def test_encoder_skips_replaced_pending_and_delivers_latest(self):
        gate, entered, encoded = threading.Event(), threading.Event(), []
        tx = self.sender(clock=Clock(10.15))
        original = channel_module.encode_packet
        def blocked(pixels, meta):
            encoded.append(meta['capture_sequence'])
            entered.set()
            gate.wait(2.)
            return original(pixels, meta)
        with patch.object(channel_module, 'encode_packet', blocked):
            tx.submit(image(), candidate())
            self.assertTrue(entered.wait(1.))
            tx.submit(image(), candidate(sequence=2))
            tx.submit(image(), candidate(sequence=3))
            gate.set()
            await_condition(lambda: output_ready(tx.worker))
        self.assertEqual(encoded, [1, 3])
        self.assertEqual(tx.worker._take().sequence, 3)

    def test_decode_exception_retires_and_discards_old_pair(self):
        rec = self.receiver()
        self.deliver(rec)
        await_condition(lambda: output_ready(rec))
        newer = fragment_plan(encode_packet(image(), candidate(sequence=2)), message_bytes=16384)
        with patch.object(FramePacketReceiver, 'accept', side_effect=ValueError('injected decode failure')):
            self.deliver(rec, newer)
            self.assertTrue(rec.done.wait(1.))
        self.assertIsNone(rec.take())
        self.assertIn('injected decode failure', rec.error)

    def test_malformed_fragment_clears_available_output_without_decode(self):
        rec = self.receiver()
        self.deliver(rec)
        await_condition(lambda: output_ready(rec))
        with patch.object(FramePacketReceiver, 'accept', side_effect=AssertionError('must not decode')):
            self.assertTrue(rec.offer_message(b'malformed'))
            await_condition(lambda: rec.assembler.counts['invalid'] == 1)
        self.assertIsNone(rec.take())

    def test_no_packet_parsing_in_message_callback(self):
        rec, ids = self.receiver(), []
        original = rec.assembler.accept
        def accept(*args, **kwargs):
            ids.append(threading.get_ident())
            return original(*args, **kwargs)
        with patch.object(rec.assembler, 'accept', accept):
            self.deliver(rec)
            await_condition(lambda: output_ready(rec))
        self.assertEqual(ids, [rec.thread.ident]*self.plan.count)
        self.assertNotEqual(rec.thread.ident, threading.get_ident())

    def test_clock_exception_at_ingress_or_take_is_fail_closed(self):
        rec = self.receiver()
        rec.clock = lambda: 1/0
        self.assertFalse(rec.offer_message(self.plan.fragment(0)))
        self.assertIsNone(rec.take())
        self.assertTrue(rec.retired.is_set())
        other = self.receiver()
        self.deliver(other)
        await_condition(lambda: output_ready(other))
        other.clock = lambda: 1/0
        self.assertIsNone(other.take())
        self.assertEqual(other.error, 'consumer_clock_failed')

    def test_consumer_clock_reversal_or_before_decode_completion_retires(self):
        clock = Clock(500.)
        rec = self.receiver(clock=clock)
        self.deliver(rec)
        await_condition(lambda: output_ready(rec))
        clock.now = 499.
        self.assertIsNone(rec.take())
        self.assertTrue(rec.retired.is_set())

    def test_worker_clock_reversal_after_previous_processing_retires(self):
        clock = Clock(500.)
        rec = self.receiver(clock=clock)
        self.deliver(rec)
        await_condition(lambda: output_ready(rec))
        clock.now = 500.1
        rec.last_processing = 500.2  # Recorded by a previous processing read.
        self.assertTrue(rec.offer_message(self.plan.fragment(0)))
        self.assertTrue(rec.done.wait(1.))
        self.assertIsNone(rec.take())

    def test_invalid_producer_input_retires_prior_output(self):
        tx = self.sender()
        tx.submit(image(), candidate())
        await_condition(lambda: output_ready(tx.worker))
        self.assertFalse(tx.submit(image(), dict(candidate(), usable_for_ffb=True)))
        tx.pump()
        self.assertTrue(tx.closed)
        self.assertEqual(tx.channel.sent, [])

    def test_close_during_multi_message_pump_retires_immediately(self):
        channel = FakeChannel()
        tx = self.sender(channel)
        tx.submit(image(), candidate())
        await_condition(lambda: output_ready(tx.worker))
        original = channel.send
        def closes(message):
            original(message)
            channel.readyState = 'closed'
        channel.send = closes
        self.assertEqual(tx.pump(budget=8), 1)
        self.assertTrue(tx.closed)
        self.assertEqual(tx.scheduler.retained_bytes, 0)

    def test_close_timeout_validation(self):
        rec = self.receiver()
        for timeout in (-1, 2, float('nan'), True):
            with self.assertRaises(ValueError):
                rec.close(timeout_sec=timeout)


if __name__ == '__main__':
    unittest.main()
