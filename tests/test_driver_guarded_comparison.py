"""Synthetic images/real threads and memory pipes; no device/ROS/GPU/network."""
import argparse
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from cone_distance_core import load_config
from cone_guarded_stream_comparison import GuardedStreamComparison
from cone_motion_range import MotionRangeEngine, load_motion_profile
from cone_upper_support_candidate import observe_upper_completion
from driver_guarded_comparison import GuardedComparisonWorker, ComparisonLimits, comparison_path
from driver_motion_bridge import add_motion_arguments, bridge_from_args
from driver_motion_process import serve
from driver_motion_protocol import read_message, write_frame
from manage_guarded_comparison import issue, status
from theta_rtc_frames import NativeFrame

SESSION = 'a'*32
BOX = dict(x1=301., y1=305., x2=339., y2=399.6, confidence=.95, class_id=0)


def wait(predicate, timeout=4.):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('bounded test wait expired')
        time.sleep(.005)


class AsyncComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings, self.camera, _, _ = load_config()
        self.profile, self.sha = load_motion_profile(ROOT/('Experimental_results/2026-11-09/'
            'cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'), self.settings)
        self.image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(self.image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
        self.image.flags.writeable = False
        self.now = 10.01
        self.worker = self.start()

    def start(self, **kwargs):
        path = self.root/str(len(list(self.root.iterdir())))
        worker = GuardedComparisonWorker(path, self.settings, self.camera, self.profile, self.sha,
            clock=lambda:self.now, **kwargs)
        self.addCleanup(worker.close)
        wait(lambda: (path/'comparison_status.json').exists() or worker.error)
        return worker

    def original(self, sequence=1, source=10., session=SESSION, boxes=None):
        frame = NativeFrame(session, sequence, .1*sequence, source, self.image)
        engine = MotionRangeEngine(self.settings, self.camera, self.profile, self.sha,
            acknowledged=True, observer=observe_upper_completion)
        result = engine.measure(frame, [BOX] if boxes is None else boxes, source+.005)
        return frame, json.dumps(result)+'\n'

    def feed(self, sequence=1, source=10., session=SESSION, boxes=None):
        frame, line = self.original(sequence, source, session, boxes)
        self.now = source+.01
        count = self.worker.processed
        self.assertTrue(self.worker.offer(frame, line))
        wait(lambda:self.worker.processed > count or self.worker.error)
        self.assertIsNone(self.worker.error)
        return self.rows()[-1]

    def rows(self):
        return [json.loads(line) for line in (self.worker.directory/'comparison_frames.jsonl').read_text().splitlines()]

    def pin(self):
        issue(self.worker.directory, 'pin')
        wait(lambda:self.worker.info['state']=='pin_pending')
        self.feed()
        self.assertEqual(self.worker.saved, 1)
        return self.worker.info['pin']

    def load(self):
        meta = self.pin()
        ref = dict(schema='offline_self_body_boundary_v1', image_size=[1280,720],
            layout='dual_fisheye_front_left_unremapped',session=meta['session'],source_frame=meta['frame'],
            source_png_sha256=meta['png_sha256'],boundary_xy=[[280,458],[360,458]],
            independent_physical_measurement=False,cross_session_mount_verified=False,
            live_authorized=False,floor_contact_verified=False)
        (self.worker.directory/'reference.json').write_text(json.dumps(ref))
        issue(self.worker.directory, 'load')
        wait(lambda:self.worker.info['state'] in ('active','load_rejected'))
        self.assertEqual(self.worker.info['state'], 'active', self.worker.snapshot())

    def test_default_no_reference_no_snapshot_or_numeric(self):
        row = self.feed()
        self.assertFalse(row['comparison_distance_available'])
        self.assertEqual(list(self.worker.directory.glob('*.png')), [])

    def test_pin_load_future_result_exact_pixels_and_primary_unchanged(self):
        original = self.image.tobytes()
        self.load()
        row = self.feed(2,10.03)
        self.assertTrue(row['comparison_distance_available'])
        self.assertEqual(row['comparison_support_pixel'], [320,400])
        self.assertFalse(row['original_distance_available'])
        self.assertFalse(row['reference_used_posthoc'])
        self.assertEqual(self.image.tobytes(), original)
        actual = cv2.imread(str(next(self.worker.directory.glob('*.png'))))
        np.testing.assert_array_equal(actual, self.image)

    def test_no_candidate_does_not_hold_previous_value(self):
        self.load();self.feed(2,10.03)
        row = self.feed(3,10.06,boxes=[])
        self.assertFalse(row['comparison_distance_available'])
        self.assertIsNone(self.worker.snapshot()['latest']['comparison_range_m'])

    def test_primary_numeric_is_kept_when_comparison_body_veto_withholds(self):
        self.load()
        path=self.worker.directory/'reference.json'
        ref=json.loads(path.read_text());ref['boundary_xy']=[[280,400],[360,400]]
        path.write_text(json.dumps(ref));request=issue(self.worker.directory,'load')
        wait(lambda:self.worker.info['request_id']==request['request_id'] and self.worker.info['state']=='active')
        row=self.feed(2,10.03,boxes=[dict(BOX,y2=405.)])
        self.assertTrue(row['original_distance_available'])
        self.assertIsNotNone(row['original_range_m'])
        self.assertFalse(row['comparison_distance_available'])

    def test_nonblocking_busy_offer(self):
        frame,line = self.original()
        with self.worker.lock:
            self.assertFalse(self.worker.offer(frame,line))
        self.assertEqual(self.worker.busy_drops,1)

    def test_capacity_one_skips_intermediate_frames_while_comparison_blocked(self):
        started, release = threading.Event(), threading.Event()
        class SlowStream(GuardedStreamComparison):
            def compare(self,*args):
                started.set();release.wait(3.)
                return super().compare(*args)
        self.worker = self.start(stream_factory=SlowStream)
        frame,line = self.original();self.worker.offer(frame,line);self.assertTrue(started.wait(2.))
        for seq in (2,3,4):
            frame,line=self.original(seq,10.+seq*.01)
            self.assertTrue(self.worker.offer(frame,line))
        self.now=10.06;release.set()
        wait(lambda:self.worker.processed==2)
        self.assertEqual([r['frame'] for r in self.rows()],[1,4])
        self.assertEqual(self.worker.dropped,2)

    def test_stale_snapshot_and_session_change_remove_numeric(self):
        self.load();self.feed(2,10.03)
        self.now=11.
        self.assertIsNone(self.worker.snapshot()['latest'])
        row=self.feed(1,11.03,session='b'*32)
        self.assertFalse(row['comparison_distance_available'])

    def test_wrong_session_load_rejected_without_restoring_old_value(self):
        self.load();self.feed(2,10.03)
        ref_path=self.worker.directory/'reference.json'
        ref=json.loads(ref_path.read_text());ref['session']='b'*32;ref_path.write_text(json.dumps(ref))
        issue(self.worker.directory,'load')
        wait(lambda:self.worker.info['state']=='load_rejected')
        self.assertIsNone(self.worker.snapshot()['latest'])
        self.assertFalse(self.feed(3,10.06)['comparison_distance_available'])

    def test_symlink_reference_and_bad_request_invalidate(self):
        self.load();self.feed(2,10.03)
        ref=self.worker.directory/'reference.json';other=self.root/'other.json'
        other.write_bytes(ref.read_bytes());ref.unlink();ref.symlink_to(other)
        issue(self.worker.directory,'load');wait(lambda:self.worker.info['state']=='load_rejected')
        (self.worker.directory/'request.json').write_text('{bad')
        wait(lambda:self.worker.info['state']=='request_rejected')
        self.assertIsNone(self.worker.snapshot()['latest'])

    def test_explicit_invalidate(self):
        self.load();self.feed(2,10.03)
        issue(self.worker.directory,'invalidate')
        wait(lambda:self.worker.info['state']=='invalidated')
        self.assertIsNone(self.worker.snapshot()['latest'])

    def test_request_not_replayed_and_higher_id_required(self):
        self.pin()
        time.sleep(.12)
        self.assertEqual(self.worker.request_count,1)
        self.assertEqual(self.worker.saved,1)

    def test_snapshot_budget_stops_only_new_pin(self):
        self.worker=self.start(limits=ComparisonLimits(max_snapshots=1))
        self.pin();issue(self.worker.directory,'pin')
        wait(lambda:self.worker.info['state']=='pin_pending')
        self.feed(2,10.03)
        self.assertEqual(self.worker.info['state'],'pin_rejected')
        self.assertEqual(self.worker.saved,1);self.assertIsNone(self.worker.error)

    def test_log_budget_and_request_budget_disable_comparison_only(self):
        self.worker=self.start(limits=ComparisonLimits(max_log_bytes=1024))
        self.feed()
        frame,line=self.original(2,10.03);self.now=10.04;self.worker.offer(frame,line)
        wait(lambda:self.worker.error)
        self.assertLessEqual((self.worker.directory/'comparison_frames.jsonl').stat().st_size,1024)
        self.assertFalse(self.worker.offer(frame,line))
        self.worker=self.start(limits=ComparisonLimits(max_requests=1))
        self.pin();issue(self.worker.directory,'invalidate')
        wait(lambda:self.worker.error)
        self.assertIn('request budget',self.worker.error)

    def test_write_failure_disables_worker_not_primary(self):
        with patch.object(GuardedComparisonWorker,'_status',side_effect=OSError('synthetic disk failure')):
            worker=self.start();wait(lambda:worker.error)
            self.assertIn('disk failure',worker.error)
        frame,line=self.original()
        self.assertFalse(worker.offer(frame,line))

    def test_bounded_close_reports_blocked_worker_and_discards_pending(self):
        started,release=threading.Event(),threading.Event()
        class Blocked(GuardedStreamComparison):
            def compare(self,*args):
                started.set();release.wait(3.)
                return super().compare(*args)
        self.worker=self.start(stream_factory=Blocked)
        frame,line=self.original();self.worker.offer(frame,line);self.assertTrue(started.wait(2.))
        result=self.worker.close(.01)
        self.assertFalse(result['writer_stopped'])
        self.assertIsNone(self.worker.snapshot()['latest'])
        self.assertFalse(self.worker.offer(frame,line))
        release.set();wait(lambda:not self.worker.thread.is_alive())
        self.assertTrue(self.worker.close()['writer_stopped'])

    def test_mismatching_main_line_disables_comparison(self):
        frame,line=self.original()
        value=json.loads(line);value['frame']=2
        self.worker.offer(frame,json.dumps(value)+'\n')
        wait(lambda:self.worker.error)
        self.assertEqual(self.worker.processed,0)

    def test_clean_close_status_and_requests_after_close_rejected(self):
        self.feed();self.assertTrue(self.worker.close()['shutdown_complete'])
        saved=json.loads((self.worker.directory/'comparison_status.json').read_text())
        self.assertTrue(saved['writer_done']);self.assertTrue(saved['shutdown_complete'])
        self.assertIsNone(status(self.worker.directory)['latest'])
        with self.assertRaises(ValueError):issue(self.worker.directory,'pin')

    def test_native_dimensions_immutable_buffer_and_size_bounds(self):
        frame,line=self.original()
        wrong=NativeFrame(frame.session,1,.1,10.,self.image.copy())
        self.assertFalse(self.worker.offer(wrong,line))
        self.assertFalse(self.worker.offer(frame,'x'*(1024*1024+1)))
        for kwargs in (dict(max_snapshots=True),dict(max_log_bytes=100),dict(max_requests=129)):
            with self.assertRaises(ValueError):ComparisonLimits(**kwargs)

    def test_primary_pipe_is_identical_when_optional_offer_raises(self):
        frame,_=self.original();data=io.BytesIO();write_frame(data,frame)
        class Broken:
            def offer(self,*args):raise OSError('comparison failure')
        outputs=[]
        for hook in (None,Broken()):
            engine=MotionRangeEngine(self.settings,self.camera,self.profile,self.sha,
                acknowledged=True,observer=observe_upper_completion)
            output=io.BytesIO()
            serve(engine,lambda frame:[BOX],io.BytesIO(data.getvalue()),output,
                self.root/('main_'+str(len(outputs))+'.jsonl'),clock=lambda:10.01,comparison=hook)
            output.seek(0);messages=[]
            while True:
                try:messages.append(read_message(output))
                except EOFError:break
            outputs.append(messages)
        self.assertEqual(outputs[0],outputs[1])


class ComparisonCLIPathTests(unittest.TestCase):
    def args(self, root, comparison):
        parser=argparse.ArgumentParser()
        parser.set_defaults(cam_width=1280,cam_height=720,front_lens='left',mock_camera=False)
        add_motion_arguments(parser)
        weights=root/'test.pt';weights.write_bytes(b'fixture NOT model')
        return parser.parse_args(['--motion-distance','--motion-experimental-rigid-mount',
            '--motion-python',sys.executable,'--motion-weights',str(weights),
            '--motion-profile',str(ROOT/'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'),
            '--motion-output-dir',str(root/'primary'),'--motion-comparison-dir',str(comparison)])

    def test_ui_option_is_forwarded_to_child_without_starting_process(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'recordings',prefix='guarded_cli_test_') as temp:
            root=Path(temp);directory=root/'comparison'
            bridge=bridge_from_args(self.args(root,directory))
            try:
                self.assertEqual(bridge.command[bridge.command.index('--comparison-dir')+1],str(directory))
                self.assertIsNone(bridge.process)
                self.assertFalse(directory.exists())
                self.assertIsNone(bridge.close()['image_files_written'])
            finally:bridge.close()

    def test_nested_primary_and_comparison_paths_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'recordings',prefix='guarded_cli_test_') as temp:
            root=Path(temp)
            with self.assertRaisesRegex(ValueError,'separate'):
                bridge_from_args(self.args(root,root/'primary/comparison'))
            self.assertFalse((root/'primary').exists())

    def test_default_off_and_comparison_cannot_start_without_main_optin(self):
        parser=argparse.ArgumentParser();add_motion_arguments(parser)
        self.assertIsNone(bridge_from_args(parser.parse_args([])))
        with self.assertRaises(ValueError):
            bridge_from_args(parser.parse_args(['--motion-comparison-dir','unused']))

    def test_comparison_path_is_new_and_under_recordings(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(comparison_path(root/'recordings/new',root),root/'recordings/new')
            for path in (root,root/'recordings',root/'elsewhere'):
                with self.assertRaises(ValueError):comparison_path(path,root)
            (root/'recordings/old').mkdir(parents=True)
            with self.assertRaises(ValueError):comparison_path(root/'recordings/old',root)


if __name__=='__main__':
    unittest.main()
