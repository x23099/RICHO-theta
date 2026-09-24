import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ros_odometry import RosOdometryBridge  # noqa: E402


class _Node:
    def __init__(self):
        self.callback = None
        self.destroyed = False

    def create_subscription(self, _message_type, _topic, callback, _depth):
        self.callback = callback
        return object()

    def destroy_node(self):
        self.destroyed = True


class _RosApi:
    def __init__(self, initially_ok=False):
        self._ok = initially_ok
        self.initialized = False
        self.shutdown_called = False
        self.node = _Node()

    def ok(self):
        return self._ok

    def init(self, args=None):
        self.initialized = True
        self._ok = True

    def create_node(self, _name):
        return self.node

    def shutdown(self):
        self.shutdown_called = True
        self._ok = False


class RosOdometryBridgeTest(unittest.TestCase):
    def test_callback_updates_atomic_sample_and_receive_count(self):
        now = [12.5]
        ros_api = _RosApi()
        bridge = RosOdometryBridge(
            "/odom",
            ros_api=ros_api,
            message_type=object,
            monotonic_clock=lambda: now[0],
            start_executor=False,
        )
        message = SimpleNamespace(
            twist=SimpleNamespace(
                twist=SimpleNamespace(
                    linear=SimpleNamespace(x=0.25),
                    angular=SimpleNamespace(z=-0.1),
                )
            )
        )

        ros_api.node.callback(message)
        sample = bridge.sample()

        self.assertEqual(sample["linear_mps"], 0.25)
        self.assertEqual(sample["angular_radps"], -0.1)
        self.assertEqual(sample["monotonic_time"], 12.5)
        self.assertEqual(sample["received_count"], 1)
        bridge.close()
        self.assertTrue(ros_api.node.destroyed)
        self.assertTrue(ros_api.shutdown_called)


if __name__ == "__main__":
    unittest.main()
