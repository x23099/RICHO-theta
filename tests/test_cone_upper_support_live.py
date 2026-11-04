"""Opt-in independent logging, evidence and model lifecycle; synthetic only."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG,ConeDistanceEngine,digest,load_config
from cone_distance_worker import DistanceWorker
from cone_fixed_floor_candidate import SCHEMA,COORDINATE_FRAME
from cone_upper_support_live import UpperSupportLiveComparison,summarize,validate_record
from run_cone_distance_live import build_parser
from theta_rtc_frames import LatestNativeFrame,NativeFrame

BOX=dict(x1=290.,y1=305.,x2=350.,y2=405.,confidence=.95,class_id=0)


class UpperLiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.settings=load_config()[0]
        heading=dict(path=self.settings["floor_candidate"],sha256=self.settings["floor_sha256"])
        m=dict(schema=SCHEMA,name="synthetic_upper",session="upper_test",normal_optical=[0.,-1.,0.],
            camera_to_floor_m=.5,coordinate_frame=COORDINATE_FRAME,heading_reference=heading,
            evidence=["synthetic, not physical"],assumptions=["synthetic plane"],invalidation_conditions=["not approved"],
            physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)
        self.model=self.folder/"model.json"
        self.model.write_text(json.dumps(dict(schema="explicit_floor_models_v1",session="upper_test",heading_reference=heading,models=[m])))
        self.image=np.zeros((720,1280,3),np.uint8)
        cv2.fillPoly(self.image,[np.array([[320,300],[295,400],[345,400]],np.int32)],(0,0,255))
        self.engine=ConeDistanceEngine(support_completion_shadow=True,frame_evidence=True,fixed_floor_models=self.model)
        self.engine.reset("upper_test")
        self.upper=UpperSupportLiveComparison(self.settings,digest(DEFAULT_CONFIG),self.folder)

    def frame(self,n=1,t=None,session="upper_test",image=None):
        t=10+n/30 if t is None else t
        return NativeFrame(session,n,t,t,self.image if image is None else image)

    def observe(self,n=1,*,load=None,t=None,boxes=None):
        frame=self.frame(n,t=t)
        base=self.engine.measure(frame,[BOX] if boxes is None else boxes,frame.received_at+.01)
        if load is not None:base["fixed_floor_load"]=load
        record=self.upper.observe(frame,base,self.engine.fixed_floor_shadow,self.engine.camera,self.engine.transform)
        self.upper.finish(record,frame.received_at+.02,baseline=base)
        return frame,base,record

    def active(self,generation=1):
        return dict(schema="fixed_floor_load_v1",state="active",reason="accepted_comparison_only",generation=generation,
            requested_session="upper_test",bundle_sha256=self.engine.fixed_floor_shadow.bundle_sha256,
            evidence_frames=[1],activated_frame=2,load_completed_at_sec=10.,activated_at_sec=10.01,
            controlling_distance=False,physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)

    def test_default_parser_and_worker_do_not_create_upper_files(self):
        args=build_parser().parse_args(["--weights","unused","--output-dir","unused"])
        self.assertFalse(args.upper_support_shadow)
        slot=LatestNativeFrame()
        worker=DistanceWorker(slot,DEFAULT_CONFIG,lambda f:[],self.folder/"frames.jsonl")
        self.addCleanup(worker.close)
        self.assertIsNone(worker.upper_comparison)
        self.assertFalse((self.folder/"upper_support_comparison.jsonl").exists())
        self.assertFalse((self.folder/"upper_support_evidence").exists())

    def test_missing_required_flags_rejected_before_gpu(self):
        import run_cone_distance_live as live
        args=build_parser().parse_args(["--weights","unused","--output-dir",str(self.folder/"out"),"--upper-support-shadow"])
        with patch.object(live,"YoloConePredictor",side_effect=AssertionError("GPU must not start")):
            with self.assertRaisesRegex(ValueError,"requires completion"):
                asyncio.run(live.run(args))
        with self.assertRaises(ValueError):
            DistanceWorker(LatestNativeFrame(),DEFAULT_CONFIG,lambda f:[],self.folder/"x",upper_support_shadow=True)

    def test_separate_candidate_waits_three_frames_and_does_not_change_legacy(self):
        output=[self.observe(n) for n in (1,2,3)]
        self.assertEqual([r[2]["status"] for r in output],["WITHHELD","WITHHELD","UNVERIFIED_UPPER_COMPARISON"])
        self.assertTrue(all(r[1]["fixed_floor_shadow"]["status"]=="WITHHELD" for r in output))
        self.assertTrue(all(not r[1]["distance_available"] for r in output))
        self.assertEqual(output[-1][2]["upper_candidate"]["point"],[320,400])
        self.assertNotIn("upper_candidate",output[-1][1])

    def test_model_generation_change_requires_new_confirmation(self):
        for n in (3,4,5):self.observe(n,load=self.active())
        r=self.observe(6,load=self.active(2))[2]
        self.assertEqual(r["reason"],"image_support_quality_not_confirmed")
        self.assertEqual(self.observe(7,load=self.active(2))[2]["status"],"WITHHELD")
        self.assertEqual(self.observe(8,load=self.active(2))[2]["status"],"UNVERIFIED_UPPER_COMPARISON")

    def test_rejected_reload_cannot_retain_old_model_values(self):
        for n in (3,4,5):self.observe(n,load=self.active())
        frame=self.frame(6)
        old=self.engine.fixed_floor_shadow;self.engine.fixed_floor_shadow=None
        base=self.engine.measure(frame,[BOX],frame.received_at+.01)
        base["fixed_floor_load"]=dict(
            schema="fixed_floor_load_v1",state="rejected",reason="synthetic_bad_reload",generation=2,
            controlling_distance=False,physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)
        r=self.upper.observe(frame,base,None,self.engine.camera,self.engine.transform)
        self.upper.finish(r,frame.received_at+.02,baseline=base)
        self.assertIsNone(r["upper_fixed_floor_shadow"])
        self.assertEqual(r["status"],"WITHHELD")
        self.engine.fixed_floor_shadow=old
        self.assertEqual(self.observe(7,load=self.active(3))[2]["status"],"WITHHELD")

    def test_disconnect_invalidation_requires_reconfirmation(self):
        for n in (1,2,3):self.observe(n)
        self.upper.invalidate()
        self.assertEqual(self.observe(4)[2]["status"],"WITHHELD")

    def test_startup_model_session_change_cannot_output(self):
        for n in (1,2,3):self.observe(n)
        self.engine.reset("other")
        frame=self.frame(1,t=11.,session="other")
        base=self.engine.measure(frame,[BOX],11.01)
        r=self.upper.observe(frame,base,self.engine.fixed_floor_shadow,self.engine.camera,self.engine.transform)
        self.upper.finish(r,11.02,baseline=base)
        self.assertEqual(r["reason"],"model_session_mismatch")
        self.assertFalse(any(m["range_available"] for m in r["upper_fixed_floor_shadow"]["models"]))

    def test_late_final_stamp_revokes_both_copied_ranges_and_resets_quality(self):
        for n in (1,2):self.observe(n)
        frame,base,r=self.observe(3)
        self.upper.finish(r,frame.received_at+.501,baseline=base)
        self.assertEqual(r["status"],"WITHHELD")
        self.assertEqual(r["reason"],"frame_processing_too_old")
        self.assertIsNone(r["upper_fixed_floor_shadow"]["models"][0]["horizontal_camera_foot_range_m"])
        self.assertEqual(self.observe(4)[2]["status"],"WITHHELD")

    def test_evidence_is_same_frame_pixels_and_rate_limited(self):
        frame,base,r=self.observe(1)
        self.assertEqual(r["evidence"]["status"],"saved")
        png=self.folder/r["evidence"]["file"]
        np.testing.assert_array_equal(cv2.imread(str(png)),frame.image)
        self.assertEqual(digest(png),r["evidence"]["sha256"])
        self.assertEqual(self.observe(2)[2]["evidence"]["status"],"rate_limited")

    def test_evidence_limit_includes_failed_attempts_and_never_overwrites(self):
        folder=self.folder/"upper_support_evidence";folder.mkdir()
        target=folder/"decoded_upper_test_f000001.png";target.write_bytes(b"keep")
        self.assertEqual(self.observe(1)[2]["evidence"]["status"],"save_error")
        self.assertEqual(self.upper.evidence_attempts,1)
        self.assertEqual(target.read_bytes(),b"keep")
        self.upper.evidence_attempts=20
        self.assertEqual(self.observe(2)[2]["evidence"]["status"],"attempt_limit_reached")

    def test_no_model_means_no_png_and_no_numeric_output(self):
        self.engine.fixed_floor_shadow=None
        r=self.observe(1)[2]
        self.assertIsNone(r["upper_fixed_floor_shadow"])
        self.assertEqual(r["evidence"]["status"],"not_requested")

    def test_multiple_or_missing_cones_never_reuse_previous_candidate(self):
        for n in (1,2,3):self.observe(n)
        for n,boxes in ((4,[]),(5,[BOX,dict(BOX,x1=350.,x2=390.)])):
            r=self.observe(n,boxes=boxes)[2]
            self.assertIsNone(r["upper_candidate"])
            self.assertEqual(r["status"],"WITHHELD")

    def test_candidate_exception_is_logged_without_replacing_legacy(self):
        frame=self.frame(1);base=self.engine.measure(frame,[BOX],frame.received_at+.01)
        original=copy.deepcopy(base)
        with patch("cone_upper_support_live.observe_upper_completion",side_effect=RuntimeError("test failure")):
            r=self.upper.observe(frame,base,self.engine.fixed_floor_shadow,self.engine.camera,self.engine.transform)
        self.upper.finish(r,frame.received_at+.02,baseline=base)
        self.assertEqual(base,original)
        self.assertIsNone(r["upper_candidate"])
        self.assertIn("test failure",r["observation_error"])

    def test_mismatched_frame_config_or_model_is_rejected(self):
        frame=self.frame(1);base=self.engine.measure(frame,[BOX],frame.received_at+.01)
        for change in (dict(frame=2),dict(session="other")):
            with self.assertRaises(ValueError):
                self.upper.observe(frame,dict(base,**change),self.engine.fixed_floor_shadow,self.engine.camera,self.engine.transform)
        bad=copy.deepcopy(base);bad["frame_evidence"]["floor_model"]["config_sha256"]="0"*64
        with self.assertRaises(ValueError):
            self.upper.observe(frame,bad,self.engine.fixed_floor_shadow,self.engine.camera,self.engine.transform)

    def test_validator_refuses_forged_authority_range_and_support(self):
        for n in (1,2):self.observe(n)
        good=self.observe(3)[2]
        changes=[]
        bad=copy.deepcopy(good);bad["usable_for_ffb"]=True;changes.append(bad)
        bad=copy.deepcopy(good);bad["upper_candidate"]["point"]=[0,0];changes.append(bad)
        bad=copy.deepcopy(good);bad["upper_fixed_floor_shadow"]["models"][0]["horizontal_camera_foot_range_m"]=float("nan");changes.append(bad)
        bad=copy.deepcopy(good);bad["upper_fixed_floor_shadow"]["model_bundle_sha256"]="0"*64;changes.append(bad)
        bad=copy.deepcopy(good);bad["upper_quality"]["observed_support"]=[];changes.append(bad)
        for bad in changes:
            with self.assertRaises(ValueError):validate_record(bad)

    def test_report_validates_and_counts_separate_rows(self):
        records=[self.observe(n)[2] for n in (1,2,3)]
        with (self.folder/"upper_support_comparison.jsonl").open("x") as stream:
            for row in records:stream.write(json.dumps(row)+"\n")
        report=summarize(self.folder,self.folder/"report")
        self.assertEqual(report["processed_rows"],3)
        self.assertEqual(report["upper_numeric_rows"],1)
        self.assertEqual(report["legacy_numeric_rows"],0)
        self.assertFalse(report["physical_metric_verified"])

    def test_report_rejects_time_reversal_and_nonfinite_json(self):
        records=[self.observe(n)[2] for n in (1,2,3)]
        path=self.folder/"upper_support_comparison.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in (records[0],records[2],records[1]))+"\n")
        with self.assertRaisesRegex(ValueError,"source order"):
            summarize(self.folder,self.folder/"bad-order-report")
        bad=dict(records[-1],unexpected=float("nan"))
        path.write_text(json.dumps(bad)+"\n")
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            summarize(self.folder,self.folder/"bad-json-report")

    def test_real_worker_writes_two_distinct_logs_and_closes_cleanly(self):
        slot=LatestNativeFrame();slot.begin("upper_test")
        now=[10.]
        worker=DistanceWorker(slot,DEFAULT_CONFIG,lambda f:[BOX],self.folder/"distance_frames.jsonl",
            scene_function=lambda *a:dict(accepted=False,reason="synthetic"),clock=lambda:now[0],
            support_completion_shadow=True,frame_evidence=True,fixed_floor_models=self.model,upper_support_shadow=True)
        self.addCleanup(worker.close);worker.start()
        for n in (1,2,3):
            now[0]=10+n/30
            slot.publish("upper_test",self.image,n/30,now[0])
            deadline=time.monotonic()+2
            while worker.latest is None or worker.latest[0].sequence!=n:
                if worker.error:self.fail(worker.error)
                if time.monotonic()>deadline:self.fail("worker wait expired")
                time.sleep(.005)
        self.assertTrue(worker.close()["shutdown_complete"])
        upper=[json.loads(s) for s in (self.folder/"upper_support_comparison.jsonl").read_text().splitlines()]
        baseline=[json.loads(s) for s in worker.log_path.read_text().splitlines()]
        self.assertEqual(len(upper),3)
        self.assertTrue(all("upper_candidate" not in r for r in baseline))
        self.assertEqual(upper[-1]["status"],"UNVERIFIED_UPPER_COMPARISON")
        self.assertTrue(all(u["frame"]==b["frame"] for u,b in zip(upper,baseline)))

    def test_worker_counts_evidence_time_in_final_freshness(self):
        slot=LatestNativeFrame();slot.begin("upper_test");now=[10.]
        worker=DistanceWorker(slot,DEFAULT_CONFIG,lambda f:[BOX],self.folder/"distance_frames.jsonl",
            scene_function=lambda *a:dict(accepted=False,reason="synthetic"),clock=lambda:now[0],
            support_completion_shadow=True,frame_evidence=True,fixed_floor_models=self.model,upper_support_shadow=True)
        self.addCleanup(worker.close)
        def delayed_evidence(*args):
            now[0]+=.6
            return dict(status="not_requested")
        worker.upper_comparison._evidence=delayed_evidence
        slot.publish("upper_test",self.image,0.,now[0]);worker.start()
        deadline=time.monotonic()+2
        path=self.folder/"upper_support_comparison.jsonl"
        while not path.exists() or not path.read_text().strip():
            if worker.error:self.fail(worker.error)
            if time.monotonic()>deadline:self.fail("delayed evidence wait expired")
            time.sleep(.005)
        worker.close()
        row=json.loads(path.read_text().splitlines()[0])
        self.assertGreater(row["frame_age_ms"],500.)
        self.assertEqual(row["status"],"WITHHELD")
        self.assertEqual(row["reason"],"frame_processing_too_old")


from test_cone_fixed_floor_live_load import FloorLoadFixture


class UpperReloadWorkerTests(FloorLoadFixture,unittest.TestCase):
    def wait_for(self,predicate):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.005)
        self.fail("upper reload worker wait expired")

    def test_real_local_reload_and_failed_replacement_remove_new_values(self):
        slot=LatestNativeFrame();slot.begin("test");slot.publish("test",self.image,0.,10.)
        worker=DistanceWorker(slot,DEFAULT_CONFIG,lambda f:[BOX],self.folder/"distance_frames.jsonl",
            scene_function=lambda *a:dict(accepted=False,reason="synthetic"),clock=lambda:self.now,
            support_completion_shadow=True,frame_evidence=True,fixed_floor_reload_file=self.path,upper_support_shadow=True)
        self.addCleanup(worker.close);worker.start()
        self.wait_for(lambda:worker.latest is not None)
        self.assertTrue(worker.request_fixed_floor_reload()[0])
        self.wait_for(lambda:worker.model_loader.future is not None and worker.model_loader.future.done())
        for n in (2,3,4):
            self.now=10+n/10;slot.publish("test",self.image,n/10,self.now)
            self.wait_for(lambda:worker.latest is not None and worker.latest[0].sequence==n)
        path=self.folder/"upper_support_comparison.jsonl"
        row=json.loads(path.read_text().splitlines()[-1])
        self.assertEqual(row["status"],"UNVERIFIED_UPPER_COMPARISON")
        self.path.write_text("invalid replacement")
        self.assertTrue(worker.request_fixed_floor_reload()[0])
        self.wait_for(lambda:worker.model_loader.future is not None and worker.model_loader.future.done())
        self.now=10.5;slot.publish("test",self.image,.5,self.now)
        self.wait_for(lambda:worker.latest is not None and worker.latest[0].sequence==5)
        row=json.loads(path.read_text().splitlines()[-1])
        self.assertIsNone(row["upper_fixed_floor_shadow"])
        self.assertEqual(row["fixed_floor_load"]["state"],"rejected")
        self.assertEqual(row["status"],"WITHHELD")
