"""Real local pipe processes, synthetic pixels/predictor only. NO ROS/network/GPU."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from driver_motion_bridge import DriverMotionBridge, add_motion_arguments, bridge_from_args, panel_text
from driver_motion_protocol import (IMAGE_BYTES,MAX_MESSAGE,PROFILE,PREFIX,checked_result,
    compact_result,profile_matches,read_frame,read_message,write_frame,write_message)
from theta_rtc_frames import NativeFrame

SESSION_A="a"*32
SESSION_B="b"*32


def image(value=1):
    result=np.full((720,1280,3),value,np.uint8);result.flags.writeable=False
    return result


def valid_result(frame):
    return dict(session=frame.session,frame=frame.sequence,source_time_sec=frame.received_at,
        distance_available=True,horizontal_camera_foot_range_m=1.2,reason="synthetic_current_support",
        primary_model="synthetic",physical_metric_verified=False,floor_contact_verified=False,
        controlling_distance=False,usable_for_ffb=False,published_to_ros=False)


FAKE_CHILD = r'''
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]+"/src")
from cone_distance_core import load_config
from cone_motion_range import MotionRangeEngine,load_motion_profile
from driver_motion_process import serve
settings,camera,_,_=load_config()
profile,sha=load_motion_profile(Path(sys.argv[1])/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json",settings)
def observe(image,*args):
 y=400+int(image[0,0,0])
 return dict(point=[320,y],support=[[x,y] for x in range(312,329)],reason="synthetic_support")
engine=MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,observer=observe)
def predict(frame):
 if sys.argv[3]=="crash":raise RuntimeError("synthetic model crash")
 if sys.argv[3]=="slow":time.sleep(.15)
 if sys.argv[3]=="hang":time.sleep(30)
 return [dict(x1=290.,y1=300.,x2=350.,y2=440.,confidence=.95,class_id=0.)]
serve(engine,predict,sys.stdin.buffer,sys.stdout.buffer,Path(sys.argv[2])/"synthetic_measurements.jsonl")
'''


class MotionPipeProtocolTests(unittest.TestCase):
    def setUp(self):
        self.frame=NativeFrame(SESSION_A,7,.3,10.,image())

    def test_profile_matches_exact_types_and_fields(self):
        self.assertTrue(profile_matches(dict(PROFILE)))
        for value in (None,{},dict(PROFILE,width=1920),dict(PROFILE,new_capture_only=1),dict(PROFILE,extra=True)):
            self.assertFalse(profile_matches(value))

    def test_native_pixels_and_source_identity_roundtrip_without_mutation(self):
        stream=io.BytesIO();write_frame(stream,self.frame);stream.seek(0)
        actual=read_frame(stream)
        self.assertEqual((actual.session,actual.sequence,actual.received_at),(SESSION_A,7,10.))
        np.testing.assert_array_equal(actual.image,self.frame.image)
        self.assertFalse(actual.image.flags.writeable)

    def test_partial_reads_are_reassembled_not_assumed_atomic(self):
        stream=io.BytesIO();write_frame(stream,self.frame);stream.seek(0)
        class PartialReader:
            def readline(self,n):return stream.readline(n)
            def read(self,n):return stream.read(min(n,12345))
        np.testing.assert_array_equal(read_frame(PartialReader()).image,self.frame.image)

    def test_truncated_native_pixels_are_rejected(self):
        stream=io.BytesIO();write_frame(stream,self.frame)
        with self.assertRaises(EOFError):read_frame(io.BytesIO(stream.getvalue()[:-1]))

    def test_oversize_frame_header_and_invalid_session_are_rejected_before_pixels(self):
        header=dict(type="frame",session=SESSION_A,sequence=1,media_time=.1,received_at=10.,bytes=IMAGE_BYTES)
        for changes in (dict(bytes=IMAGE_BYTES*2),dict(sequence=True),dict(session="../../etc"),dict(media_time=True)):
            stream=io.BytesIO();write_message(stream,dict(header,**changes));stream.seek(0)
            with self.assertRaises(ValueError):read_frame(stream)

    def test_protocol_rejects_noise_oversize_nonfinite_and_nonobjects(self):
        for value in (b"torch startup noise\n",PREFIX+b"[]\n",PREFIX+b'{"n":NaN}\n',b"x"*(MAX_MESSAGE+1)):
            with self.assertRaises(ValueError):read_message(io.BytesIO(value))

    def test_result_must_match_input_and_cannot_grant_control_permission(self):
        result=valid_result(self.frame)
        self.assertEqual(checked_result(result,self.frame),result)
        for changes in (dict(frame=8),dict(session=SESSION_B),dict(source_time_sec=11.),dict(usable_for_ffb=True),
                        dict(horizontal_camera_foot_range_m=float("inf")),dict(distance_available=False)):
            with self.assertRaises(ValueError):checked_result(dict(result,**changes),self.frame)

    def test_compact_result_excludes_images_and_support_arrays(self):
        result=dict(valid_result(self.frame),support_pixel=[320,400],support_observation=dict(support=[[1,2]]))
        self.assertEqual(compact_result(result),valid_result(self.frame))


class DriverTapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/"tap"
        self.bridge=DriverMotionBridge([sys.executable,"-c","pass"],self.output,clock=lambda:10.)
        self.addCleanup(self.bridge.close)
        self.bridge.begin(SESSION_A,dict(PROFILE))

    def publish(self,pixels=None,media=.1,received=10.):
        return self.bridge.publish(SESSION_A,image() if pixels is None else pixels,media,received)

    def test_tap_borrows_owned_readonly_original_not_remapped_or_resized(self):
        pixels=image();self.assertTrue(self.publish(pixels))
        self.assertIs(self.bridge.latest.image,pixels)
        self.assertFalse(pixels.flags.writeable)

    def test_publish_never_waits_for_pipe_or_busy_tap_lock(self):
        with self.bridge.lock:
            self.assertFalse(self.publish())
        self.assertEqual(self.bridge.dropped,1)
        self.assertIsNone(self.bridge.latest)

    def test_wrong_dimension_or_mutable_buffer_latches_distance_only_invalid(self):
        for pixels in (np.zeros((960,1920,3),np.uint8),np.zeros((720,1280,3),np.uint8)):
            bridge=DriverMotionBridge([sys.executable,"-c","pass"],Path(self.temp.name)/str(pixels.shape))
            self.addCleanup(bridge.close);bridge.begin(SESSION_A,dict(PROFILE))
            self.assertFalse(bridge.publish(SESSION_A,pixels,.1,10.))
            self.assertFalse(bridge.valid_source)
            self.assertIsNone(bridge.latest)

    def test_legacy_offer_acceptance_is_not_range_approval(self):
        self.bridge.begin(SESSION_B,None)
        self.assertFalse(self.bridge.valid_source)
        self.assertIn("profile",self.bridge.snapshot()["reason"])

    def test_duplicate_time_future_time_or_nan_clears_current_range(self):
        self.publish()
        self.bridge.result=valid_result(self.bridge.latest)
        self.assertFalse(self.publish(media=.1))
        self.assertFalse(self.bridge.snapshot()["available"])
        for now in (11.,float("nan")):
            self.bridge.begin(os.urandom(16).hex(),dict(PROFILE))
            self.assertFalse(self.bridge.publish(self.bridge.session,image(),.1,now))

    def test_stale_range_is_not_displayed_over_newer_frame(self):
        self.publish();self.bridge.result=valid_result(self.bridge.latest)
        self.assertTrue(self.bridge.snapshot(10.1)["available"])
        self.assertFalse(self.bridge.snapshot(10.501)["available"])
        self.assertNotIn("1.200",panel_text(self.bridge.snapshot(10.501)))

    def test_old_disconnect_does_not_invalidate_new_peer(self):
        self.publish();self.bridge.result=valid_result(self.bridge.latest)
        self.bridge.begin(SESSION_B,dict(PROFILE));self.bridge.end(SESSION_A)
        self.assertTrue(self.bridge.valid_source)
        self.assertFalse(self.bridge.snapshot()["available"])
        with self.assertRaises(ValueError):self.bridge.begin(SESSION_A,dict(PROFILE))

    def test_stop_clears_numbers_and_cannot_restart(self):
        self.publish();self.bridge.result=valid_result(self.bridge.latest)
        self.bridge.request_stop()
        self.assertFalse(self.bridge.snapshot()["available"])
        with self.assertRaises(RuntimeError):self.bridge.start()

    def test_panel_is_separate_source_labeled_and_non_controlling(self):
        self.publish();self.bridge.result=valid_result(self.bridge.latest)
        text=panel_text(self.bridge.snapshot())
        self.assertIn("1.200 m",text);self.assertIn("frame 1",text)
        self.assertIn("NOT used for control/FFB",text)


class DriverSubprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.bridge=None

    def start(self,mode="normal"):
        output=Path(self.temp.name)/"worker"
        command=[sys.executable,"-u","-c",FAKE_CHILD,str(ROOT),str(output),mode]
        self.bridge=DriverMotionBridge(command,output)
        self.addCleanup(self.bridge.close);self.bridge.start()
        self.assertTrue(self.bridge.ready.wait(5.),str(self.bridge.error))
        self.bridge.begin(SESSION_A,dict(PROFILE))
        return self.bridge

    def wait_for(self,predicate):
        deadline=time.monotonic()+4.
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.005)
        self.fail("bounded IPC wait: "+str(self.bridge.error))

    def publish(self,n=1,session=SESSION_A):
        self.assertTrue(self.bridge.publish(session,image(n),n/30.,time.monotonic()))

    def test_real_pipe_measurement_and_metadata_logs_without_images(self):
        bridge=self.start();pixels=image(3);before=pixels.copy()
        self.assertTrue(bridge.publish(SESSION_A,pixels,.1,time.monotonic()))
        self.wait_for(lambda:bridge.returned==1)
        self.assertTrue(bridge.snapshot()["available"])
        np.testing.assert_array_equal(pixels,before)
        result=json.loads((bridge.output_dir/"synthetic_measurements.jsonl").read_text().splitlines()[0])
        self.assertEqual(result["support_pixel"],[320,403])
        self.assertIn("injected_predictor",result["inference_source"])
        self.assertFalse(list(bridge.output_dir.glob("*.png")))

    def test_slow_inference_skips_intermediate_inputs_without_blocking_publisher(self):
        bridge=self.start("slow");self.publish();self.wait_for(lambda:bridge.sent==1)
        for n in (2,3,4):self.publish(n)
        self.wait_for(lambda:bridge.returned>=2)
        rows=[json.loads(line) for line in (bridge.output_dir/"synthetic_measurements.jsonl").read_text().splitlines()]
        self.assertEqual([r["frame"] for r in rows],[1,4])

    def test_reconnect_during_inference_drops_retired_peer_result(self):
        bridge=self.start("slow");self.publish();self.wait_for(lambda:bridge.sent==1)
        bridge.begin(SESSION_B,dict(PROFILE));self.publish(2,SESSION_B)
        self.wait_for(lambda:bridge.returned>=2)
        self.assertGreaterEqual(bridge.retired,1)
        self.assertEqual(bridge.snapshot()["result"]["session"],SESSION_B)

    def test_child_model_crash_becomes_distance_failure_only(self):
        bridge=self.start("crash");self.publish();self.wait_for(lambda:bridge.error is not None)
        self.assertFalse(bridge.snapshot()["available"])
        self.assertTrue(bridge.publish(SESSION_A,image(2),.2,time.monotonic()))
        self.assertTrue(bridge.close()["child_stopped"])

    def test_blocked_native_inference_is_terminated_without_waiting_in_publish(self):
        bridge=self.start("hang");self.publish();self.wait_for(lambda:bridge.sent==1)
        self.publish(2)
        status=bridge.close()
        self.assertTrue(status["child_stopped"]);self.assertTrue(status["io_thread_stopped"])
        self.assertFalse(bridge.snapshot()["available"])

    def test_child_stdout_noise_is_not_parsed_as_a_distance(self):
        output=Path(self.temp.name)/"noise"
        bridge=DriverMotionBridge([sys.executable,"-c","print('not IPC')"],output)
        self.bridge=bridge;self.addCleanup(bridge.close);bridge.start()
        self.wait_for(lambda:bridge.error is not None)
        self.assertFalse(bridge.snapshot()["available"])

    def test_child_exit_after_request_is_detected_without_any_camera_frame(self):
        output=Path(self.temp.name)/"early_exit"
        code="import sys;sys.path.insert(0,sys.argv[1]+'/src');from driver_motion_protocol import write_message;write_message(sys.stdout.buffer,dict(type='request'))"
        bridge=DriverMotionBridge([sys.executable,"-c",code,str(ROOT)],output)
        self.bridge=bridge;self.addCleanup(bridge.close);bridge.start()
        self.wait_for(lambda:bridge.error is not None)
        self.assertFalse(bridge.snapshot()["available"])


class DriverMotionCLITests(unittest.TestCase):
    def parser(self):
        parser=argparse.ArgumentParser()
        parser.set_defaults(cam_width=1280,cam_height=720,front_lens="left",mock_camera=False)
        add_motion_arguments(parser);return parser

    def test_default_has_no_output_process_or_model_dependency(self):
        self.assertIsNone(bridge_from_args(self.parser().parse_args([])))

    def test_opt_in_requires_explicit_mount_ack_before_process(self):
        with self.assertRaisesRegex(ValueError,"rigid-mount"):
            bridge_from_args(self.parser().parse_args(["--motion-distance"]))

    def test_existing_driver_geometry_cannot_be_silently_scaled(self):
        args=self.parser().parse_args(["--motion-distance","--motion-experimental-rigid-mount"])
        args.cam_width=1920;args.cam_height=960
        with self.assertRaisesRegex(ValueError,"no resizing"):
            bridge_from_args(args)

    def test_valid_command_keeps_explicit_python_path_and_starts_no_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);python=root/"venv_python";python.symlink_to(sys.executable)
            weights=root/"synthetic.pt";weights.write_bytes(b"test fixture, not a model")
            profile=ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json"
            args=self.parser().parse_args(["--motion-distance","--motion-experimental-rigid-mount",
                "--motion-python",str(python),"--motion-weights",str(weights),"--motion-profile",str(profile),
                "--motion-output-dir",str(root/"new_output")])
            bridge=bridge_from_args(args)
            try:
                self.assertEqual(bridge.command[0],str(python))
                self.assertIsNone(bridge.process);self.assertIsNone(bridge.thread.ident)
                self.assertIn("--experimental-rigid-mount",bridge.command)
            finally:bridge.close()


if __name__ == "__main__":unittest.main()
