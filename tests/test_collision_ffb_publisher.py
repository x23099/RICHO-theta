import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from bird_eye import CalibrationWindow  # noqa: E402
from collision_ffb_publisher import (  # noqa: E402
    CollisionFfbPublisherBridge,
    PATTERN_VALUES,
    RISK_LEVEL_VALUES,
    virtual_command_payload,
)
from virtual_ffb import VirtualFfbPolicy  # noqa: E402


class _Message:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None)


class _Publisher:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def publish(self, message):
        if self.fail:
            raise RuntimeError("synthetic publish failure")
        self.messages.append(message)


class _Node:
    def __init__(self, publisher):
        self.publisher = publisher
        self.destroyed = False

    def create_publisher(self, _message_type, _topic, _qos):
        return self.publisher

    def get_clock(self):
        return SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=lambda: "fake-stamp")
        )

    def destroy_node(self):
        self.destroyed = True


class _RosApi:
    def __init__(self, *, initially_ok=True, fail_publish=False):
        self._ok = initially_ok
        self.initialized = False
        self.shutdown_called = False
        self.publisher = _Publisher(fail=fail_publish)
        self.node = _Node(self.publisher)

    def ok(self):
        return self._ok

    def init(self, args=None):
        self.initialized = True
        self._ok = True

    def shutdown(self):
        self.shutdown_called = True
        self._ok = False

    def create_node(self, _name):
        return self.node


def _bridge(ros_api):
    return CollisionFfbPublisherBridge(
        ros_api=ros_api,
        message_type=_Message,
        qos_profile=object(),
    )


class CollisionFfbPublisherTest(unittest.TestCase):
    def test_virtual_policy_enum_mapping_is_exact(self):
        policy = VirtualFfbPolicy()
        expected = {
            "CLEAR": (0, 0, False, 0.0),
            "PATH": (1, 0, False, 0.0),
            "WARNING": (2, 1, True, 0.25),
            "WARNING_HOLD": (3, 2, True, 0.25),
            "CRITICAL": (4, 1, True, 0.40),
            "UNKNOWN": (5, 3, True, 0.15),
        }

        for risk_level, values in expected.items():
            with self.subTest(risk_level=risk_level):
                payload = virtual_command_payload(policy.command(risk_level))
                self.assertEqual(
                    (
                        payload["risk_level"],
                        payload["pattern"],
                        payload["active"],
                        payload["normalized_magnitude"],
                    ),
                    values,
                )
        self.assertEqual(RISK_LEVEL_VALUES["WARNING_HOLD"], 3)
        self.assertEqual(PATTERN_VALUES["STEADY_HOLD".lower()], 2)

    def test_publish_populates_message_and_increments_sequence(self):
        ros_api = _RosApi()
        bridge = _bridge(ros_api)

        first = bridge.publish_risk("CLEAR")
        second = bridge.publish_risk("WARNING")

        self.assertEqual(first["collision_ffb_sequence"], 0)
        self.assertEqual(second["collision_ffb_sequence"], 1)
        self.assertEqual(second["collision_ffb_publish_success"], 1)
        self.assertEqual(second["collision_ffb_requested_magnitude"], 0.25)
        message = ros_api.publisher.messages[-1]
        self.assertEqual(message.header.stamp, "fake-stamp")
        self.assertEqual(message.sequence, 1)
        self.assertEqual(message.source, "bird_eye")
        self.assertEqual(message.risk_level, 2)
        self.assertEqual(message.pattern, 1)
        self.assertTrue(message.active)
        self.assertEqual(message.normalized_magnitude, 0.25)

    def test_close_publishes_clear_and_releases_only_owned_runtime(self):
        ros_api = _RosApi(initially_ok=False)
        bridge = _bridge(ros_api)
        bridge.publish_risk("WARNING_HOLD")

        bridge.close()

        self.assertTrue(ros_api.initialized)
        self.assertTrue(ros_api.shutdown_called)
        self.assertTrue(ros_api.node.destroyed)
        final_message = ros_api.publisher.messages[-1]
        self.assertEqual(final_message.risk_level, RISK_LEVEL_VALUES["CLEAR"])
        self.assertFalse(final_message.active)

    def test_publish_error_is_recorded_without_crashing_live_loop(self):
        bridge = _bridge(_RosApi(fail_publish=True))

        record = bridge.publish_risk("CRITICAL")

        self.assertEqual(record["collision_ffb_publish_success"], 0)
        self.assertIn(
            "synthetic publish failure",
            record["collision_ffb_publish_error"],
        )
        self.assertEqual(record["collision_ffb_risk_level"], "CRITICAL")
        bridge.close()

    def test_window_publishes_final_collision_state(self):
        ros_api = _RosApi()
        window = CalibrationWindow.__new__(CalibrationWindow)
        window.collision_ffb_publisher = _bridge(ros_api)
        window.last_blue_collision = {"risk_level": "WARNING_HOLD"}

        record = window.publish_collision_ffb()

        self.assertEqual(record["collision_ffb_risk_level"], "WARNING_HOLD")
        self.assertEqual(record["collision_ffb_requested_magnitude"], 0.25)
        self.assertEqual(ros_api.publisher.messages[-1].risk_level, 3)
        window.collision_ffb_publisher.close()


if __name__ == "__main__":
    unittest.main()
