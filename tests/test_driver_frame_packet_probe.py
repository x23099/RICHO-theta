"""Transport-only probe tests; no RTC, camera, ROS or GPU is created."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('frame_packet_probe_test',
                                              ROOT / 'src/driver_frame_packet_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

PROFILE = dict(schema='frame_motion_connection_v1', sender_id='a' * 32, stream_id='b' * 32,
               rate_hz=5, message_cap=16384, receive_age_limit_sec=.2,
               physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)


def packet(sequence, *, received=0., nbytes=1200):
    image = types.SimpleNamespace(nbytes=nbytes)
    return types.SimpleNamespace(candidate=dict(capture_sequence=sequence), image=image,
                                 received_at_sec=received, packet_sha256='c' * 64)


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


class ProbeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def test_missing_directory_and_role_are_rejected(self):
        with self.assertRaises(ValueError):
            probe.ProbeRecorder(self.directory / 'absent', 'sender', PROFILE)
        with self.assertRaises(ValueError):
            probe.ProbeRecorder(self.directory, 'other', PROFILE)

    def test_summary_is_written_and_closed(self):
        clock = Clock()
        recorder = probe.ProbeRecorder(self.directory, 'sender', PROFILE, interval_sec=10, clock=clock)
        recorder.update(messages_sent=7)
        recorder.set_provider(lambda: dict(scheduler=dict(offered=3, expired=1)))
        self.assertTrue(recorder.close())
        value = json.loads((self.directory / 'sender_probe.json').read_bytes())
        self.assertEqual(value['schema'], probe.SCHEMA)
        self.assertEqual(value['role'], 'sender')
        self.assertEqual(value['profile'], PROFILE)
        self.assertEqual(value['counters']['messages_sent'], 7)
        self.assertEqual(value['channel']['scheduler']['expired'], 1)
        self.assertTrue(value['closed'])
        self.assertFalse(value['inference_started'])
        self.assertFalse(value['ros_published'])
        self.assertFalse(value['usable_for_ffb'])

    def test_profile_can_be_set_after_construction(self):
        recorder = probe.ProbeRecorder(self.directory, 'receiver', None, interval_sec=10)
        self.assertIsNone(json.loads((self.directory / 'receiver_probe.json').read_bytes())['profile'])
        recorder.set_profile(PROFILE)
        recorder.close()
        self.assertEqual(json.loads((self.directory / 'receiver_probe.json').read_bytes())['profile'], PROFILE)

    def test_provider_failure_is_recorded_without_raising(self):
        recorder = probe.ProbeRecorder(self.directory, 'receiver', PROFILE, interval_sec=10)

        def broken():
            raise RuntimeError('state unavailable')

        recorder.set_provider(broken)
        recorder.close()
        value = json.loads((self.directory / 'receiver_probe.json').read_bytes())
        self.assertIn('state_error', value['channel'])
        self.assertIn('state unavailable', value['channel']['state_error'])

    def test_sink_counts_frames_gaps_and_latency_without_retaining_images(self):
        clock = Clock()
        recorder = probe.ProbeRecorder(self.directory, 'receiver', PROFILE, interval_sec=10, clock=clock)
        sink = probe.ProbePacketSink(recorder, clock=clock)
        sink.begin_packet(PROFILE)
        clock.now = 0.1
        sink.publish_packet(packet(1, received=0.0))
        clock.now = 0.3
        sink.publish_packet(packet(3, received=0.1))
        clock.now = 0.4
        sink.publish_packet(packet(3, received=0.2))
        sink.end('session', 'peer_closed')
        recorder.close()
        value = json.loads((self.directory / 'receiver_probe.json').read_bytes())
        counters = value['counters']
        self.assertEqual(counters['frames_published'], 3)
        self.assertEqual(counters['image_bytes'], 3600)
        self.assertEqual(counters['sequence_gaps'], 1)
        self.assertEqual(counters['out_of_order'], 1)
        self.assertEqual(counters['reason'], 'peer_closed')
        self.assertAlmostEqual(counters['delivery_latency_min_sec'], 0.1)
        self.assertAlmostEqual(counters['delivery_latency_max_sec'], 0.2)
        self.assertIsNone(value['channel'])

    def test_sender_state_handles_unactivated_and_active_bindings(self):
        idle = types.SimpleNamespace(tx=None, error='not_activated',
                                     source=types.SimpleNamespace(error=None))
        self.assertFalse(probe.sender_state(idle)['activated'])
        active = types.SimpleNamespace(
            tx=types.SimpleNamespace(messages_sent=9, scheduler=types.SimpleNamespace(
                    counts=dict(offered=2, packets_handed_off=2), peak_retained_bytes=2048),
                worker=types.SimpleNamespace(replaced=1, peak_queued=1), error=None),
            error=None, source=types.SimpleNamespace(error=None))
        state = probe.sender_state(active)
        self.assertTrue(state['activated'])
        self.assertEqual(state['messages_sent'], 9)
        self.assertEqual(state['scheduler']['packets_handed_off'], 2)
        self.assertEqual(state['encoder_replaced'], 1)

    def test_receiver_state_copies_assembler_counts(self):
        binding = types.SimpleNamespace(
            rx=types.SimpleNamespace(assembler=types.SimpleNamespace(
                    counts=dict(completed=4, delivered=3), peak_retained_bytes=1024),
                replaced=0, peak_queued=2, error=None),
            error=None)
        state = probe.receiver_state(binding)
        self.assertTrue(state['configured'])
        self.assertEqual(state['assembler']['completed'], 4)
        self.assertEqual(state['inbox_peak_queued'], 2)

    def test_background_flush_writes_before_close(self):
        clock = Clock()
        recorder = probe.ProbeRecorder(self.directory, 'sender', PROFILE, interval_sec=0.1, clock=clock)
        recorder.update(messages_sent=1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = json.loads((self.directory / 'sender_probe.json').read_bytes())
            if value['counters'].get('messages_sent') == 1:
                break
            time.sleep(0.02)
        else:
            self.fail('periodic flush did not persist counters')
        recorder.close()


if __name__ == '__main__':
    unittest.main()
