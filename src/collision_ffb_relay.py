#!/usr/bin/env python3
"""Relay local collision intents with receiver-issued freshness tokens.

The relay is intentionally a separate process from the camera GUI.  It keeps
receiver challenge callbacks out of the image-processing event loop and only
forwards a command when both the local intent and challenge are fresh.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass

from collision_ffb_publisher import collision_command_qos


INTENT_MAX_AGE_SEC = 0.1
CHALLENGE_MAX_AGE_SEC = 0.1
FUTURE_TOLERANCE_SEC = 0.02
CHALLENGE_STABLE_MAX_SEC = 10.0

try:
    import rclpy
    from oit_interfaces.msg import CollisionFfbChallenge, CollisionFfbCommand
    from std_msgs.msg import String

    ROS_IMPORT_ERROR = None
except ImportError as error:  # Keep configuration/unit tests usable offline.
    rclpy = None
    CollisionFfbChallenge = None
    CollisionFfbCommand = None
    String = None
    ROS_IMPORT_ERROR = error


def _stamp_seconds(stamp) -> float:
    return float(stamp.sec) + float(stamp.nanosec) / 1_000_000_000.0


@dataclass(frozen=True)
class RelayDecision:
    accepted: bool
    reason: str
    receiver_session_id: int = 0
    receiver_token: int = 0
    intent_age_sec: float | None = None
    challenge_age_sec: float | None = None
    challenge_stable_age_sec: float | None = None
    challenge_received_count: int = 0


class CollisionFfbRelayGate:
    """Pure fail-closed freshness and single-use-token gate."""

    def __init__(
        self,
        *,
        expected_source="bird_eye",
        intent_max_age_sec=0.1,
        challenge_max_age_sec=0.06,
        challenge_stable_sec=1.0,
        future_tolerance_sec=FUTURE_TOLERANCE_SEC,
    ):
        self.expected_source = str(expected_source).strip()
        self.intent_max_age_sec = float(intent_max_age_sec)
        self.challenge_max_age_sec = float(challenge_max_age_sec)
        self.challenge_stable_sec = float(challenge_stable_sec)
        self.future_tolerance_sec = float(future_tolerance_sec)
        if not self.expected_source:
            raise ValueError("expected source must not be empty")
        if not 0.0 < self.intent_max_age_sec <= INTENT_MAX_AGE_SEC:
            raise ValueError("intent max age must be within (0, 0.1] seconds")
        if not 0.0 < self.challenge_max_age_sec <= CHALLENGE_MAX_AGE_SEC:
            raise ValueError(
                "challenge max age must be within (0, 0.1] seconds"
            )
        if (
            not math.isfinite(self.challenge_stable_sec)
            or not 0.0 <= self.challenge_stable_sec <= CHALLENGE_STABLE_MAX_SEC
        ):
            raise ValueError(
                "challenge stable duration must be within [0, 10] seconds"
            )
        if not 0.0 <= self.future_tolerance_sec <= FUTURE_TOLERANCE_SEC:
            raise ValueError("future tolerance must be within [0, 0.02] seconds")
        self.latest_challenge = None
        self.last_used_challenge = None
        self.challenge_received_count = 0
        self.challenge_stable_since = None
        self.last_challenge_received_monotonic = None

    def receive_challenge(self, message, received_monotonic: float) -> bool:
        session_id = int(message.session_id)
        token = int(message.token)
        received_monotonic = float(received_monotonic)
        if session_id <= 0 or token <= 0 or not math.isfinite(received_monotonic):
            return False
        latest = self.latest_challenge
        if latest is not None and latest[0] == session_id and token <= latest[1]:
            return False
        stream_restarted = (
            latest is None
            or latest[0] != session_id
            or self.last_challenge_received_monotonic is None
            or received_monotonic - self.last_challenge_received_monotonic
            > self.challenge_max_age_sec
        )
        if stream_restarted:
            self.challenge_stable_since = received_monotonic
        self.latest_challenge = (session_id, token, received_monotonic)
        self.last_challenge_received_monotonic = received_monotonic
        self.challenge_received_count += 1
        return True

    def authorize(
        self,
        intent,
        *,
        now_ros_sec: float,
        now_monotonic: float,
    ) -> RelayDecision:
        now_ros_sec = float(now_ros_sec)
        now_monotonic = float(now_monotonic)
        if not math.isfinite(now_ros_sec) or not math.isfinite(now_monotonic):
            return RelayDecision(False, "invalid_relay_clock")
        if str(intent.source) != self.expected_source:
            return RelayDecision(False, "unexpected_intent_source")
        try:
            intent_stamp_sec = _stamp_seconds(intent.header.stamp)
            intent_age_sec = now_ros_sec - intent_stamp_sec
        except (AttributeError, TypeError, ValueError, OverflowError):
            return RelayDecision(False, "invalid_intent_stamp")
        if not math.isfinite(intent_age_sec):
            return RelayDecision(False, "invalid_intent_age")
        if intent_age_sec < -self.future_tolerance_sec:
            return RelayDecision(
                False, "future_intent", intent_age_sec=intent_age_sec
            )
        if intent_age_sec > self.intent_max_age_sec:
            return RelayDecision(
                False, "stale_intent", intent_age_sec=intent_age_sec
            )

        try:
            magnitude = float(intent.normalized_magnitude)
        except (TypeError, ValueError):
            return RelayDecision(
                False, "invalid_intent_magnitude", intent_age_sec=intent_age_sec
            )
        if not math.isfinite(magnitude) or not 0.0 <= magnitude <= 1.0:
            return RelayDecision(
                False, "invalid_intent_magnitude", intent_age_sec=intent_age_sec
            )
        if (not bool(intent.active)) and magnitude != 0.0:
            return RelayDecision(
                False,
                "inactive_intent_has_magnitude",
                intent_age_sec=intent_age_sec,
            )

        challenge = self.latest_challenge
        if challenge is None:
            return RelayDecision(
                False, "no_receiver_challenge", intent_age_sec=intent_age_sec
            )
        session_id, token, received_monotonic = challenge
        challenge_age_sec = now_monotonic - received_monotonic
        challenge_stable_age_sec = (
            None
            if self.challenge_stable_since is None
            else now_monotonic - self.challenge_stable_since
        )
        if (
            not math.isfinite(challenge_age_sec)
            or challenge_age_sec < 0.0
            or challenge_age_sec > self.challenge_max_age_sec
        ):
            return RelayDecision(
                False,
                "stale_receiver_challenge",
                intent_age_sec=intent_age_sec,
                challenge_age_sec=challenge_age_sec,
                challenge_stable_age_sec=challenge_stable_age_sec,
                challenge_received_count=self.challenge_received_count,
            )
        if (
            challenge_stable_age_sec is None
            or not math.isfinite(challenge_stable_age_sec)
            or challenge_stable_age_sec < self.challenge_stable_sec
        ):
            return RelayDecision(
                False,
                "receiver_challenge_stream_not_stable",
                receiver_session_id=session_id,
                receiver_token=token,
                intent_age_sec=intent_age_sec,
                challenge_age_sec=challenge_age_sec,
                challenge_stable_age_sec=challenge_stable_age_sec,
                challenge_received_count=self.challenge_received_count,
            )
        if challenge[:2] == self.last_used_challenge:
            return RelayDecision(
                False,
                "receiver_challenge_already_used",
                intent_age_sec=intent_age_sec,
                challenge_age_sec=challenge_age_sec,
                challenge_stable_age_sec=challenge_stable_age_sec,
                challenge_received_count=self.challenge_received_count,
            )

        # Consume before publish.  A local publish exception cannot prove that
        # DDS delivered no bytes, so retrying the same nonce would be unsafe.
        self.last_used_challenge = challenge[:2]
        return RelayDecision(
            True,
            "authorized",
            receiver_session_id=session_id,
            receiver_token=token,
            intent_age_sec=intent_age_sec,
            challenge_age_sec=challenge_age_sec,
            challenge_stable_age_sec=challenge_stable_age_sec,
            challenge_received_count=self.challenge_received_count,
        )


class CollisionFfbRelay:
    """ROS wrapper around :class:`CollisionFfbRelayGate`."""

    def __init__(
        self,
        *,
        intent_topic="/collision/ffb_intent",
        command_topic="/collision/ffb_command",
        challenge_topic="/collision/ffb_challenge",
        diagnostic_topic="/collision/ffb_relay_diagnostics",
        expected_source="bird_eye",
        intent_max_age_sec=0.1,
        challenge_max_age_sec=0.06,
        challenge_stable_sec=1.0,
        monotonic_clock=time.monotonic,
        ros_api=None,
        command_type=None,
        challenge_type=None,
        diagnostic_type=None,
        qos_profile=None,
    ):
        topics = tuple(
            str(item).strip()
            for item in (
                intent_topic,
                command_topic,
                challenge_topic,
                diagnostic_topic,
            )
        )
        if not all(topics) or len(set(topics)) != len(topics):
            raise ValueError("relay topics must be non-empty and distinct")
        (
            self.intent_topic,
            self.command_topic,
            self.challenge_topic,
            self.diagnostic_topic,
        ) = topics
        self.monotonic_clock = monotonic_clock
        self.gate = CollisionFfbRelayGate(
            expected_source=expected_source,
            intent_max_age_sec=intent_max_age_sec,
            challenge_max_age_sec=challenge_max_age_sec,
            challenge_stable_sec=challenge_stable_sec,
        )
        self._ros = ros_api if ros_api is not None else rclpy
        self._command_type = command_type or CollisionFfbCommand
        self._challenge_type = challenge_type or CollisionFfbChallenge
        self._diagnostic_type = diagnostic_type or String
        if (
            self._ros is None
            or self._command_type is None
            or self._challenge_type is None
            or self._diagnostic_type is None
        ):
            raise RuntimeError(
                "ROS 2 rclpy/oit_interfaces is unavailable; build and source "
                f"the FFB workspace: {ROS_IMPORT_ERROR}"
            )
        self._owns_rclpy = not self._ros.ok()
        self.node = None
        self._closed = False
        self._last_rejection = ""
        try:
            if self._owns_rclpy:
                self._ros.init(args=None)
            self.node = self._ros.create_node("collision_ffb_intent_relay")
            qos = qos_profile if qos_profile is not None else collision_command_qos()
            self.publisher = self.node.create_publisher(
                self._command_type, self.command_topic, qos
            )
            self.diagnostic_publisher = self.node.create_publisher(
                self._diagnostic_type, self.diagnostic_topic, qos
            )
            self.challenge_subscription = self.node.create_subscription(
                self._challenge_type,
                self.challenge_topic,
                self._on_challenge,
                qos,
            )
            self.intent_subscription = self.node.create_subscription(
                self._command_type,
                self.intent_topic,
                self._on_intent,
                qos,
            )
        except Exception:
            self.close()
            raise

    def _now_ros_sec(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000.0

    def _on_challenge(self, message) -> None:
        self.gate.receive_challenge(message, self.monotonic_clock())

    @staticmethod
    def _finite_or_none(value):
        if value is None:
            return None
        value = float(value)
        return value if math.isfinite(value) else None

    def _publish_diagnostic(self, intent, decision, outcome) -> None:
        """Publish one machine-readable record for every intent disposition."""
        payload = {
            "schema_version": 1,
            "relay_ros_time_sec": self._now_ros_sec(),
            "intent_sequence": int(getattr(intent, "sequence", 0)),
            "intent_source": str(getattr(intent, "source", "")),
            "intent_active": bool(getattr(intent, "active", False)),
            "accepted": bool(decision.accepted and outcome == "forwarded"),
            "outcome": str(outcome),
            "reason": str(decision.reason),
            "intent_age_sec": self._finite_or_none(decision.intent_age_sec),
            "challenge_age_sec": self._finite_or_none(decision.challenge_age_sec),
            "challenge_stable_age_sec": self._finite_or_none(
                decision.challenge_stable_age_sec
            ),
            "challenge_stable_required_sec": self.gate.challenge_stable_sec,
            "challenge_received_count": int(
                decision.challenge_received_count
                or self.gate.challenge_received_count
            ),
            "receiver_session_id": int(decision.receiver_session_id),
            "receiver_token": int(decision.receiver_token),
        }
        message = self._diagnostic_type()
        message.data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            self.diagnostic_publisher.publish(message)
        except Exception as error:
            self.node.get_logger().error(
                "FFB relay diagnostic publish failed: "
                f"{type(error).__name__}: {error}"
            )

    def _on_intent(self, intent) -> None:
        decision = self.gate.authorize(
            intent,
            now_ros_sec=self._now_ros_sec(),
            now_monotonic=self.monotonic_clock(),
        )
        if not decision.accepted:
            if decision.reason != self._last_rejection:
                self.node.get_logger().warning(
                    f"FFB intent rejected: {decision.reason}"
                )
            self._last_rejection = decision.reason
            self._publish_diagnostic(intent, decision, "rejected")
            return
        message = self._command_type()
        message.header.stamp = self.node.get_clock().now().to_msg()
        message.sequence = int(intent.sequence)
        message.source = str(intent.source)
        message.risk_level = int(intent.risk_level)
        message.pattern = int(intent.pattern)
        message.active = bool(intent.active)
        message.normalized_magnitude = float(intent.normalized_magnitude)
        message.reason = str(intent.reason)
        message.receiver_session_id = decision.receiver_session_id
        message.receiver_token = decision.receiver_token
        try:
            self.publisher.publish(message)
            self._last_rejection = ""
            self._publish_diagnostic(intent, decision, "forwarded")
        except Exception as error:
            self.node.get_logger().error(
                f"FFB command publish failed: {type(error).__name__}: {error}"
            )
            self._publish_diagnostic(intent, decision, "command_publish_error")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.node is not None:
            self.node.destroy_node()
            self.node = None
        if self._owns_rclpy and self._ros is not None and self._ros.ok():
            self._ros.shutdown()


def positive_bounded_age(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 < parsed <= 0.1:
        raise argparse.ArgumentTypeError("must be within (0, 0.1]")
    return parsed


def nonnegative_stable_duration(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 10.0:
        raise argparse.ArgumentTypeError("must be within [0, 10]")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Relay fresh local FFB intents with receiver challenges"
    )
    parser.add_argument("--intent-topic", default="/collision/ffb_intent")
    parser.add_argument("--command-topic", default="/collision/ffb_command")
    parser.add_argument("--challenge-topic", default="/collision/ffb_challenge")
    parser.add_argument(
        "--diagnostic-topic", default="/collision/ffb_relay_diagnostics"
    )
    parser.add_argument("--expected-source", default="bird_eye")
    parser.add_argument(
        "--intent-max-age-sec", type=positive_bounded_age, default=0.1
    )
    parser.add_argument(
        "--challenge-max-age-sec", type=positive_bounded_age, default=0.06
    )
    parser.add_argument(
        "--challenge-stable-sec",
        type=nonnegative_stable_duration,
        default=1.0,
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    relay = CollisionFfbRelay(
        intent_topic=args.intent_topic,
        command_topic=args.command_topic,
        challenge_topic=args.challenge_topic,
        diagnostic_topic=args.diagnostic_topic,
        expected_source=args.expected_source,
        intent_max_age_sec=args.intent_max_age_sec,
        challenge_max_age_sec=args.challenge_max_age_sec,
        challenge_stable_sec=args.challenge_stable_sec,
    )
    print(
        "[INFO] Collision FFB relay started: "
        f"{args.intent_topic} -> {args.command_topic}; "
        f"challenge={args.challenge_topic}, "
        f"stable={args.challenge_stable_sec:.3f}s, "
        f"diagnostics={args.diagnostic_topic}",
        flush=True,
    )
    try:
        rclpy.spin(relay.node)
    except KeyboardInterrupt:
        pass
    finally:
        relay.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
