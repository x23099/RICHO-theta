"""Receiver shutdown tests with fake CUDA/model/server; never bind a socket."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import run_cone_distance_live as live


class LiveCleanupTest(unittest.TestCase):
    def exercise(self, *, shutdown_complete=True, setup_error=False,
                 receiver_close_error=False, detector_error=None):
        self.calls = []
        self.summary = None
        self.error = None
        calls = self.calls
        class Predictor:
            def __init__(self, weights, settings, output_dir, device):
                output_dir.mkdir()
                self.gpu = {"test_only": True}
                self.weights_sha256 = "synthetic-not-a-checkpoint"
        class Receiver:
            def __init__(self, slot):
                pass
            async def offer(self, request):
                raise AssertionError("no real HTTP request allowed")
            async def close(self):
                calls.append("receiver.close")
                if receiver_close_error:
                    raise RuntimeError("synthetic receiver cleanup failure")
        class Worker:
            def __init__(self, *args, **kwargs):
                self.engine = SimpleNamespace(target_roi=None)
                self.error = detector_error
            def start(self):
                calls.append("worker.start")
            def poll(self, now, current):
                return None, "synthetic_no_frames"
            def close(self):
                calls.append("worker.close")
                return dict(worker_stopped=True, scene_job_running=not shutdown_complete,
                            shutdown_complete=shutdown_complete, retired_scene_jobs=0)
        class Runner:
            def __init__(self, *args, **kwargs):
                pass
            async def setup(self):
                calls.append("runner.setup")
                if setup_error:
                    raise RuntimeError("synthetic runner setup failure")
            async def cleanup(self):
                calls.append("runner.cleanup")
        class Site:
            def __init__(self, *args, **kwargs):
                pass
            async def start(self):
                calls.append("site.start.fake.no_socket")
        async def inline_to_thread(function, *args):
            # Stub close is instantaneous; real worker threading is covered by
            # test_cone_distance_worker_lifecycle, not by this resource-order test.
            return function(*args)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"out"
            args = live.build_parser().parse_args(["--weights", "unused.pt", "--output-dir", str(output),
                                                   "--headless", "--duration-sec", ".02"])
            with patch.object(live, "YoloConePredictor", Predictor), patch.object(live, "Receiver", Receiver), \
                 patch.object(live, "DistanceWorker", Worker), patch("aiohttp.web.AppRunner", Runner), \
                 patch("aiohttp.web.TCPSite", Site), patch.object(live.asyncio, "to_thread", inline_to_thread):
                try:
                    asyncio.run(live.run(args))
                except RuntimeError as exc:
                    self.error = str(exc)
            self.summary = json.loads((output/"live_summary.json").read_text())

    def test_normal_shutdown_is_not_physical_approval(self):
        self.exercise()
        self.assertIsNone(self.error)
        self.assertEqual(self.summary["runtime_status"], "STOPPED")
        self.assertTrue(self.summary["shutdown"]["shutdown_complete"])
        self.assertFalse(self.summary["usable_for_ffb"])
        self.assertFalse(self.summary["physical_output"])

    def test_running_scene_is_not_reported_as_complete_shutdown(self):
        self.exercise(shutdown_complete=False)
        self.assertIn("cleanup incomplete", self.error)
        self.assertEqual(self.summary["runtime_status"], "CLEANUP_INCOMPLETE")
        self.assertTrue(self.summary["worker_stopped"])
        self.assertTrue(self.summary["shutdown"]["scene_job_running"])

    def test_receiver_cleanup_failure_still_closes_runner_and_worker(self):
        self.exercise(receiver_close_error=True)
        self.assertIn("cleanup incomplete", self.error)
        self.assertIn("runner.cleanup", self.calls)
        self.assertIn("worker.close", self.calls)
        self.assertIn("synthetic receiver cleanup failure", self.summary["cleanup_errors"][0])

    def test_setup_failure_still_closes_unstarted_worker(self):
        self.exercise(setup_error=True)
        self.assertIn("synthetic runner setup failure", self.error)
        self.assertNotIn("worker.start", self.calls)
        self.assertNotIn("site.start.fake.no_socket", self.calls)
        self.assertIn("worker.close", self.calls)
        self.assertEqual(self.summary["runtime_status"], "RUN_FAILED")

    def test_original_failure_is_not_masked_by_cleanup_failure(self):
        self.exercise(setup_error=True, receiver_close_error=True)
        self.assertEqual(self.error, "synthetic runner setup failure")
        self.assertIn("synthetic runner setup failure", self.summary["run_error"])
        self.assertEqual(self.summary["runtime_status"], "CLEANUP_INCOMPLETE")

    def test_detector_failure_is_preserved_in_summary(self):
        self.exercise(detector_error="synthetic CUDA failure")
        self.assertIn("distance worker failed: synthetic CUDA failure", self.error)
        self.assertEqual(self.summary["worker_error"], "synthetic CUDA failure")
        self.assertEqual(self.summary["runtime_status"], "RUN_FAILED")


if __name__ == "__main__":
    unittest.main()
