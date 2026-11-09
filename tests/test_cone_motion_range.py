"""Motion evaluation is observational only: geometry, failures, opt-in and cleanup."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from angular_fisheye_geometry import project, unproject
from cone_distance_core import load_config
from cone_motion_range import FLAGS, PROFILE_SCHEMA, MotionRangeEngine, checked_current_support, horizontal_range, parse_motion_profile, revoke_range
from prepare_cone_motion_profile import prepare
from run_cone_motion_live import build_parser, render_motion, run, validate_options
from theta_rtc_frames import NativeFrame


def profile_fixture(settings):
    return dict(schema=PROFILE_SCHEMA, camera_sha256=settings["camera_sha256"], image_size=[1280,720],
        native_ray_basis="unmodified", metric="horizontal_camera_foot_range_m", primary_model="ippe_0",
        models=[dict(id="ippe_0", up_optical=[0.,-1.,0.], height_m=.59),
                dict(id="ippe_1", up_optical=[0.,-1.,0.], height_m=.6)],
        source=dict(image_sha256="0"*64, session="synthetic", frame=1),
        mount_or_floor_tilt_compensated=False, cross_session_mount_verified=False, **FLAGS)


def support_observation(x=320, y=400):
    return dict(point=[x,y], support=[[i,y] for i in range(x-8,x+9)],
                reason="synthetic_current_support", floor_contact_verified=False)


def cone_box():
    return dict(x1=290.,y1=300.,x2=350.,y2=440.,confidence=.95,class_id=0.)


class MotionRangeTests(unittest.TestCase):
    def setUp(self):
        self.settings,self.camera,_,_=load_config()
        self.profile=profile_fixture(self.settings)
        self.image=np.zeros((720,1280,3),np.uint8)
        self.observation=support_observation()
        self.engine=MotionRangeEngine(self.settings,self.camera,self.profile,"a"*64,
            acknowledged=True,observer=lambda *args:self.observation)

    def frame(self, sequence=1, source=10., session="motion"):
        return NativeFrame(session,sequence,source-10.,source,self.image)

    def test_height_normal_geometry_recovers_known_horizontal_range(self):
        ray=np.array([.2,.59,2.]);ray/=np.linalg.norm(ray)
        self.assertAlmostEqual(horizontal_range(ray,self.profile["models"][0]),np.hypot(.2,2.))

    def test_planar_vehicle_translation_and_yaw_need_no_world_pose_update(self):
        base_rotation=np.array([[0.,0.,1.],[-1.,0.,0.],[0.,-1.,0.]])
        target=np.array([2.,.2,0.])
        for x,y,yaw in ((0.,0.,0.),(.3,0.,.1),(.6,.1,-.1)):
            c,s=np.cos(yaw),np.sin(yaw)
            yaw_rotation=np.array([[c,-s,0.],[s,c,0.],[0.,0.,1.]])
            camera_world=np.array([x,y,.59])
            ray=(target-camera_world)@(yaw_rotation@base_rotation)
            ray/=np.linalg.norm(ray)
            self.assertAlmostEqual(horizontal_range(ray,self.profile["models"][0]),np.linalg.norm(target[:2]-camera_world[:2]))

    def test_simultaneous_optical_basis_reflection_does_not_change_scalar_range(self):
        ray=np.array([.2,.59,2.]);ray/=np.linalg.norm(ray)
        up=np.array([.02,-.999,0.01]);up/=np.linalg.norm(up)
        model=dict(height_m=.59,up_optical=up.tolist())
        mirror=np.diag([-1.,1.,1.])
        reflected=dict(model,up_optical=(mirror@up).tolist())
        self.assertAlmostEqual(horizontal_range(ray,model),horizontal_range(mirror@ray,reflected))

    def test_grazing_or_upward_ray_is_withheld(self):
        for ray in ([0.,0.,1.],[0.,-1.,0.]):
            self.assertIsNone(horizontal_range(ray,self.profile["models"][0]))

    def test_negative_height_is_not_absolutized(self):
        with self.assertRaises(ValueError):
            horizontal_range([0.,1.,0.],dict(height_m=-.59,up_optical=[0.,-1.,0.]))

    def test_nonunit_ray_is_refused(self):
        with self.assertRaises(ValueError):
            horizontal_range([0.,1.,1.],self.profile["models"][0])

    def test_explicit_opt_in_is_required(self):
        with self.assertRaises(ValueError):
            MotionRangeEngine(self.settings,self.camera,self.profile,"a"*64)

    def test_profile_cannot_claim_physical_approval_or_change_pixel_basis(self):
        for key,value in (("usable_for_ffb",True),("physical_metric_verified",True),
                          ("native_ray_basis","mirror_x"),("camera_sha256","x"*64)):
            bad=copy.deepcopy(self.profile);bad[key]=value
            with self.assertRaises(ValueError):
                parse_motion_profile(json.dumps(bad).encode(),self.settings)

    def test_profile_keeps_both_models_and_explicit_primary(self):
        parsed,_=parse_motion_profile(json.dumps(self.profile).encode(),self.settings)
        self.assertEqual(len(parsed["models"]),2)
        bad=dict(self.profile,primary_model="automatic_closest_range")
        with self.assertRaises(ValueError):
            parse_motion_profile(json.dumps(bad).encode(),self.settings)

    def test_profile_is_owned_copy_not_caller_mutable(self):
        self.profile["models"][0]["height_m"]=2.
        self.assertEqual(self.engine.profile["models"][0]["height_m"],.59)

    def test_current_support_requires_actual_observed_point(self):
        observation=support_observation();observation["point"]=[300,400]
        point,reason=checked_current_support(observation)
        self.assertIsNone(point)
        self.assertEqual(reason,"point_not_in_current_observed_support")

    def test_disconnected_or_unordered_columns_are_not_accepted(self):
        for support in ([[310,400],[312,400],[314,400],[316,400],[318,400],[320,400],[322,400],[324,400]],
                        [[i,400] for i in reversed(range(310,327))]):
            self.assertIsNone(checked_current_support(dict(point=[320,400],support=support))[0])

    def test_first_frame_and_large_motion_both_produce_current_frame_ranges(self):
        a=self.engine.measure(self.frame(),[cone_box()],10.01)
        self.observation=support_observation(330,430)
        b=self.engine.measure(self.frame(2,10.03),[cone_box()],10.04)
        self.assertTrue(a["distance_available"])
        self.assertTrue(b["distance_available"])
        self.assertNotEqual(a["horizontal_camera_foot_range_m"],b["horizontal_camera_foot_range_m"])
        self.assertFalse(b["static_scene_required"])

    def test_missing_current_support_does_not_hold_last_number(self):
        self.engine.measure(self.frame(),[cone_box()],10.01)
        self.observation=dict(point=None,support=None,reason="occluded")
        b=self.engine.measure(self.frame(2,10.03),[cone_box()],10.04)
        self.assertFalse(b["distance_available"])
        self.assertIsNone(b["horizontal_camera_foot_range_m"])
        self.assertEqual(b["models"],[])

    def test_stale_frame_is_withheld_without_observation_work(self):
        self.engine.observer=lambda *args: (_ for _ in ()).throw(AssertionError("stale work"))
        r=self.engine.measure(self.frame(),[cone_box()],10.501)
        self.assertEqual(r["reason"],"frame_processing_too_old")

    def test_multiple_cones_and_no_cone_are_withheld(self):
        for i,boxes in enumerate(([],[cone_box(),cone_box()]),1):
            r=self.engine.measure(self.frame(i,10.+i*.1),boxes,10.01+i*.1)
            self.assertFalse(r["distance_available"])

    def test_model_primary_failure_does_not_fall_back_to_alternative(self):
        self.engine.profile["models"][0]["up_optical"]=[0.,1.,0.]
        r=self.engine.measure(self.frame(),[cone_box()],10.01)
        self.assertFalse(r["distance_available"])
        self.assertTrue(r["models"][1]["range_available"])
        self.assertIsNone(r["horizontal_camera_foot_range_m"])

    def test_late_completion_revokes_all_model_numbers(self):
        r=self.engine.measure(self.frame(),[cone_box()],10.01)
        revoke_range(r,"late_completion")
        self.assertIsNone(r["horizontal_camera_foot_range_m"])
        self.assertTrue(all(m["horizontal_camera_foot_range_m"] is None for m in r["models"]))

    def test_backward_frame_or_time_is_refused(self):
        self.engine.measure(self.frame(),[cone_box()],10.01)
        with self.assertRaises(ValueError):
            self.engine.measure(self.frame(),[cone_box()],10.02)

    def test_new_session_resets_sequence_without_reusing_a_distance(self):
        self.engine.measure(self.frame(),[cone_box()],10.01)
        r=self.engine.measure(self.frame(1,10.1,"new"),[],10.11)
        self.assertEqual(r["session"],"new")
        self.assertFalse(r["distance_available"])

    def test_render_changes_only_display_copy_and_makes_no_image_file(self):
        r=self.engine.measure(self.frame(),[cone_box()],10.01)
        before=self.image.copy()
        display=render_motion(self.image,r)
        self.assertFalse(np.array_equal(display,self.image))
        np.testing.assert_array_equal(self.image,before)

    def test_cli_opt_in_failure_precedes_gpu_or_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            args=build_parser().parse_args(["--weights","missing.pt","--motion-profile","missing.json",
                                           "--output-dir",str(Path(directory)/"output")])
            with patch("run_cone_motion_live.YoloConePredictor",side_effect=AssertionError("GPU started")):
                with self.assertRaisesRegex(ValueError,"experimental-rigid-mount"):
                    asyncio.run(run(args))

    def test_all_outputs_remain_non_controlling_and_not_contact_verified(self):
        r=self.engine.measure(self.frame(),[cone_box()],10.01)
        for key in FLAGS:
            self.assertIs(r[key],False)
        self.assertFalse(r["mount_or_floor_tilt_compensated"])


class MotionReceiverCleanupTests(unittest.TestCase):
    def test_listener_failure_still_cleans_receiver_runner_and_worker_and_writes_summary(self):
        settings=load_config()[0]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);profile=root/"profile.json";output=root/"out"
            profile.write_text(json.dumps(profile_fixture(settings)))
            args=build_parser().parse_args(["--weights","unused.pt","--motion-profile",str(profile),
                "--output-dir",str(output),"--experimental-rigid-mount","--headless"])
            receiver=type("ReceiverMock",(),{})()
            async def offer(request):
                return None
            receiver.offer=offer;receiver.close=AsyncMock()
            runner=type("RunnerMock",(),{})()
            runner.setup=AsyncMock(side_effect=RuntimeError("synthetic listener failure"));runner.cleanup=AsyncMock()
            worker=type("WorkerMock",(),{})()
            worker.error=None;worker.processed=0;worker.available=0;worker.retired_results=0
            worker.close=lambda:dict(worker_stopped=True,shutdown_complete=True)
            predictor=type("PredictorMock",(),dict(gpu="synthetic",weights_sha256="0"*64))()
            def create_predictor(*args):
                output.mkdir()
                return predictor
            with patch("run_cone_motion_live.YoloConePredictor",side_effect=create_predictor), \
                 patch("run_cone_motion_live.Receiver",return_value=receiver), \
                 patch("run_cone_motion_live.MotionRangeWorker",return_value=worker), \
                 patch("aiohttp.web.AppRunner",return_value=runner):
                with self.assertRaisesRegex(RuntimeError,"listener failure"):
                    asyncio.run(run(args))
            receiver.close.assert_awaited_once();runner.cleanup.assert_awaited_once()
            summary=json.loads((output/"motion_live_summary.json").read_text())
            self.assertEqual(summary["runtime_status"],"RUN_FAILED")
            self.assertTrue(summary["shutdown"]["worker_stopped"])
            self.assertFalse(summary["robot_movement_started"])


class MotionProfilePreparationTests(unittest.TestCase):
    def setUp(self):
        self.spec = dict(schema="native_metric_rectangle_points_v1", image_sha256="1"*64,
            corner_order=["near_image_left", "near_image_right", "far_image_left", "far_image_right"],
            width_m=.8, depth_m=.8,
            corners_native_xy=[[254.69232545,413.57168429],[384.09211576,409.52236742],
                               [278.16675451,376.72819146],[357.71890795,374.70760240]])

    def prepare_spec(self, spec, primary=0):
        with tempfile.TemporaryDirectory() as directory:
            points=Path(directory)/"points.json"
            points.write_text(json.dumps(spec))
            before=points.read_bytes()
            # Only the PNG input/dimension check is replaced. The real native
            # ray model and IPPE geometry run on the explicit four points.
            with patch("prepare_cone_motion_profile.png_digest",return_value="1"*64):
                result=prepare(Path(directory)/"decoded_fixture_f000001.png",points,
                    ROOT/"src/cone_distance_diagnostic_config.json",primary)
            self.assertEqual(points.read_bytes(),before)
            return result

    def test_real_four_point_geometry_keeps_both_hypotheses_without_E(self):
        result=self.prepare_spec(self.spec)
        self.assertEqual(result["primary_model"],"ippe_0")
        self.assertEqual({m["id"] for m in result["models"]},{"ippe_0","ippe_1"})
        primary=result["models"][0]
        self.assertAlmostEqual(primary["height_m"],.57676727,places=6)
        self.assertFalse(result["source"]["E_used"])
        self.assertFalse(result["physical_metric_verified"])

    def test_nonpositive_nonfinite_or_boolean_rectangle_dimensions_fail(self):
        for value in (-.8,0.,float("nan"),True):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.prepare_spec(dict(self.spec,width_m=value))

    def test_wrong_image_hash_or_corner_order_fails(self):
        for changes in (dict(image_sha256="2"*64),dict(corner_order=list(reversed(self.spec["corner_order"])))):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.prepare_spec(dict(self.spec,**changes))

    def test_fifth_point_or_nonfinite_point_is_not_accepted(self):
        for points in (self.spec["corners_native_xy"]+[[320.,390.]],
                       [[float("nan"),400.]]*4):
            with self.subTest(points=points),self.assertRaises(ValueError):
                self.prepare_spec(dict(self.spec,corners_native_xy=points))

    def test_primary_solution_must_exist_no_automatic_fallback(self):
        with self.assertRaisesRegex(ValueError,"requested diagnostic solution"):
            self.prepare_spec(self.spec,primary=7)

    def test_rejected_geometry_is_not_repaired_with_absolute_height(self):
        fit=dict(candidates=[dict(solution_index=0,geometry_consistent=False)])
        with patch("prepare_cone_motion_profile.planar_floor_pose_candidates",return_value=fit):
            with self.assertRaisesRegex(ValueError,"no abs-height repair"):
                self.prepare_spec(self.spec)


if __name__ == "__main__":
    unittest.main()
