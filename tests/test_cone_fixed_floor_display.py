"""GUI semantics and fake entrypoint only. No real camera/window/GPU/network."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import ConeDistanceEngine, load_config, render_distance
from cone_fixed_floor_candidate import COORDINATE_FRAME, SCHEMA
from cone_fixed_floor_display import append_comparison_panel, comparison_view_model, panel_lines
from summarize_cone_distance_live import validate_row
from theta_rtc_frames import NativeFrame


class FixedFloorDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(cls.image, [np.array([[320,310],[295,400],[345,400]], np.int32)], (0,0,255))
        settings = load_config()[0]
        heading = dict(path=settings["floor_candidate"], sha256=settings["floor_sha256"])
        models = [dict(schema=SCHEMA, name=f"synthetic_model_{n:02d}", session="synthetic_gui",
            normal_optical=[0.,-1.,0.], camera_to_floor_m=.5+n*.02, coordinate_frame=COORDINATE_FRAME,
            heading_reference=heading, evidence=["synthetic display-only fixture; not physical data"],
            assumptions=["synthetic plane, not independently measured"], invalidation_conditions=["not for live/physical use"],
            physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False) for n in range(6)]
        cls.models = cls.folder/"synthetic_models.json"
        cls.models.write_text(json.dumps(dict(schema="explicit_floor_models_v1", session="synthetic_gui",
                                             heading_reference=heading, models=models)))
        engine = ConeDistanceEngine(support_completion_shadow=True, frame_evidence=True, fixed_floor_models=cls.models)
        engine.reset("synthetic_gui")
        box = dict(x1=290.,y1=305.,x2=350.,y2=405.,confidence=.95,class_id=0)
        cls.rows=[]
        for n in (4,5,6):
            t=10.+n/30
            row=engine.measure(NativeFrame("synthetic_gui",n,t,t,cls.image),[box],t+.01)
            row.update(predict_ms=0.,support_geometry_ms=10.,cone_service_ms=10.,inference_source="SYNTHETIC_GUI_TEST")
            cls.rows.append(row)
        cls.startup=copy.deepcopy(cls.rows[-1])
        cls.row=copy.deepcopy(cls.startup)
        cls.row["fixed_floor_load"]=dict(schema="fixed_floor_load_v1",state="active",reason="accepted_comparison_only",
            generation=1,requested_session="synthetic_gui",bundle_sha256=cls.row["fixed_floor_shadow"]["model_bundle_sha256"],
            evidence_frames=[1],activated_frame=4,load_completed_at_sec=10.1,activated_at_sec=cls.rows[0]["source_time_sec"],
            controlling_distance=False,physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)
        cls.state=copy.deepcopy(cls.row["fixed_floor_load"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def view(self, row=None, **kwargs):
        options=dict(model_state=copy.deepcopy(self.state),now=self.row["completed_time_sec"],
            expected_session="synthetic_gui",expected_frame=6,expected_source_time=self.row["source_time_sec"])
        options.update(kwargs)
        return comparison_view_model(copy.deepcopy(self.row) if row is None else row,**options)

    def test_unverified_span_preserves_all_models_not_best(self):
        view=self.view()
        self.assertEqual(view["status"],"UNVERIFIED_COMPARISON")
        values=[m["horizontal_camera_foot_range_m"] for m in self.row["fixed_floor_shadow"]["models"]]
        self.assertEqual(view["range_span_m"],[min(values),max(values)])
        self.assertEqual(view["available_model_count"],6)
        self.assertEqual([m["name"] for m in view["models"]],[m["model_name"] for m in self.row["fixed_floor_shadow"]["models"]])
        lines="\n".join(panel_lines(view))
        for label in ("UNVERIFIED COMPARISON ONLY","NOT forward/base_link/contact","NOT ranking","2 more models not shown","NOT accuracy"):
            self.assertIn(label,lines)
        self.assertFalse(self.row["distance_available"])

    def test_panel_does_not_edit_source_result_or_existing_base_display(self):
        raw=self.image.copy()
        result=copy.deepcopy(self.row)
        base=render_distance(raw,result)
        before=base.copy()
        view=append_comparison_panel(base,result,model_state=self.state,now=result["completed_time_sec"])
        self.assertEqual(view.shape,(980,1280,3))
        np.testing.assert_array_equal(raw,self.image)
        np.testing.assert_array_equal(base,before)
        np.testing.assert_array_equal(view[:720],before)
        self.assertEqual(result,self.row)
        self.assertFalse(np.shares_memory(view,base))

    def test_live_engine_explicit_roi_matches_serialized_gui_without_mutation(self):
        engine = ConeDistanceEngine(target_roi=(270,0,350,720),
            support_completion_shadow=True, frame_evidence=True, fixed_floor_models=self.models)
        engine.reset("synthetic_gui")
        box = dict(x1=290.,y1=305.,x2=350.,y2=405.,confidence=.95,class_id=0)
        for n in (4,5,6):
            t=10.+n/30
            row=engine.measure(NativeFrame("synthetic_gui",n,t,t,self.image),[box],t+.01)
            row.update(predict_ms=0.,support_geometry_ms=10.,cone_service_ms=10.,
                inference_source="SYNTHETIC_GUI_TEST")
        row["fixed_floor_load"]=copy.deepcopy(self.state)
        before=copy.deepcopy(row)
        self.assertIsInstance(row["target_roi_native_xyxy"],tuple)
        persisted=json.loads(json.dumps(row))
        validate_row(persisted)
        live=self.view(row)
        recorded=self.view(persisted)
        self.assertEqual(live["status"],"UNVERIFIED_COMPARISON")
        self.assertEqual(live,recorded)
        self.assertEqual(live["available_model_count"],6)
        np.testing.assert_array_equal(
            append_comparison_panel(self.image,row,model_state=self.state,now=row["completed_time_sec"]),
            append_comparison_panel(self.image,persisted,model_state=self.state,now=row["completed_time_sec"]))
        self.assertEqual(row,before)
        self.assertIsInstance(row["target_roi_native_xyxy"],tuple)

    def test_invalid_tuple_roi_is_still_withheld(self):
        for roi in ((270,0,350), (350,0,270,720), (270,0,641,720),
                    (True,0,350,720), (270.,0,350,720)):
            row=copy.deepcopy(self.row)
            row["target_roi_native_xyxy"]=roi
            with self.subTest(roi=roi):
                view=self.view(row)
                self.assertEqual(view["reason"],"invalid_comparison_result")
                self.assertIsNone(view["range_span_m"])

    def test_persisted_row_validator_stays_strict_about_tuple_roi(self):
        row=copy.deepcopy(self.row)
        row["target_roi_native_xyxy"]=(270,0,350,720)
        with self.assertRaisesRegex(ValueError,"native front-lens target ROI required"):
            validate_row(row)

    def test_live_tuple_roi_does_not_bypass_existing_validation(self):
        variants=[]
        row=copy.deepcopy(self.row)
        row["fixed_floor_shadow"]["usable_for_ffb"]=True
        variants.append(row)
        row=copy.deepcopy(self.row)
        row["fixed_floor_shadow"]["models"][0]["horizontal_camera_foot_range_m"]=float("nan")
        variants.append(row)
        row=copy.deepcopy(self.row)
        row["fixed_floor_shadow"]["support_pixel"]=[0,0]
        variants.append(row)
        for row in variants:
            row["target_roi_native_xyxy"]=(270,0,350,720)
            self.assertEqual(self.view(row)["reason"],"invalid_comparison_result")
        row=copy.deepcopy(self.row)
        row["target_roi_native_xyxy"]=(270,0,350,720)
        self.assertEqual(self.view(row,now=row["source_time_sec"]+.501)["reason"],"display_result_stale")
        self.assertEqual(self.view(row,model_state=dict(self.state,generation=2))["reason"],"awaiting_current_model_result")

    def test_startup_bundle_and_recorded_modes_explicit(self):
        self.assertIsNotNone(self.view(self.startup,model_state=None)["range_span_m"])
        self.assertIsNone(self.view(model_state=None)["range_span_m"])
        self.assertIsNotNone(self.view(model_state=None,mode="recorded")["range_span_m"])
        self.assertIn("RECORDED RECOMPUTATION",panel_lines(self.view(mode="recorded"))[0])
        self.assertIn("SYNTHETIC PREVIEW",panel_lines(self.view(mode="synthetic"))[0])

    def test_recorded_view_uses_logged_state_without_claiming_live_ownership(self):
        view=self.view(model_state=None,mode="recorded")
        self.assertEqual(view["loader_state"],"active")
        self.assertEqual(view["generation"],1)
        row=copy.deepcopy(self.row)
        row.pop("fixed_floor_shadow")
        row["fixed_floor_load"].update(state="rejected",reason="historical_disconnect")
        self.assertIsNone(self.view(row,model_state=None,mode="recorded")["range_span_m"])

    def test_generation_hash_and_session_must_match_current_loader(self):
        for key,value in (("generation",2),("bundle_sha256","0"*64),("requested_session","new_session")):
            state=copy.deepcopy(self.state)
            state[key]=value
            with self.subTest(key=key):
                self.assertIsNone(self.view(model_state=state)["range_span_m"])

    def test_waiting_loading_rejected_and_closed_never_show_last_value(self):
        self.assertIsNotNone(self.view()["range_span_m"])
        for status in ("waiting","loading","ready","rejected","closed"):
            state=dict(self.state,state=status,reason="new_request_or_disconnect")
            with self.subTest(status=status):
                view=self.view(model_state=state)
                self.assertIsNone(view["range_span_m"])
                self.assertEqual(view["models"],[])

    def test_missing_result_and_idle_active_state_do_not_use_cache(self):
        self.view()
        view=comparison_view_model(None,model_state=self.state,unavailable_reason="waiting_for_new_frame")
        self.assertIsNone(view["range_span_m"])
        self.assertEqual(view["reason"],"waiting_for_new_frame")

    def test_display_wall_age_over_500_ms_hides_previously_fresh_row(self):
        self.assertIsNone(self.view(now=self.row["source_time_sec"]+.501)["range_span_m"])
        self.assertIsNone(self.view(now=self.row["source_time_sec"]-.01)["range_span_m"])
        self.assertIsNone(self.view(now=float("nan"))["range_span_m"])

    def test_live_image_identity_and_timestamp_must_match(self):
        for options in (dict(expected_session="new"),dict(expected_frame=7),dict(expected_source_time=11.)):
            with self.subTest(options=options):
                self.assertIsNone(self.view(**options)["range_span_m"])

    def test_malformed_range_authority_and_point_refused(self):
        variants=[]
        for value in (float("nan"),float("inf"),True,-1.,10.):
            row=copy.deepcopy(self.row)
            row["fixed_floor_shadow"]["models"][0]["horizontal_camera_foot_range_m"]=value
            variants.append(row)
        row=copy.deepcopy(self.row)
        row["fixed_floor_shadow"]["usable_for_ffb"]=True
        variants.append(row)
        row=copy.deepcopy(self.row)
        row["fixed_floor_shadow"]["support_pixel"]=[0,0]
        variants.append(row)
        for row in variants:
            with self.subTest(row=row["fixed_floor_shadow"]):
                self.assertIsNone(self.view(row)["range_span_m"])

    def test_unsupported_shadow_not_treated_as_baseline_distance(self):
        row=copy.deepcopy(self.row)
        row.pop("fixed_floor_shadow")
        row.pop("fixed_floor_load")
        row["distance_available"]=True
        row["distance_forward_m"]=1.
        self.assertIsNone(self.view(row,model_state=None)["range_span_m"])

    def test_unconfirmed_support_shows_withheld_not_previous_numbers(self):
        row=copy.deepcopy(self.rows[0])
        view=comparison_view_model(row,mode="synthetic")
        self.assertIsNone(view["range_span_m"])
        self.assertTrue(all(m["value_m"] is None for m in view["models"]))

    def test_unknown_mode_refused(self):
        with self.assertRaises(ValueError):
            self.view(mode="physical_approved")

    def test_malformed_loader_snapshot_withheld_without_crash(self):
        self.assertIsNone(self.view(model_state=[])["range_span_m"])

    def test_control_characters_cannot_insert_extra_panel_lines(self):
        view=self.view()
        view["models"][0]["name"]="name\nFORGED APPROVAL\x00"
        lines=panel_lines(view)
        self.assertEqual(len(lines),10)
        self.assertTrue(all("\n" not in line and "\x00" not in line for line in lines))

    def exercise_gui(self, enabled):
        import run_cone_distance_live as live
        displays,saved=[],[]
        row=copy.deepcopy(self.startup)
        frame=NativeFrame("synthetic_gui",6,row["source_time_sec"],row["source_time_sec"],self.image)
        class Predictor:
            def __init__(self,weights,settings,output,device):
                output.mkdir()
                self.gpu={"synthetic":True}
                self.weights_sha256="synthetic"
        class Receiver:
            def __init__(self,*args):pass
            async def offer(self,*args):raise AssertionError("no network")
            async def close(self):pass
        class Worker:
            error=None
            def __init__(self,*a,**kw):self.engine=SimpleNamespace(target_roi=None)
            def start(self):pass
            def poll(self,*args):return (frame,row),"synthetic"
            def close(self):return dict(worker_stopped=True,scene_job_running=False,shutdown_complete=True)
        class Runner:
            def __init__(self,*a,**kw):pass
            async def setup(self):pass
            async def cleanup(self):pass
        class Site:
            def __init__(self,*a,**kw):pass
            async def start(self):pass
        async def inline(function,*args):return function(*args)
        with tempfile.TemporaryDirectory() as directory:
            argv=["--weights","unused.pt","--output-dir",str(Path(directory)/"out")]
            if enabled:
                argv += ["--fixed-floor-models",str(self.models),"--support-completion-shadow"]
            args=live.build_parser().parse_args(argv)
            with patch.object(live,"YoloConePredictor",Predictor),patch.object(live,"Receiver",Receiver), \
                 patch.object(live,"DistanceWorker",Worker),patch("aiohttp.web.AppRunner",Runner), \
                 patch("aiohttp.web.TCPSite",Site),patch.object(live.cv2,"imshow",side_effect=lambda name,image:displays.append(image.copy())), \
                 patch.object(live.cv2,"waitKey",side_effect=[ord("S"),ord("Q")]),patch.object(live.cv2,"destroyAllWindows"), \
                 patch.object(live.asyncio,"to_thread",inline),patch.object(live,"save_decoded_frame",side_effect=lambda folder,frame:saved.append(frame)):
                asyncio.run(live.run(args))
        self.assertEqual(len(displays),2)
        self.assertEqual(displays[0].shape,(980 if enabled else 720,1280,3))
        self.assertEqual(len(saved),1)
        self.assertIs(saved[0],frame)
        np.testing.assert_array_equal(saved[0].image,self.image)

    def test_gui_enabled_appends_panel_and_s_saves_raw_frame(self):
        self.exercise_gui(True)

    def test_gui_default_off_preserves_existing_dimensions_and_raw_s(self):
        self.exercise_gui(False)


if __name__ == "__main__":
    unittest.main()
