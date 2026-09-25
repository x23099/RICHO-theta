import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from collision_ffb_relay import (  # noqa: E402
    CollisionFfbRelay,
    CollisionFfbRelayGate,
)


def _intent(*, stamp=10.0, source="bird_eye", active=True, magnitude=0.25):
    sec = int(stamp)
    nanosec = int(round((stamp - sec) * 1_000_000_000))
    return SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=sec, nanosec=nanosec)
        ),
        sequence=7,
        source=source,
        risk_level=2 if active else 0,
        pattern=1 if active else 0,
        active=active,
        normalized_magnitude=magnitude,
        reason="test",
    )


def _challenge(session=3, token=9):
    return SimpleNamespace(session_id=session, token=token)


class _Command:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None)
        self.sequence = 0
        self.source = ""
        self.risk_level = 0
        self.pattern = 0
        self.active = False
        self.normalized_magnitude = 0.0
        self.reason = ""
        self.receiver_session_id = 0
        self.receiver_token = 0


class _Challenge:
    pass


class _Now:
    def __init__(self, seconds):
        self.nanoseconds = int(seconds * 1_000_000_000)

    def to_msg(self):
        return "relay-stamp"


class _Clock:
    def __init__(self, seconds):
        self.seconds = seconds

    def now(self):
        return _Now(self.seconds)


class _Logger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, message):
        self.warnings.append(message)

    def error(self, message):
        self.errors.append(message)


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class _Node:
    def __init__(self, seconds):
        self.clock = _Clock(seconds)
        self.logger = _Logger()
        self.publisher = _Publisher()
        self.subscriptions = {}
        self.destroyed = False

    def create_publisher(self, _message_type, _topic, _qos):
        return self.publisher

    def create_subscription(self, _message_type, topic, callback, _qos):
        self.subscriptions[topic] = callback
        return callback

    def get_clock(self):
        return self.clock

    def get_logger(self):
        return self.logger

    def destroy_node(self):
        self.destroyed = True


class _RosApi:
    def __init__(self, seconds=10.02):
        self.running = True
        self.node = _Node(seconds)

    def ok(self):
        return self.running

    def init(self, args=None):
        self.running = True

    def shutdown(self):
        self.running = False

    def create_node(self, _name):
        return self.node


class CollisionFfbRelayGateTest(unittest.TestCase):
    def test_accepts_fresh_intent_once_with_fresh_challenge(self):
        gate = CollisionFfbRelayGate()
        self.assertTrue(gate.receive_challenge(_challenge(), 20.0))

        decision = gate.authorize(
            _intent(), now_ros_sec=10.02, now_monotonic=20.01
        )
        reused = gate.authorize(
            _intent(), now_ros_sec=10.03, now_monotonic=20.02
        )

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.receiver_session_id, 3)
        self.assertEqual(decision.receiver_token, 9)
        self.assertFalse(reused.accepted)
        self.assertEqual(reused.reason, "receiver_challenge_already_used")

    def test_rejects_stale_intent_before_consuming_token(self):
        gate = CollisionFfbRelayGate()
        gate.receive_challenge(_challenge(), 20.0)

        decision = gate.authorize(
            _intent(stamp=9.8), now_ros_sec=10.0, now_monotonic=20.01
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "stale_intent")
        self.assertIsNone(gate.last_used_challenge)

    def test_rejects_stale_challenge_and_out_of_order_update(self):
        gate = CollisionFfbRelayGate()
        self.assertTrue(gate.receive_challenge(_challenge(token=10), 20.0))
        self.assertFalse(gate.receive_challenge(_challenge(token=9), 20.02))

        decision = gate.authorize(
            _intent(), now_ros_sec=10.02, now_monotonic=20.07
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "stale_receiver_challenge")

    def test_rejects_unexpected_source_and_malformed_clear(self):
        gate = CollisionFfbRelayGate()
        gate.receive_challenge(_challenge(), 20.0)

        wrong_source = gate.authorize(
            _intent(source="other"),
            now_ros_sec=10.02,
            now_monotonic=20.01,
        )
        malformed_clear = gate.authorize(
            _intent(active=False, magnitude=0.1),
            now_ros_sec=10.02,
            now_monotonic=20.01,
        )

        self.assertEqual(wrong_source.reason, "unexpected_intent_source")
        self.assertEqual(
            malformed_clear.reason, "inactive_intent_has_magnitude"
        )


class CollisionFfbRelayRosTest(unittest.TestCase):
    def test_forwards_authorized_intent_with_receiver_token(self):
        ros_api = _RosApi()
        monotonic_values = iter((20.0, 20.01))
        relay = CollisionFfbRelay(
            ros_api=ros_api,
            command_type=_Command,
            challenge_type=_Challenge,
            qos_profile="qos",
            monotonic_clock=lambda: next(monotonic_values),
        )

        ros_api.node.subscriptions["/collision/ffb_challenge"](_challenge())
        ros_api.node.subscriptions["/collision/ffb_intent"](_intent())

        self.assertEqual(len(ros_api.node.publisher.messages), 1)
        message = ros_api.node.publisher.messages[0]
        self.assertEqual(message.header.stamp, "relay-stamp")
        self.assertEqual(message.sequence, 7)
        self.assertEqual(message.receiver_session_id, 3)
        self.assertEqual(message.receiver_token, 9)
        relay.close()

    def test_rejected_intent_publishes_nothing(self):
        ros_api = _RosApi(seconds=10.5)
        relay = CollisionFfbRelay(
            ros_api=ros_api,
            command_type=_Command,
            challenge_type=_Challenge,
            qos_profile="qos",
            monotonic_clock=lambda: 20.0,
        )

        ros_api.node.subscriptions["/collision/ffb_intent"](_intent())

        self.assertEqual(ros_api.node.publisher.messages, [])
        self.assertIn("stale_intent", ros_api.node.logger.warnings[-1])
        relay.close()


if __name__ == "__main__":
    unittest.main()
