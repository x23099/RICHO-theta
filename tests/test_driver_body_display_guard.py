"""Current-frame display veto: synthetic geometry, memory/real local pipes only."""
import argparse
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from driver_body_display_guard import BodyDisplayGuard,checked_display_review,FLAGS,CLEAR
from driver_motion_bridge import DriverMotionBridge,add_motion_arguments,bridge_from_args,panel_text
from driver_motion_protocol import PROFILE,read_message,write_frame
from driver_motion_process import serve
from theta_rtc_frames import NativeFrame
import test_driver_guarded_comparison as asynchronous
from test_driver_motion_bridge import image,valid_result

SESSION='a'*32


def original(y=400,number=20,source=10.):
    return dict(session=SESSION,frame=number,source_time_sec=source,distance_available=True,
        horizontal_camera_foot_range_m=1.2,reason='experimental',primary_model='synthetic',
        support_pixel=[320,y],support_observation=dict(point=[320,y],support=[[x,y] for x in range(312,329)],
            **{k:False for k in FLAGS}),**{k:False for k in FLAGS})


def capability(generation=1,activated_at=9.99):
    return dict(generation=generation,activation_frame=5,activated_at=activated_at,
        reference=dict(schema='offline_self_body_boundary_v1',session=SESSION,source_frame=1,
            source_png_sha256='b'*64,image_size=[1280,720],layout='dual_fisheye_front_left_unremapped',
            boundary_xy=[[280,455],[360,455]],independent_physical_measurement=False,
            cross_session_mount_verified=False,live_authorized=False,floor_contact_verified=False))


class BodyDisplayTests(unittest.TestCase):
    def test_clear_keeps_exact_value_support_and_original_unchanged(self):
        value=original();old=copy.deepcopy(value)
        result=BodyDisplayGuard().review(value,capability(),10.01)
        self.assertTrue(result['display_available']);self.assertEqual(result['display_range_m'],1.2)
        self.assertEqual(result['body_review_reason'],CLEAR);self.assertEqual(value,old)
        self.assertTrue(all(result[k] is False for k in FLAGS))

    def test_near_boundary_revokes_only_display(self):
        value=original(455);old=copy.deepcopy(value)
        result=BodyDisplayGuard().review(value,capability(),10.01)
        self.assertFalse(result['display_available']);self.assertIsNone(result['display_range_m'])
        self.assertEqual(result['reason'],'possible_self_body_occlusion');self.assertEqual(value,old)

    def test_any_support_column_not_only_point_must_clear(self):
        value=original();value['support_observation']['support'][0][1]=455
        self.assertEqual(BodyDisplayGuard().review(value,capability(),10.01)['reason'],'possible_self_body_occlusion')

    def test_missing_reference_cannot_fall_back_to_raw_number(self):
        result=BodyDisplayGuard().review(original(),None,10.01)
        self.assertFalse(result['display_available']);self.assertIsNone(result['display_range_m'])

    def test_wrong_session_future_activation_and_uncovered_support(self):
        cap=capability();cap['reference']['session']='b'*32
        self.assertEqual(BodyDisplayGuard().review(original(),cap,10.01)['reason'],'display_body_reference_session_mismatch')
        self.assertFalse(BodyDisplayGuard().review(original(),capability(activated_at=11.),10.01)['display_available'])
        cap=capability();cap['reference']['boundary_xy']=[[320,455],[360,455]]
        self.assertEqual(BodyDisplayGuard().review(original(),cap,10.01)['reason'],'self_body_reference_does_not_cover_support')

    def test_gap_retires_old_generation_until_new_explicit_load(self):
        guard=BodyDisplayGuard();self.assertTrue(guard.review(original(),capability(),10.01)['display_available'])
        self.assertFalse(guard.review(original(number=21,source=11.),capability(),11.01)['display_available'])
        self.assertFalse(guard.review(original(number=22,source=11.03),capability(),11.04)['display_available'])
        self.assertTrue(guard.review(original(number=23,source=11.06),capability(2,11.04),11.07)['display_available'])

    def test_original_withheld_is_not_rescued(self):
        value=original();value.update(distance_available=False,horizontal_camera_foot_range_m=None,reason='no_candidate')
        result=BodyDisplayGuard().review(value,capability(),10.01)
        self.assertFalse(result['display_available']);self.assertEqual(result['reason'],'no_candidate')

    def test_stale_review_and_support_mismatch_withhold(self):
        self.assertEqual(BodyDisplayGuard().review(original(),capability(),11.)['reason'],'display_body_review_stale')
        value=original();value['support_pixel']=[321,400]
        self.assertEqual(BodyDisplayGuard().review(value,capability(),10.01)['reason'],'display_body_support_mismatch')

    def test_scalar_validator_rejects_wrong_frame_rescue_changed_value_and_authority(self):
        value=original();result=BodyDisplayGuard().review(value,capability(),10.01)
        for changed in (dict(frame=21),dict(display_range_m=1.3),dict(usable_for_ffb=True),dict(reference_scope_verified=False)):
            with self.subTest(changed=changed),self.assertRaises(ValueError):checked_display_review(dict(result,**changed),value)
        value.update(distance_available=False,horizontal_camera_foot_range_m=None)
        with self.assertRaises(ValueError):checked_display_review(result,value)


class WorkerReferenceTests(unittest.TestCase):
    def setUp(self):
        self.case=asynchronous.AsyncComparisonTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_only_successful_pin_load_exports_copy_without_distance(self):
        worker=self.case.worker;self.assertIsNone(worker.display_reference_snapshot())
        self.case.load();cap=worker.display_reference_snapshot()
        self.assertEqual(cap['reference']['source_frame'],1);self.assertNotIn('comparison_range_m',cap)
        cap['reference']['boundary_xy'][0][1]=1
        self.assertEqual(worker.display_reference_snapshot()['reference']['boundary_xy'][0][1],458)

    def test_busy_stale_invalidate_and_close_remove_capability(self):
        self.case.load();worker=self.case.worker
        with worker.lock:self.assertIsNone(worker.display_reference_snapshot())
        self.case.now=11.;self.assertIsNone(worker.display_reference_snapshot())
        self.case.now=10.01;asynchronous.issue(worker.directory,'invalidate')
        asynchronous.wait(lambda:worker.info['state']=='invalidated')
        self.assertIsNone(worker.display_reference_snapshot());worker.close();self.assertIsNone(worker.display_reference_snapshot())

    def test_failed_load_removes_old_capability(self):
        self.case.load();worker=self.case.worker
        (worker.directory/'reference.json').write_text('{}')
        asynchronous.issue(worker.directory,'load');asynchronous.wait(lambda:worker.info['state']=='load_rejected')
        self.assertIsNone(worker.display_reference_snapshot())


class MemoryPipeTests(unittest.TestCase):
    def test_guarded_output_keeps_raw_log_and_raw_ipc_exact(self):
        class Engine:
            settings={'frame_max_age_sec':.5}
            def measure(self,frame,boxes,now):
                return dict(original(455),schema='cone_motion_range_v1',models=[])
        class Hook:
            def offer(self,*args):pass
            def display_reference_snapshot(self):return capability()
        frame=NativeFrame(SESSION,20,.1,10.,image())
        data=io.BytesIO();write_frame(data,frame)
        with tempfile.TemporaryDirectory() as directory:
            outputs=[];logs=[]
            for n,guard in enumerate((None,BodyDisplayGuard())):
                path=Path(directory)/str(n);path.mkdir();output=io.BytesIO()
                serve(Engine(),lambda f:[],io.BytesIO(data.getvalue()),output,path/'motion_distance_frames.jsonl',
                    clock=lambda:10.01,comparison=Hook(),display_guard=guard)
                output.seek(0);read_message(output);outputs.append(read_message(output))
                logs.append((path/'motion_distance_frames.jsonl').read_bytes())
            self.assertEqual(logs[0],logs[1]);self.assertEqual(outputs[0]['result'],outputs[1]['result'])
            self.assertNotIn('display_review',outputs[0]);self.assertFalse(outputs[1]['display_review']['display_available'])
            self.assertTrue(outputs[1]['result']['distance_available'])


class GuardedBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.bridge=DriverMotionBridge([sys.executable,'-c','pass'],Path(self.temp.name)/'guarded',
            clock=lambda:10.02,body_display_guard=True)
        self.addCleanup(self.bridge.close);self.bridge.begin(SESSION,dict(PROFILE))
        self.bridge.publish(SESSION,image(),.1,10.)
        self.bridge.result=original()

    def test_missing_or_mismatched_review_withholds_instead_of_raw_fallback(self):
        self.assertFalse(self.bridge.snapshot()['available'])
        review=BodyDisplayGuard().review(original(),capability(),10.01)
        self.bridge.display_review=dict(review,frame=21)
        self.assertFalse(self.bridge.snapshot()['available'])

    def test_current_clear_review_shows_original_and_occluded_review_hides_it(self):
        self.bridge.display_review=BodyDisplayGuard().review(original(),capability(),10.01)
        self.assertTrue(self.bridge.snapshot()['available']);self.assertIn('1.200 m',panel_text(self.bridge.snapshot()))
        self.bridge.result=original(455)
        self.bridge.display_review=BodyDisplayGuard().review(self.bridge.result,capability(),10.01)
        text=panel_text(self.bridge.snapshot());self.assertIn('WITHHELD',text);self.assertNotIn('1.200 m',text)

    def test_mode_requires_comparison_and_explicit_motion(self):
        parser=argparse.ArgumentParser();add_motion_arguments(parser)
        for args in (['--motion-body-display-guard'],['--motion-distance','--motion-body-display-guard']):
            with self.assertRaises(ValueError):bridge_from_args(parser.parse_args(args))


PIPE_CHILD=r'''
import sys,time
sys.path.insert(0,sys.argv[1]+'/src')
from driver_body_display_guard import BodyDisplayGuard,FLAGS
from driver_motion_protocol import compact_result,read_frame,write_message
from cone_self_body_shadow import compare_self_body
guard=BodyDisplayGuard()
while True:
 write_message(sys.stdout.buffer,dict(type='request'))
 try: frame=read_frame(sys.stdin.buffer)
 except EOFError: break
 y=455 if frame.image[0,0,0]==1 else 400
 original=dict(session=frame.session,frame=frame.sequence,source_time_sec=frame.received_at,
  distance_available=True,horizontal_camera_foot_range_m=1.2,reason='synthetic',primary_model='test',
  support_pixel=[320,y],support_observation=dict(point=[320,y],support=[[x,y] for x in range(312,329)],
   **{k:False for k in FLAGS}),**{k:False for k in FLAGS})
 ref=dict(schema='offline_self_body_boundary_v1',session=frame.session,source_frame=1,
  source_png_sha256='b'*64,image_size=[1280,720],layout='dual_fisheye_front_left_unremapped',
  boundary_xy=[[280,455],[360,455]],independent_physical_measurement=False,
  cross_session_mount_verified=False,live_authorized=False,floor_contact_verified=False)
 # Synthetic capability for IPC testing only. Production gets it from explicit pin/load.
 review=guard.review(original,dict(reference=ref,generation=1,activation_frame=1,activated_at=0.),time.monotonic())
 message=dict(type='result',result=compact_result(original))
 if sys.argv[2]!='omit':message['display_review']=review
 write_message(sys.stdout.buffer,message)
'''


class RealLocalPipeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def start(self,directory,mode='normal'):
        bridge=DriverMotionBridge([sys.executable,'-u','-c',PIPE_CHILD,str(ROOT),mode],directory,body_display_guard=True)
        self.addCleanup(bridge.close);bridge.begin(SESSION,dict(PROFILE));bridge.start()
        self.wait(lambda:bridge.ready.is_set() or bridge.error)
        self.assertIsNone(bridge.error);return bridge

    def wait(self,predicate):
        deadline=time.monotonic()+5
        while not predicate():
            if time.monotonic()>deadline:self.fail('local pipe timeout')
            time.sleep(.005)

    def feed(self,bridge,value):
        previous=bridge.returned;now=time.monotonic()
        self.assertTrue(bridge.publish(SESSION,image(value),now,now))
        self.wait(lambda:bridge.returned>previous or bridge.error)

    def test_real_ipc_withholds_body_then_recovers_without_changing_raw(self):
        bridge=self.start(self.root/'pipe')
        self.feed(bridge,1);self.feed(bridge,1)
        self.assertIsNone(bridge.error)
        self.assertTrue(bridge.result['distance_available']);self.assertFalse(bridge.snapshot()['available'])
        self.assertIn('possible_self_body_occlusion',panel_text(bridge.snapshot()))
        self.feed(bridge,2)
        self.assertIsNone(bridge.error);self.assertTrue(bridge.snapshot()['available'])
        self.assertIn('1.200 m',panel_text(bridge.snapshot()))
        summary=bridge.close();self.assertTrue(summary['shutdown_complete'])
        events=[json.loads(line) for line in (bridge.output_dir/'motion_bridge_events.jsonl').read_text().splitlines()]
        self.assertEqual(len(events),3)
        self.assertTrue(all(e['result']['horizontal_camera_foot_range_m']==1.2 for e in events))
        self.assertEqual([e['display_review']['display_available'] for e in events],[False,False,True])

    def test_guard_mode_rejects_old_worker_message_without_review(self):
        bridge=self.start(self.root/'missing','omit');self.feed(bridge,2)
        self.assertIsNotNone(bridge.error);self.assertFalse(bridge.snapshot()['available'])

    def test_cli_forwards_guard_and_default_still_off(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'recordings',prefix='body_guard_cli_') as directory:
            root=Path(directory)
            args=asynchronous.ComparisonCLIPathTests().args(root,root/'comparison')
            self.assertFalse(args.motion_body_display_guard);args.motion_body_display_guard=True
            bridge=bridge_from_args(args)
            try:
                self.assertIn('--body-display-guard',bridge.command);self.assertTrue(bridge.body_display_guard)
                self.assertIsNone(bridge.process);self.assertIsNone(bridge.thread.ident)
            finally:bridge.close()


if __name__=='__main__':unittest.main()
