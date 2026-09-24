import threading
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ros_executor_thread import RosExecutorThread


class _Executor:
    def __init__(self, fail=False):
        self.fail = fail
        self.started = threading.Event()
        self.stopped = threading.Event()

    def add_node(self, _node):
        return True

    def spin(self):
        self.started.set()
        if self.fail:
            raise RuntimeError("synthetic executor failure")
        self.stopped.wait(1.0)

    def shutdown(self, timeout_sec=None):
        self.stopped.set()
        return True


class RosExecutorThreadTest(unittest.TestCase):
    def test_starts_and_stops_executor(self):
        executor = _Executor()
        worker = RosExecutorThread(executor, object(), name="test-executor")
        self.assertTrue(executor.started.wait(0.5))
        worker.raise_if_failed()
        worker.close()
        self.assertFalse(worker.thread.is_alive())

    def test_reports_executor_failure(self):
        executor = _Executor(fail=True)
        worker = RosExecutorThread(executor, object(), name="test-executor")
        self.assertTrue(executor.started.wait(0.5))
        worker.thread.join(0.5)
        with self.assertRaisesRegex(RuntimeError, "synthetic executor failure"):
            worker.raise_if_failed()
        worker.close()


if __name__ == "__main__":
    unittest.main()
