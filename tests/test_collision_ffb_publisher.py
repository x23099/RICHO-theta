import sys
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from bird_eye import CalibrationWindow  # noqa: E402
from collision_ffb_publisher import (  # noqa: E402
    CollisionFfbCadenceController,
    CollisionFfbPublisherBridge,
    PATTERN_VALUES,
    RISK_LEVEL_VALUES,
    build_cadence_schedule,
    virtual_command_payload,
)
from virtual_ffb import VirtualFfbPolicy  # noqa: E402


class _Message:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None)
        self.receiver_session_id = 0
        self.receiver_token = 0


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
        self.subscription_callback = None

    def create_publisher(self, _message_type, _topic, _qos):
        return self.publisher

    def create_subscription(self, _message_type, _topic, callback, _qos):
        self.subscription_callback = callback
        return object()

    def get_clock(self):
        return SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=lambda: "fake-stamp")
        )

    def destroy_node(self):
        self.destroyed = True


class _RosApi:
    def __init__(
        self, *, initially_ok=True, fail_publish=False, fail_spin=False
    ):
        self._ok = initially_ok
        self.initialized = False
        self.shutdown_called = False
        self.publisher = _Publisher(fail=fail_publish)
        self.node = _Node(self.publisher)
        self.fail_spin = fail_spin

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

    def spin_once(self, _node, timeout_sec=0.0):
        if self.fail_spin:
            raise RuntimeError("synthetic challenge receive failure")


class _FailedExecutorThread:
    def raise_if_failed(self):
        raise RuntimeError("synthetic challenge executor failure")

    def close(self):
        pass


class _ChallengeExecutor:
    def __init__(self):
        self.node = None
        self.delivered = threading.Event()
        self.stopped = threading.Event()

    def add_node(self, node):
        self.node = node
        return True

    def spin(self):
        self.node.subscription_callback(
            SimpleNamespace(session_id=41, token=202)
        )
        self.delivered.set()
        self.stopped.wait(1.0)

    def shutdown(self, timeout_sec=None):
        self.stopped.set()
        return True


def _bridge(ros_api, **kwargs):
    start_executor = kwargs.pop("start_executor", False)
    return CollisionFfbPublisherBridge(
        ros_api=ros_api,
        message_type=_Message,
        qos_profile=object(),
        challenge_message_type=_Message,
        start_executor=start_executor,
        **kwargs,
    )


class CollisionFfbPublisherTest(unittest.TestCase):
    def test_relay_config_publishes_local_intent_without_gui_challenge(self):
        window = CalibrationWindow.__new__(CalibrationWindow)
        window.params = {
            "collision_ffb_publish_enabled": 1,
            "collision_ffb_relay_enabled": 1,
            "collision_ffb_intent_topic": "/collision/ffb_intent",
            "collision_ffb_command_topic": "/collision/ffb_command",
            "collision_ffb_freshness_mode": "challenge",
        }
        fake_publisher = SimpleNamespace(topic="/collision/ffb_intent")

        with patch(
            "bird_eye.CollisionFfbPublisherBridge",
            return_value=fake_publisher,
        ) as bridge_type:
            publisher = window.create_collision_ffb_publisher()

        self.assertIs(publisher, fake_publisher)
        kwargs = bridge_type.call_args.kwargs
        self.assertEqual(kwargs["topic"], "/collision/ffb_intent")
        self.assertEqual(kwargs["freshness_mode"], "clock")

    def test_challenge_executor_receives_without_frame_polling(self):
        ros_api = _RosApi()
        executor = _ChallengeExecutor()
        bridge = _bridge(
            ros_api,
            freshness_mode="challenge",
            executor_factory=lambda: executor,
            start_executor=True,
        )
        self.assertTrue(executor.delivered.wait(0.5))

        result = bridge.publish_risk("CLEAR")

        self.assertEqual(result["collision_ffb_publish_success"], 1)
        self.assertEqual(result["collision_ffb_challenge_received_count"], 1)
        self.assertEqual(result["collision_ffb_challenge_session_id"], 41)
        self.assertEqual(result["collision_ffb_challenge_token"], 202)
        bridge.close()

    def test_challenge_mode_never_publishes_without_recent_receiver_token(self):
        now = [2.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api, freshness_mode="challenge", monotonic_clock=lambda: now[0]
        )

        absent = bridge.publish_risk("WARNING")
        self.assertEqual(absent["collision_ffb_publish_success"], 0)
        self.assertEqual(absent["collision_ffb_active"], 0)
        self.assertEqual(ros_api.publisher.messages, [])

        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=17, token=42)
        )
        accepted = bridge.publish_risk("WARNING")
        self.assertEqual(accepted["collision_ffb_publish_success"], 1)
        sent = ros_api.publisher.messages[-1]
        self.assertEqual((sent.receiver_session_id, sent.receiver_token), (17, 42))
        self.assertEqual(
            accepted["collision_ffb_challenge_received_count"], 1
        )
        self.assertEqual(accepted["collision_ffb_challenge_session_id"], 17)
        self.assertEqual(accepted["collision_ffb_challenge_token"], 42)

        now[0] = 2.101
        stale = bridge.publish_risk("WARNING")
        self.assertEqual(stale["collision_ffb_publish_success"], 0)
        self.assertEqual(stale["collision_ffb_active"], 0)

    def test_challenge_sender_age_can_be_shorter_than_receiver_limit(self):
        now = [4.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api,
            freshness_mode="challenge",
            challenge_max_age_sec=0.06,
            monotonic_clock=lambda: now[0],
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=23, token=99)
        )
        now[0] = 4.059
        self.assertEqual(
            bridge.publish_risk("CLEAR")["collision_ffb_publish_success"], 1
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=23, token=100)
        )
        now[0] = 4.061
        self.assertEqual(
            bridge.publish_risk("CLEAR")["collision_ffb_publish_success"], 1
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=23, token=101)
        )
        now[0] = 4.122
        stale = bridge.publish_risk("CLEAR")
        self.assertEqual(stale["collision_ffb_publish_success"], 0)
        self.assertEqual(
            stale["collision_ffb_publish_error"],
            "no_recent_receiver_challenge",
        )
        self.assertEqual(
            stale["collision_ffb_challenge_recovery_reason"],
            "sender_age",
        )

    def test_challenge_token_is_used_at_most_once_by_sender(self):
        now = [5.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api, freshness_mode="challenge", monotonic_clock=lambda: now[0]
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=29, token=7)
        )

        first = bridge.publish_risk("CLEAR")
        second = bridge.publish_risk("CLEAR")

        self.assertEqual(first["collision_ffb_publish_success"], 1)
        self.assertEqual(second["collision_ffb_publish_success"], 0)
        self.assertEqual(
            second["collision_ffb_publish_error"],
            "receiver_challenge_already_used",
        )
        self.assertEqual(len(ros_api.publisher.messages), 1)

    def test_out_of_order_challenge_does_not_replace_latest_token(self):
        now = [6.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api, freshness_mode="challenge", monotonic_clock=lambda: now[0]
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=31, token=12)
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=31, token=11)
        )

        result = bridge.publish_risk("CLEAR")

        self.assertEqual(result["collision_ffb_challenge_received_count"], 2)
        self.assertEqual(result["collision_ffb_challenge_token"], 12)
        self.assertEqual(ros_api.publisher.messages[-1].receiver_token, 12)

    def test_challenge_recovery_cooldown_waits_for_queue_to_drain(self):
        now = [7.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api,
            cadence="triple",
            freshness_mode="challenge",
            challenge_max_age_sec=0.06,
            challenge_recovery_sec=0.1,
            monotonic_clock=lambda: now[0],
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=37, token=1)
        )
        now[0] = 7.061
        stale = bridge.publish_risk("WARNING")
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=37, token=2)
        )
        now[0] = 7.12
        cooling_down = bridge.publish_risk("WARNING")
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=37, token=3)
        )
        now[0] = 7.162
        recovered = bridge.publish_risk("WARNING")

        self.assertEqual(stale["collision_ffb_publish_success"], 0)
        self.assertEqual(
            cooling_down["collision_ffb_publish_error"],
            "receiver_challenge_recovery_cooldown",
        )
        self.assertEqual(recovered["collision_ffb_publish_success"], 1)
        self.assertEqual(recovered["collision_ffb_active"], 1)
        self.assertEqual(
            recovered["collision_ffb_reason"],
            "ttc_warning:cadence_triple",
        )

    def test_challenge_loss_does_not_restart_started_cadence(self):
        now = [8.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api,
            cadence="triple",
            freshness_mode="challenge",
            challenge_max_age_sec=0.06,
            challenge_recovery_sec=0.1,
            monotonic_clock=lambda: now[0],
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=41, token=1)
        )
        first = bridge.publish_risk("WARNING")
        now[0] = 8.07
        unavailable = bridge.publish_risk("WARNING")
        for token, received_at in enumerate(
            (8.09, 8.11, 8.13, 8.15, 8.17, 8.19, 8.21, 8.23, 8.25, 8.27, 8.29),
            start=2,
        ):
            now[0] = received_at
            ros_api.node.subscription_callback(
                SimpleNamespace(session_id=41, token=token)
            )
        now[0] = 8.305
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=41, token=13)
        )
        after_recovery = bridge.publish_risk("WARNING")

        self.assertEqual(first["collision_ffb_active"], 1)
        self.assertEqual(unavailable["collision_ffb_publish_success"], 0)
        self.assertEqual(after_recovery["collision_ffb_publish_success"], 1)
        self.assertEqual(after_recovery["collision_ffb_active"], 0)
        self.assertEqual(
            after_recovery["collision_ffb_reason"],
            "cadence_gap:triple",
        )

    def test_long_callback_gap_enters_recovery_before_using_token(self):
        now = [9.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api,
            freshness_mode="challenge",
            challenge_max_age_sec=0.06,
            challenge_recovery_sec=0.1,
            monotonic_clock=lambda: now[0],
        )
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=43, token=1)
        )
        self.assertEqual(
            bridge.publish_risk("CLEAR")["collision_ffb_publish_success"], 1
        )

        # The token is locally new, but the 167 ms callback gap matches the
        # observed live failure mode and must trigger backlog recovery.
        now[0] = 9.167
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=43, token=9)
        )
        delayed = bridge.publish_risk("WARNING")
        for token, received_at in enumerate(
            (9.187, 9.207, 9.227, 9.247, 9.267), start=10
        ):
            now[0] = received_at
            ros_api.node.subscription_callback(
                SimpleNamespace(session_id=43, token=token)
            )
        now[0] = 9.268
        recovered = bridge.publish_risk("WARNING")

        self.assertEqual(delayed["collision_ffb_publish_success"], 0)
        self.assertEqual(
            delayed["collision_ffb_publish_error"],
            "receiver_challenge_recovery_cooldown",
        )
        self.assertEqual(
            delayed["collision_ffb_challenge_recovery_reason"],
            "callback_gap",
        )
        self.assertAlmostEqual(
            delayed["collision_ffb_challenge_recovery_trigger_sec"],
            0.167,
        )
        self.assertEqual(recovered["collision_ffb_publish_success"], 1)
        self.assertEqual(recovered["collision_ffb_challenge_token"], 14)

    def test_challenge_settings_reject_values_above_safety_limit(self):
        for kwargs in (
            {"challenge_max_age_sec": 0.101},
            {"challenge_recovery_sec": 0.101},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    _bridge(
                        _RosApi(),
                        freshness_mode="challenge",
                        **kwargs,
                    )

    def test_challenge_executor_failure_fails_closed(self):
        ros_api = _RosApi()
        bridge = _bridge(ros_api, freshness_mode="challenge")
        ros_api.node.subscription_callback(
            SimpleNamespace(session_id=31, token=101)
        )
        bridge.executor_thread = _FailedExecutorThread()

        result = bridge.publish_risk("WARNING")

        self.assertEqual(result["collision_ffb_publish_success"], 0)
        self.assertEqual(result["collision_ffb_active"], 0)
        self.assertEqual(ros_api.publisher.messages, [])
        self.assertIn(
            "synthetic challenge executor failure",
            result["collision_ffb_publish_error"],
        )

    def test_verified_triple_schedule_matches_hardware_probe(self):
        self.assertEqual(
            build_cadence_schedule("triple", 0.5, 30.0),
            [
                True, True, True, False, False,
                True, True, True, False, False,
                True, True, True, False, False,
            ],
        )

    def test_triple_cadence_is_finite_and_does_not_retrigger_on_hold(self):
        now = [0.0]
        ros_api = _RosApi()
        bridge = _bridge(
            ros_api,
            cadence="triple",
            cadence_duration_sec=0.5,
            cadence_rate_hz=30.0,
            monotonic_clock=lambda: now[0],
        )

        records = []
        for index in range(15):
            now[0] = index / 30.0
            records.append(bridge.publish_risk("WARNING"))

        self.assertEqual(
            [row["collision_ffb_active"] for row in records],
            [1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0],
        )
        now[0] = 0.6
        completed = bridge.publish_risk("WARNING_HOLD")
        self.assertEqual(completed["collision_ffb_active"], 0)
        self.assertEqual(completed["collision_ffb_reason"], "cadence_complete")
        bridge.close()

    def test_unknown_is_one_finite_pulse_not_hazard_triple(self):
        now = [0.0]
        bridge = _bridge(
            _RosApi(),
            cadence="triple",
            cadence_duration_sec=0.5,
            cadence_rate_hz=30.0,
            unknown_pulse_duration_sec=0.1,
            monotonic_clock=lambda: now[0],
        )

        records = []
        for index in range(15):
            now[0] = index / 30.0
            records.append(bridge.publish_risk("UNKNOWN"))

        self.assertEqual(
            [row["collision_ffb_active"] for row in records],
            [1, 1, 1] + [0] * 12,
        )
        self.assertTrue(all(
            row["collision_ffb_reason"].endswith("cadence_single")
            for row in records[:3]
        ))
        self.assertTrue(all(
            row["collision_ffb_reason"] == "unknown_pulse_complete"
            for row in records[3:]
        ))
        bridge.close()

    def test_unknown_to_warning_starts_hazard_triple(self):
        now = [1.0]
        bridge = _bridge(
            _RosApi(),
            cadence="triple",
            monotonic_clock=lambda: now[0],
        )

        unknown = bridge.publish_risk("UNKNOWN")
        now[0] = 1.2
        warning = bridge.publish_risk("WARNING")

        self.assertEqual(unknown["collision_ffb_pattern"], "pulse")
        self.assertEqual(
            unknown["collision_ffb_reason"],
            "invalid_or_unknown_perception:cadence_single",
        )
        self.assertEqual(warning["collision_ffb_pattern"], "steady")
        self.assertEqual(
            warning["collision_ffb_reason"],
            "ttc_warning:cadence_triple",
        )
        bridge.close()

    def test_clear_cancels_and_rearms_triple_cadence(self):
        now = [1.0]
        bridge = _bridge(
            _RosApi(),
            cadence="triple",
            monotonic_clock=lambda: now[0],
        )

        first = bridge.publish_risk("WARNING")
        now[0] = 1.04
        cleared = bridge.publish_risk("CLEAR")
        now[0] = 2.0
        restarted = bridge.publish_risk("WARNING")

        self.assertEqual(first["collision_ffb_active"], 1)
        self.assertEqual(cleared["collision_ffb_active"], 0)
        self.assertEqual(
            cleared["collision_ffb_reason"],
            "cadence_cancelled_by_clear",
        )
        self.assertEqual(restarted["collision_ffb_active"], 1)
        bridge.close()

    def test_critical_escalation_restarts_completed_cadence(self):
        now = [3.0]
        bridge = _bridge(
            _RosApi(),
            cadence="triple",
            monotonic_clock=lambda: now[0],
        )

        bridge.publish_risk("WARNING")
        now[0] = 3.6
        completed = bridge.publish_risk("WARNING")
        now[0] = 3.7
        critical = bridge.publish_risk("CRITICAL")

        self.assertEqual(completed["collision_ffb_active"], 0)
        self.assertEqual(critical["collision_ffb_active"], 1)
        self.assertEqual(
            critical["collision_ffb_requested_magnitude"],
            0.40,
        )
        bridge.close()

    def test_cadence_settings_reject_unsafe_values(self):
        for kwargs in (
            {"cadence": "other"},
            {"duration_sec": 0.51},
            {"rate_hz": 9.0},
            {"unknown_pulse_duration_sec": 0.101},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    CollisionFfbCadenceController(**kwargs)

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
