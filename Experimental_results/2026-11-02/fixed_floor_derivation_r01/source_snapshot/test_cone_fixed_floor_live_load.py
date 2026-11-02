"""Local model activation tests. Only temporary synthetic PNGs and fake frames."""
from concurrent.futures import Future
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_distance_worker import DistanceWorker
from cone_fixed_floor_live_load import LocalFloorModelLoader, bounded_regular_bytes, validate_live_payload
from prepare_fixed_floor_live_bundle import prepare
from run_cone_distance_live import build_parser
from summarize_cone_distance_live import validate_row
from theta_rtc_frames import LatestNativeFrame, NativeFrame

BUNDLE = ROOT / "Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/explicit_floor_models.json"
BOX = dict(x1=290., y1=305., x2=350., y2=405., confidence=.95, class_id=0)


class ControlledLoaderPool:
    def __init__(self):
        self.jobs = []

    def submit(self, function, *args):
        future = Future()
        future.set_running_or_notify_cancel()
        self.jobs.append((future, function, args))
        return future

    def finish(self):
        future, function, args = self.jobs[-1]
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)

    def shutdown(self, **kwargs):
        pass


class FloorLoadFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.settings = load_config()[0]
        self.config_sha = digest(DEFAULT_CONFIG)
        self.image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(self.image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
        self.png = self.folder / "decoded_test_f000001.png"
        self.assertTrue(cv2.imwrite(str(self.png), self.image))
        self.bundle = json.loads(BUNDLE.read_text())
        self.bundle["session"] = "test"
        for model in self.bundle["models"]:
            model["session"] = "test"
        self.original = self.folder / "original.json"
        self.original.write_text(json.dumps(self.bundle))
        self.payload = prepare(self.original, [self.png], DEFAULT_CONFIG,
                               board_on_floor=True, rigid_board=True, static_camera=True)
        self.path = self.folder / "prepared.json"
        self.path.write_bytes(self.payload)
        self.now = 10.
        self.pool = ControlledLoaderPool()
        self.loader = LocalFloorModelLoader(self.path, self.settings, self.config_sha, self.folder,
            self.folder / "events.jsonl", "support_completion_shadow", clock=lambda: self.now, executor=self.pool)
        self.addCleanup(self.loader.close)

    def frame(self, sequence=2, received=10., session="test"):
        return NativeFrame(session, sequence, received, received, self.image)

    def validate(self, payload=None, maximum_frame=2):
        return validate_live_payload(self.payload if payload is None else payload, self.settings,
            self.config_sha, self.folder, "test", maximum_frame, "support_completion_shadow")

    def activate(self):
        self.assertTrue(self.loader.request(self.frame())[0])
        self.now = 10.05
        self.pool.finish()
        self.now = 10.1
        adapter = self.loader.step(self.frame(3, 10.1))
        self.assertIsNotNone(adapter)
        return adapter


class LocalFloorLoadTests(FloorLoadFixture, unittest.TestCase):
    def test_no_request_means_no_file_load_or_automatic_activation(self):
        self.path.unlink()
        self.assertIsNone(self.loader.step(self.frame()))
        self.assertEqual(self.pool.jobs, [])
        self.assertEqual(self.loader.snapshot()["state"], "waiting")

    def test_valid_explicit_request_activates_only_after_read_completed(self):
        self.loader.request(self.frame())
        self.now = 10.2
        self.pool.finish()
        self.assertIsNone(self.loader.step(self.frame(3, 10.1)))
        self.assertEqual(self.loader.snapshot()["state"], "ready")
        adapter = self.loader.step(self.frame(4, 10.3))
        self.assertIsNotNone(adapter)
        state = self.loader.snapshot()
        self.assertEqual(state["activated_frame"], 4)
        self.assertEqual(state["evidence_frames"], [1])

    def test_one_pending_job_no_queue(self):
        self.loader.request(self.frame())
        self.assertFalse(self.loader.request(self.frame())[0])
        self.assertEqual(len(self.pool.jobs), 1)

    def test_submission_failure_revokes_model_and_is_logged_without_crashing(self):
        self.activate()
        from unittest.mock import patch
        with patch.object(self.pool, "submit", side_effect=RuntimeError("unavailable")):
            self.assertEqual(self.loader.request(self.frame(4, 10.2)), (False, "load_submit_failed"))
        self.assertIsNone(self.loader.step(self.frame(5, 10.3)))
        self.assertEqual(self.loader.snapshot()["reason"], "submit_failed:RuntimeError")

    def test_reconnect_while_loading_never_applies_old_session(self):
        self.loader.request(self.frame())
        self.loader.step(self.frame(1, 10.1, "new"))
        self.pool.finish()
        self.assertIsNone(self.loader.step(self.frame(3, 10.2)))
        self.assertEqual(self.loader.snapshot()["state"], "rejected")

    def test_ready_model_is_invalidated_by_disconnect(self):
        self.loader.request(self.frame())
        self.now = 10.2
        self.pool.finish()
        self.loader.step(self.frame(3, 10.1))
        self.loader.step(None)
        self.assertIsNone(self.loader.step(self.frame(4, 10.3)))

    def test_active_model_is_invalidated_on_stale_or_disconnected_input(self):
        self.activate()
        self.assertIsNone(self.loader.step(None))
        self.assertIsNone(self.loader.step(self.frame(4, 10.3)))

    def test_new_request_revokes_old_model_and_bad_load_does_not_restore_it(self):
        self.activate()
        self.path.write_text("not-json")
        self.loader.request(self.frame(4, 10.2))
        self.pool.finish()
        self.assertIsNone(self.loader.step(self.frame(5, 10.3)))
        self.assertEqual(self.loader.snapshot()["state"], "rejected")

    def test_loaded_payload_not_reread_when_file_changes_before_activation(self):
        self.loader.request(self.frame())
        self.pool.finish()
        self.path.write_text("changed after read")
        self.now = 10.1
        adapter = self.loader.step(self.frame(3, 10.1))
        self.assertIsNotNone(adapter)
        import hashlib
        self.assertEqual(adapter.bundle_sha256, hashlib.sha256(self.payload).hexdigest())

    def test_shutdown_reports_unfinished_load_and_does_not_revive_it(self):
        self.loader.request(self.frame())
        self.assertTrue(self.loader.close()["model_load_running"])
        self.pool.finish()
        self.assertFalse(self.loader.close()["model_load_running"])
        self.assertIsNone(self.loader.step(self.frame(4, 10.3)))
        self.assertFalse(self.loader.request(self.frame())[0])

    def test_session_rebinding_is_refused(self):
        data = json.loads(self.payload)
        data["session"] = "new"
        for model in data["models"]:
            model["session"] = "new"
        with self.assertRaises(ValueError):
            self.validate(json.dumps(data).encode())

    def test_model_must_include_same_config_and_camera_evidence(self):
        for key in ("config_sha256", "camera_sha256"):
            data = json.loads(self.payload)
            data["live_evidence"][key] = "0"*64
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(json.dumps(data).encode())

    def test_changed_png_hash_refused(self):
        self.png.write_bytes(self.png.read_bytes()+b"different bytes")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.validate()

    def test_future_evidence_frame_refused(self):
        with self.assertRaises(ValueError):
            self.validate(maximum_frame=0)

    def test_traversal_and_duplicate_evidence_refused(self):
        for change in ("path", "duplicate"):
            data = json.loads(self.payload)
            if change == "path":
                data["live_evidence"]["source_frames"][0]["file"] = "../"+self.png.name
            else:
                data["live_evidence"]["source_frames"] *= 2
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate(json.dumps(data).encode())

    def test_placement_must_be_explicitly_confirmed_not_inferred(self):
        with self.assertRaises(ValueError):
            prepare(self.original, [self.png], DEFAULT_CONFIG)
        data = json.loads(self.payload)
        data["live_evidence"]["static_camera_confirmed"] = False
        with self.assertRaises(ValueError):
            self.validate(json.dumps(data).encode())

    def test_physical_approval_is_never_accepted(self):
        data = json.loads(self.payload)
        data["models"][0]["physical_metric_verified"] = True
        with self.assertRaises(ValueError):
            self.validate(json.dumps(data).encode())

    def test_symlinks_and_oversized_files_are_not_read(self):
        link = self.folder / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            bounded_regular_bytes(link, 512*1024)
        with self.assertRaises(ValueError):
            bounded_regular_bytes(self.path, 1)

    def test_cli_modes_are_explicit_and_mutually_exclusive(self):
        parser = build_parser()
        default = parser.parse_args(["--weights", "x", "--output-dir", "out"])
        self.assertIsNone(default.fixed_floor_reload_file)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--weights", "x", "--output-dir", "out", "--fixed-floor-models", "one",
                               "--fixed-floor-reload-file", "two"])

    def test_preparer_output_is_new_file_only(self):
        from prepare_fixed_floor_live_bundle import main
        target = self.folder / "do-not-overwrite.json"
        target.write_text("existing")
        with self.assertRaises(FileExistsError):
            main(["--models", str(self.original), "--evidence-png", str(self.png),
                  "--board-on-floor", "--rigid-board", "--static-camera", "--output", str(target)])
        self.assertEqual(target.read_text(), "existing")

    def test_event_log_records_requests_acceptance_and_close_without_authority(self):
        self.activate()
        self.loader.close()
        events = [json.loads(line) for line in (self.folder/"events.jsonl").read_text().splitlines()]
        self.assertEqual([e["action"] for e in events], ["requested", "accepted", "closed"])
        self.assertTrue(all(e["usable_for_ffb"] is False and e["physical_metric_verified"] is False for e in events))

    def test_headless_reload_rejected_before_predictor_or_network(self):
        import asyncio
        from unittest.mock import patch
        import run_cone_distance_live as live
        args=live.build_parser().parse_args(["--weights","unused.pt","--output-dir",str(self.folder/"unused"),
            "--headless","--support-completion-shadow","--fixed-floor-reload-file",str(self.path)])
        with patch.object(live,"YoloConePredictor",side_effect=AssertionError("GPU must not start")):
            with self.assertRaisesRegex(ValueError,"requires the GUI"):
                asyncio.run(live.run(args))

    def test_l_key_routes_one_explicit_request_without_socket_or_cuda(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        import run_cone_distance_live as live
        calls=[]
        class Predictor:
            def __init__(self,weights,settings,output,device):
                output.mkdir()
                self.gpu={"synthetic":True}
                self.weights_sha256="synthetic"
        class Receiver:
            def __init__(self,*a):pass
            async def offer(self,*a):raise AssertionError("no network")
            async def close(self):pass
        class Worker:
            error=None
            def __init__(self,*a,**kw):
                self.engine=SimpleNamespace(target_roi=None)
                self.model_loader=SimpleNamespace(snapshot=lambda:dict(generation=0,state="waiting",reason="not_requested"))
                calls.append(kw["fixed_floor_reload_file"])
            def start(self):pass
            def poll(self,*a):return None,"synthetic"
            def request_fixed_floor_reload(self):calls.append("explicit L");return True,"requested"
            def close(self):return dict(worker_stopped=True,scene_job_running=False,shutdown_complete=True)
        class Runner:
            def __init__(self,*a,**kw):pass
            async def setup(self):pass
            async def cleanup(self):pass
        class Site:
            def __init__(self,*a,**kw):pass
            async def start(self):pass
        args=live.build_parser().parse_args(["--weights","unused.pt","--output-dir",str(self.folder/"fake-GUI"),
            "--support-completion-shadow","--fixed-floor-reload-file",str(self.path)])
        with patch.object(live,"YoloConePredictor",Predictor),patch.object(live,"Receiver",Receiver), \
             patch.object(live,"DistanceWorker",Worker),patch("aiohttp.web.AppRunner",Runner), \
             patch("aiohttp.web.TCPSite",Site),patch.object(live.cv2,"imshow"), \
             patch.object(live.cv2,"waitKey",side_effect=[ord("L"),ord("Q")]),patch.object(live.cv2,"destroyAllWindows"):
            asyncio.run(live.run(args))
        self.assertEqual(calls,[self.path,"explicit L"])
        summary = json.loads((args.output_dir/"live_summary.json").read_text())
        self.assertTrue(summary["fixed_floor_shadow_enabled"])
        self.assertTrue(summary["fixed_floor_local_reload_enabled"])


class LiveLoadWorkerTests(FloorLoadFixture, unittest.TestCase):
    def wait_for(self, predicate):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.005)
        self.fail("bounded worker wait expired")

    def test_real_worker_activates_without_restart_then_retires_on_new_session(self):
        slot = LatestNativeFrame()
        slot.begin("test")
        slot.publish("test", self.image, 0., 10.)
        worker = DistanceWorker(slot, DEFAULT_CONFIG, lambda _: [BOX], self.folder / "frames.jsonl",
            scene_function=lambda *args: dict(accepted=False, reason="synthetic_scene"),
            clock=lambda: self.now, support_completion_shadow=True, fixed_floor_reload_file=self.path)
        self.addCleanup(worker.close)
        worker.start()
        self.wait_for(lambda: worker.latest is not None)
        self.assertTrue(worker.request_fixed_floor_reload()[0])
        self.wait_for(lambda: worker.model_loader.future is not None and worker.model_loader.future.done())
        for sequence in (2, 3, 4):
            self.now = 10.+sequence/10
            slot.publish("test", self.image, sequence/10, self.now)
            self.wait_for(lambda: worker.latest is not None and worker.latest[0].sequence == sequence)
        row = worker.latest[1]
        self.assertEqual(row["fixed_floor_load"]["state"], "active")
        self.assertTrue(all(m["range_available"] for m in row["fixed_floor_shadow"]["models"]))
        self.assertFalse(row["distance_available"])
        validate_row(row)
        for key, value in (("load_completed_at_sec", self.now+1), ("activated_frame", row["frame"]+1),
                           ("state", "rejected")):
            bad = copy.deepcopy(row)
            bad["fixed_floor_load"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_row(bad)
        changed = copy.deepcopy(row)
        changed["fixed_floor_load"]["requested_session"] = "not-test"
        with self.assertRaises(ValueError):
            validate_row(changed)
        slot.begin("new")
        self.now = 10.5
        slot.publish("new", self.image, 0., self.now)
        self.wait_for(lambda: worker.latest is not None and worker.latest[0].session == "new")
        self.assertNotIn("fixed_floor_shadow", worker.latest[1])
        self.assertIsNone(worker.error)

    def test_newer_slot_frame_does_not_activate_model_on_older_inflight_inference(self):
        import threading
        entered = {n: threading.Event() for n in (2, 3)}
        release = {n: threading.Event() for n in (2, 3)}
        def predictor(frame):
            if frame.sequence in entered:
                entered[frame.sequence].set()
                if not release[frame.sequence].wait(2):
                    raise RuntimeError("test inference gate timed out")
            return [BOX]
        slot = LatestNativeFrame()
        slot.begin("test")
        slot.publish("test", self.image, 0., 10.)
        logfile = self.folder/"inflight.jsonl"
        worker = DistanceWorker(slot, DEFAULT_CONFIG, predictor, logfile,
            scene_function=lambda *args: dict(accepted=False, reason="synthetic"), clock=lambda: self.now,
            support_completion_shadow=True, fixed_floor_reload_file=self.path)
        self.addCleanup(worker.close)
        for event in release.values():
            self.addCleanup(event.set)
        worker.model_loader.pool.shutdown(wait=True)
        controlled = ControlledLoaderPool()
        worker.model_loader.pool = controlled
        worker.start()
        self.wait_for(lambda: worker.latest is not None)
        self.assertTrue(worker.request_fixed_floor_reload()[0])
        self.now = 10.1
        slot.publish("test", self.image, .1, self.now)
        self.assertTrue(entered[2].wait(1))
        self.now = 10.15
        controlled.finish()
        self.now = 10.2
        slot.publish("test", self.image, .2, self.now)
        release[2].set()
        self.assertTrue(entered[3].wait(1))
        rows = [json.loads(line) for line in logfile.read_text().splitlines()]
        row = next(r for r in rows if r["frame"] == 2)
        self.assertEqual(row["fixed_floor_load"]["state"], "ready")
        self.assertNotIn("fixed_floor_shadow", row)
        validate_row(row)
        release[3].set()
        self.wait_for(lambda: worker.latest is not None and worker.latest[0].sequence == 3)
        row = worker.latest[1]
        self.assertEqual(row["fixed_floor_load"]["activated_frame"], 3)
        validate_row(row)

    def test_reload_immediately_hides_old_comparison_and_never_falls_back_on_error(self):
        slot = LatestNativeFrame()
        slot.begin("test")
        slot.publish("test", self.image, 0., 10.)
        worker = DistanceWorker(slot, DEFAULT_CONFIG, lambda _: [BOX], self.folder/"worker-failed-reload.jsonl",
            scene_function=lambda *args: dict(accepted=False, reason="synthetic"), clock=lambda:self.now,
            support_completion_shadow=True, fixed_floor_reload_file=self.path)
        self.addCleanup(worker.close)
        worker.start()
        self.wait_for(lambda: worker.latest is not None)
        worker.request_fixed_floor_reload()
        self.wait_for(lambda: worker.model_loader.future is not None and worker.model_loader.future.done())
        for sequence in (2,3,4):
            self.now=10.+sequence/10
            slot.publish("test",self.image,sequence/10,self.now)
            self.wait_for(lambda: worker.latest is not None and worker.latest[0].sequence==sequence)
        self.assertIn("fixed_floor_shadow", worker.latest[1])
        self.path.write_text("invalid-new-model")
        self.assertTrue(worker.request_fixed_floor_reload()[0])
        current=slot.current(self.now)[0]
        displayed,_=worker.poll(self.now,current)
        self.assertIsNotNone(displayed)
        self.assertNotIn("fixed_floor_shadow",displayed[1])
        self.assertFalse(displayed[1]["distance_available"])
        self.wait_for(lambda: worker.model_loader.future is not None and worker.model_loader.future.done())
        self.now=10.5
        slot.publish("test",self.image,.5,self.now)
        self.wait_for(lambda: worker.latest is not None and worker.latest[0].sequence==5)
        self.assertEqual(worker.latest[1]["fixed_floor_load"]["state"],"rejected")
        self.assertNotIn("fixed_floor_shadow",worker.latest[1])
        validate_row(worker.latest[1])


if __name__ == "__main__":
    unittest.main()
