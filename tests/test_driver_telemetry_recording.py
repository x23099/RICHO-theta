"""Local synthetic disk/peer tests only; no ROS/Qt/network/GPU is started."""
import argparse
import asyncio
import ast
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from driver_telemetry_recording import TelemetryRecorder, add_recording_arguments, recorder_from_args
from test_driver_motion_integration import FakeRequest, FakeVideo, receiver_class
from driver_motion_protocol import PROFILE

SESSION = 'a'*32


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'capture'
        self.recorders = []
        self.addCleanup(self.cleanup_recorders)

    def cleanup_recorders(self):
        for recorder in self.recorders:
            recorder.close()

    def recorder(self, **changes):
        args = dict(max_bytes=100000, max_records=100, queue_size=16, clock=lambda:100.)
        args.update(changes)
        recorder = TelemetryRecorder(self.directory, **args)
        self.recorders.append(recorder)
        return recorder

    def rows(self):
        return [json.loads(line) for line in (self.directory/'received_telemetry.jsonl').read_bytes().splitlines()]

    def wait(self, predicate):
        deadline = time.monotonic()+2.
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.002)
        self.fail('bounded synthetic wait expired')

    def test_disabled_option_has_no_files_or_thread(self):
        parser = argparse.ArgumentParser(); add_recording_arguments(parser)
        with patch('driver_telemetry_recording.TelemetryRecorder') as constructor:
            self.assertIsNone(recorder_from_args(parser.parse_args([])))
            constructor.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_cli_requires_new_directory_under_recordings_and_bounded_limits(self):
        parser = argparse.ArgumentParser(); add_recording_arguments(parser)
        root = Path(self.temp.name)
        with patch('driver_telemetry_recording.ROOT', root):
            path = root/'recordings/run'
            value = recorder_from_args(parser.parse_args(['--telemetry-record-dir', str(path)]))
            self.assertFalse(path.exists()); self.assertFalse(value.started)
            value.close()
            for args in (['--telemetry-record-dir', str(root/'elsewhere')],
                         ['--telemetry-record-max-mib', '2'],
                         ['--telemetry-record-dir', str(path), '--telemetry-record-queue-size', '0'],
                         ['--telemetry-record-dir', str(path), '--telemetry-record-max-records', '1000001']):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    recorder_from_args(parser.parse_args(args))
            path.mkdir(parents=True)
            with self.assertRaises(ValueError):
                recorder_from_args(parser.parse_args(['--telemetry-record-dir', str(path)]))

    def test_symlink_outside_recordings_rejected(self):
        root = Path(self.temp.name); (root/'recordings').mkdir()
        (root/'outside').mkdir(); (root/'recordings/link').symlink_to(root/'outside', target_is_directory=True)
        parser = argparse.ArgumentParser(); add_recording_arguments(parser)
        with patch('driver_telemetry_recording.ROOT', root), self.assertRaises(ValueError):
            recorder_from_args(parser.parse_args(['--telemetry-record-dir', str(root/'recordings/link/new')]))

    def test_actual_received_zero_is_recorded_but_not_verified_motion(self):
        recorder = self.recorder(); recorder.start()
        original = dict(linear_x=0., angular_z=-.1, speed_mps=0., imu_yaw_rate=.2,
                        timestamp=1794800000000, secret='do not save', measurement_valid=True,
                        source_stamp_ns=123, source_clock_id='claim')
        before = dict(original)
        self.assertTrue(recorder.offer(SESSION, original, 1.))
        status = recorder.close()
        self.assertEqual(original, before)
        row = self.rows()[0]
        self.assertEqual(row['linear_mps'], 0.)
        self.assertEqual(row['angular_radps'], -.1)
        self.assertEqual(row['sender_wall_time_ms'], original['timestamp'])
        self.assertIsNone(row['measurement_valid']); self.assertIsNone(row['source_stamp_ns'])
        self.assertIsNone(row['source_clock_id']); self.assertIsNone(row['motion_frame_id'])
        self.assertNotIn('secret', json.dumps(row))
        self.assertIs(row['usable_for_ffb'], False)
        self.assertEqual(row['logged_at_sec'], 100.)
        self.assertTrue(status['shutdown_complete']); self.assertIsNone(status['error'])
        self.assertEqual(status['written'], 1)
        self.assertEqual(status['log_bytes'], (self.directory/'received_telemetry.jsonl').stat().st_size)
        self.assertEqual(status, json.loads((self.directory/'telemetry_recording_summary.json').read_bytes()))

    def test_missing_values_not_zero_filled_and_bad_values_not_saved(self):
        recorder = self.recorder(); recorder.start()
        recorder.offer(SESSION, {}, 1.)
        recorder.offer(SESSION, dict(linear_x=True, angular_z=float('nan'), speed_mps='0.2',
                                   imu_yaw_rate=10**1000, timestamp=-1), 2.)
        recorder.close(); rows = self.rows()
        for row in rows:
            for key in ('linear_mps', 'angular_radps', 'speed_mps', 'imu_yaw_rate_radps', 'sender_wall_time_ms'):
                self.assertIsNone(row[key])
        self.assertEqual(rows[0]['invalid_fields'], [])
        self.assertEqual(set(rows[1]['invalid_fields']), {'linear_x', 'angular_z', 'speed_mps', 'imu_yaw_rate', 'timestamp'})

    def test_callbacks_never_write_serialize_or_touch_disk(self):
        recorder = self.recorder(); recorder.start()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = recorder._write_record
        def slow(stream, wire):
            entered.set(); release.wait(2.); original(stream, wire)
        with patch.object(recorder, '_write_record', side_effect=slow):
            recorder.offer(SESSION, {}, 1.)
            self.assertTrue(entered.wait(1.))
            before = time.monotonic()
            for _ in range(100):
                recorder.offer(SESSION, dict(linear_x=.1), 2.)
            self.assertLess(time.monotonic()-before, .25)
            self.assertLessEqual(recorder.queue.qsize(), recorder.queue.maxsize)
            self.assertGreater(recorder.snapshot()['queue_drops'], 0)
            # Close is bounded even when a disk writer cannot finish.
            status = recorder.close(timeout_sec=.001)
            self.assertFalse(status['shutdown_complete'])
            release.set(); self.assertTrue(recorder.close()['shutdown_complete'])
        # The production callback only calls fixed scalar operations/put_nowait.
        node = next(n for n in ast.parse((ROOT/'src/driver_telemetry_recording.py').read_text()).body
                    if isinstance(n, ast.ClassDef) and n.name == 'TelemetryRecorder')
        offer = next(n for n in node.body if getattr(n, 'name', '') == '_offer')
        text = ast.unparse(offer)
        for forbidden in ('open(', 'json.dumps', '.write(', '.flush(', '.join(', 'queue.put('):
            self.assertNotIn(forbidden, text)

    def test_queue_and_count_conservation_after_normal_drain(self):
        recorder = self.recorder(); recorder.start()
        for number in range(50):
            recorder.offer(SESSION, dict(linear_x=number), 1.)
        status = recorder.close()
        self.assertEqual(status['offered'], status['queued']+status['queue_drops']+status['rejected'])
        self.assertEqual(status['queued'], status['written']+status['discarded_pending'])
        self.assertEqual(status['pending'], 0); self.assertEqual(status['in_flight'], 0)
        self.assertEqual(status['written'], len(self.rows()))

    def test_record_and_byte_limits_stop_only_recording(self):
        for maximum, count in ((1, 100), (100000, 1)):
            self.directory = Path(self.temp.name)/('limit_'+str(maximum))
            recorder = self.recorder(max_bytes=maximum, max_records=count); recorder.start()
            for _ in range(3):
                recorder.offer(SESSION, {}, 1.)
            status = recorder.close()
            self.assertEqual(status['state'], 'limit_reached')
            self.assertLessEqual(status['log_bytes'], maximum)
            self.assertLessEqual(status['written'], count)
            self.assertEqual(status['queued'], status['written']+status['discarded_pending'])

    def test_writer_failure_preserves_truthful_error_and_counts(self):
        recorder = self.recorder()
        with patch.object(recorder, '_write_record', side_effect=OSError('synthetic disk full')):
            recorder.start(); recorder.offer(SESSION, {}, 1.)
            self.wait(recorder.done.is_set)
            status = recorder.close()
        self.assertEqual(status['state'], 'writer_error')
        self.assertIn('disk full', status['error'])
        self.assertEqual(status['queued'], status['discarded_pending'])
        self.assertFalse(recorder.offer(SESSION, {}, 2.))

    def test_existing_directory_and_evidence_never_overwritten(self):
        self.directory.mkdir(); (self.directory/'received_telemetry.jsonl').write_bytes(b'user evidence')
        recorder = self.recorder(); recorder.start(); status = recorder.close()
        self.assertEqual(status['state'], 'writer_error')
        self.assertEqual((self.directory/'received_telemetry.jsonl').read_bytes(), b'user evidence')
        self.assertFalse((self.directory/'telemetry_recording_summary.json').exists())

    def test_invalid_writer_clock_rejects_dequeued_record_with_count(self):
        for now in (float('nan'), .5):
            self.directory = Path(self.temp.name)/str(now)
            recorder = self.recorder(clock=lambda:now); recorder.start()
            recorder.offer(SESSION, {}, 1.); status = recorder.close()
            self.assertEqual(status['state'], 'writer_error')
            self.assertEqual(status['written'], 0)
            self.assertEqual(status['queued'], status['discarded_pending'])

    def test_lifecycle_and_reconnect_session_id_retained(self):
        recorder = self.recorder(); recorder.start()
        recorder.lifecycle(SESSION, 'peer_begin', 1.)
        recorder.offer('b'*32, dict(linear_x=.2), 2.)
        recorder.offer(SESSION, dict(linear_x=.1), 3.)
        recorder.lifecycle(SESSION, 'peer_closed', 4.)
        recorder.close(); rows = self.rows()
        self.assertEqual([r['session'] for r in rows], [SESSION, 'b'*32, SESSION, SESSION])
        self.assertIsNone(rows[0]['linear_mps'])
        self.assertEqual(len({r['receiver_clock_id'] for r in rows}), 1)

    def test_bad_input_and_lock_contention_return_without_exception(self):
        recorder = self.recorder(); recorder.start()
        for session, data, at in (('bad', {}, 1.), (SESSION, [], 1.), (SESSION, {}, True), (SESSION, {}, float('nan'))):
            self.assertFalse(recorder.offer(session, data, at))
        with recorder.lock:
            self.assertFalse(recorder.offer(SESSION, {}, 1.))
        recorder.close()
        self.assertEqual(recorder.snapshot()['busy_drops'], 1)

    def test_double_start_close_and_never_started(self):
        recorder = self.recorder()
        self.assertFalse(recorder.offer(SESSION, {}, 1.))
        self.assertTrue(recorder.close()['shutdown_complete'])
        self.assertFalse(self.directory.exists())
        with self.assertRaises(ValueError):
            recorder.start()
        self.directory = Path(self.temp.name)/'second'
        recorder = self.recorder(); recorder.start()
        with self.assertRaises(ValueError):
            recorder.start()
        self.assertTrue(recorder.close()['shutdown_complete'])
        self.assertTrue(recorder.close()['shutdown_complete'])

    def test_thread_start_failure_still_has_bounded_close(self):
        recorder = self.recorder()
        with patch.object(recorder.thread, 'start', side_effect=RuntimeError('synthetic no thread')):
            with self.assertRaises(RuntimeError):
                recorder.start()
        status = recorder.close()
        self.assertTrue(status['shutdown_complete'])
        self.assertEqual(status['state'], 'start_failed')
        self.assertFalse(self.directory.exists())


class ReceiverRecordingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.recorder = TelemetryRecorder(Path(self.temp.name)/'capture', max_records=100,
                                          max_bytes=100000, queue_size=32)
        self.recorder.start(); self.addCleanup(self.recorder.close)
        signals = SimpleNamespace(telemetry_received=SimpleNamespace(emit=Mock()), latency_updated=SimpleNamespace(emit=Mock()))
        self.server = receiver_class()(signals, telemetry_recorder=self.recorder)

    def channel(self, peer):
        handlers = {}
        def on(event):
            def decorator(fn): handlers[event] = fn; return fn
            return decorator
        peer.handlers['datachannel'](SimpleNamespace(label='telemetry', on=on))
        return handlers['message']

    def rows(self):
        self.recorder.close()
        return [json.loads(line) for line in (self.recorder.directory/'received_telemetry.jsonl').read_bytes().splitlines()]

    async def test_observer_receives_before_ui_with_same_connection_session(self):
        motion = SimpleNamespace(begin=Mock(), end=Mock())
        self.server.motion = motion
        await self.server.handle_offer(FakeRequest(dict(PROFILE)))
        session = motion.begin.call_args[0][0]
        handler = self.channel(self.server.pc)
        payload = dict(linear_x=.2, angular_z=-.1, timestamp=1794800000000)
        with patch('json.loads', wraps=json.loads) as loads:
            handler(json.dumps(payload))
            loads.assert_called_once()
        self.server.signals.telemetry_received.emit.assert_called_once_with(payload)
        rows = self.rows(); self.assertEqual(rows[0]['event_kind'], 'peer_begin')
        row = next(r for r in rows if r['event_kind'] == 'telemetry')
        self.assertEqual(row['session'], session)
        self.assertLessEqual(row['received_at_sec'], row['logged_at_sec'])
        self.assertEqual(row['linear_mps'], .2)
        control = SimpleNamespace(label='control')
        self.server.pc.handlers['datachannel'](control)
        self.assertIs(self.server.control_channel, control)

    async def test_reconnect_and_old_callback_not_relabelled(self):
        await self.server.handle_offer(FakeRequest(None)); old_peer = self.server.pc
        old = self.channel(old_peer)
        await self.server.handle_offer(FakeRequest(None)); new_peer = self.server.pc
        new = self.channel(new_peer)
        new('{"linear_x":0.2}'); old('{"linear_x":0.1}')
        old_peer.connectionState='closed'; await old_peer.handlers['connectionstatechange']()
        rows = self.rows(); beginnings = [r['session'] for r in rows if r['event_kind']=='peer_begin']
        self.assertEqual(len(set(beginnings)), 2)
        values = {r['linear_mps']:r['session'] for r in rows if r['event_kind']=='telemetry'}
        self.assertEqual(values[.2], beginnings[1]); self.assertEqual(values[.1], beginnings[0])
        self.assertEqual(self.server.signals.telemetry_received.emit.call_count, 2)

    async def test_broken_observer_does_not_suppress_ui_or_control(self):
        await self.server.handle_offer(FakeRequest(None))
        broken = SimpleNamespace(offer=Mock(side_effect=RuntimeError('synthetic observer fault')), request_stop=Mock())
        self.server.telemetry_recorder = broken
        handler = self.channel(self.server.pc); handler('{"linear_x":0.2}')
        self.assertIsNone(self.server.telemetry_recorder); broken.request_stop.assert_called_once()
        self.server.signals.telemetry_received.emit.assert_called_once_with(dict(linear_x=.2))
        control = SimpleNamespace(label='control'); self.server.pc.handlers['datachannel'](control)
        self.assertIs(self.server.control_channel, control)

    async def test_telemetry_recording_does_not_change_decoded_frame_mutability(self):
        with patch.object(self.recorder, 'lifecycle', wraps=self.recorder.lifecycle) as lifecycle:
            await self.server.handle_offer(FakeRequest(None))
            session = lifecycle.call_args[0][0]
        video = FakeVideo(); video.hold.set()
        await self.server.process_video(video, session)
        self.assertTrue(self.server.latest_frame.flags.writeable)
        self.assertTrue(any(r['event_kind']=='video_track_ended' for r in self.rows()))

    async def test_bad_json_does_not_enter_record_log_or_break_next_message(self):
        await self.server.handle_offer(FakeRequest(None)); handler = self.channel(self.server.pc)
        handler('bad json'); handler('{"linear_x":0.1}')
        self.assertEqual(self.server.signals.telemetry_received.emit.call_count, 1)
        self.assertEqual(sum(r['event_kind']=='telemetry' for r in self.rows()), 1)

    async def test_disk_failure_does_not_stop_ui_notifications_or_control(self):
        with patch.object(self.recorder, '_write_record', side_effect=OSError('synthetic disk full')):
            await self.server.handle_offer(FakeRequest(None))
            for _ in range(200):
                if self.recorder.done.is_set():
                    break
                await asyncio.sleep(.005)
            self.assertTrue(self.recorder.done.is_set())
            self.channel(self.server.pc)('{"linear_x":0.2}')
            self.server.signals.telemetry_received.emit.assert_called_once_with(dict(linear_x=.2))
            control = SimpleNamespace(label='control'); self.server.pc.handlers['datachannel'](control)
            self.assertIs(self.server.control_channel, control)
            self.assertEqual(self.recorder.snapshot()['state'], 'writer_error')

    async def test_slow_disk_full_queue_still_notifies_every_telemetry_message(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = self.recorder._write_record
        def slow(stream, wire):
            entered.set(); release.wait(2.); original(stream, wire)
        with patch.object(self.recorder, '_write_record', side_effect=slow):
            await self.server.handle_offer(FakeRequest(None))
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(.005)
            self.assertTrue(entered.is_set())
            handler = self.channel(self.server.pc)
            for _ in range(100):
                handler('{"linear_x":0.2}')
            self.assertEqual(self.server.signals.telemetry_received.emit.call_count, 100)
            self.assertGreater(self.recorder.snapshot()['queue_drops'], 0)
            control = SimpleNamespace(label='control'); self.server.pc.handlers['datachannel'](control)
            self.assertIs(self.server.control_channel, control)
            release.set(); self.assertTrue(self.recorder.close()['shutdown_complete'])


if __name__ == '__main__':
    unittest.main()
