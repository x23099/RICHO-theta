#!/usr/bin/env python3
"""Optional ROS 2 publisher for device-independent collision FFB commands."""

from __future__ import annotations

import math
import time

from virtual_ffb import VirtualFfbCommand, VirtualFfbPolicy


FFB_RECORDING_FIELDS = (
    "collision_ffb_sequence",
    "collision_ffb_publish_enabled",
    "collision_ffb_publish_success",
    "collision_ffb_risk_level",
    "collision_ffb_active",
    "collision_ffb_requested_magnitude",
    "collision_ffb_pattern",
    "collision_ffb_reason",
    "collision_ffb_publish_error",
)

RISK_LEVEL_VALUES = {
    "CLEAR": 0,
    "PATH": 1,
    "WARNING": 2,
    "WARNING_HOLD": 3,
    "CRITICAL": 4,
    "UNKNOWN": 5,
}
PATTERN_VALUES = {
    "off": 0,
    "steady": 1,
    "steady_hold": 2,
    "pulse": 3,
}
UINT64_MAX = (1 << 64) - 1
CADENCE_NAMES = ("continuous", "double", "triple")
CADENCE_MAX_DURATION_SEC = 0.5
CADENCE_MIN_RATE_HZ = 10.0
CADENCE_MAX_RATE_HZ = 60.0

try:
    import rclpy
    from oit_interfaces.msg import CollisionFfbChallenge, CollisionFfbCommand
    from rclpy.qos import (
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )
    ROS_IMPORT_ERROR = None
except ImportError as error:  # Preserve offline analysis without ROS setup.
    rclpy = None
    CollisionFfbCommand = None
    CollisionFfbChallenge = None
    DurabilityPolicy = None
    HistoryPolicy = None
    QoSProfile = None
    ReliabilityPolicy = None
    ROS_IMPORT_ERROR = error


def empty_publish_record(*, enabled=False, risk_level=""):
    """Return a complete recording row for an absent publisher result."""
    return {
        "collision_ffb_sequence": "",
        "collision_ffb_publish_enabled": 1 if enabled else 0,
        "collision_ffb_publish_success": 0,
        "collision_ffb_risk_level": str(risk_level),
        "collision_ffb_active": 0,
        "collision_ffb_requested_magnitude": 0.0,
        "collision_ffb_pattern": "off",
        "collision_ffb_reason": "publisher_not_run",
        "collision_ffb_publish_error": "",
    }


def virtual_command_payload(command):
    """Convert one VirtualFfbCommand into the shared numeric schema."""
    risk_level = str(command.risk_level).strip().upper()
    pattern = str(command.pattern).strip().lower()
    if risk_level not in RISK_LEVEL_VALUES:
        raise ValueError(f"unsupported virtual FFB risk level: {risk_level!r}")
    if pattern not in PATTERN_VALUES:
        raise ValueError(f"unsupported virtual FFB pattern: {pattern!r}")
    magnitude = float(command.normalized_magnitude)
    if not math.isfinite(magnitude) or not 0.0 <= magnitude <= 1.0:
        raise ValueError(
            "virtual FFB magnitude must be finite and within 0..1"
        )
    return {
        "risk_level_name": risk_level,
        "risk_level": RISK_LEVEL_VALUES[risk_level],
        "pattern_name": pattern,
        "pattern": PATTERN_VALUES[pattern],
        "active": bool(command.active),
        "normalized_magnitude": magnitude,
        "reason": str(command.reason),
    }


def collision_command_qos():
    """Return the shared low-latency, non-persistent command QoS profile."""
    if QoSProfile is None:
        raise RuntimeError("ROS 2 QoS support is unavailable")
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )


def build_cadence_schedule(cadence, duration_sec, rate_hz):
    """Return the finite active schedule used by the verified probe."""
    cadence = str(cadence).strip().lower()
    if cadence not in CADENCE_NAMES:
        raise ValueError(f"unsupported collision FFB cadence: {cadence!r}")
    duration_sec = float(duration_sec)
    rate_hz = float(rate_hz)
    if (
        not math.isfinite(duration_sec)
        or duration_sec <= 0.0
        or duration_sec > CADENCE_MAX_DURATION_SEC
    ):
        raise ValueError(
            "collision FFB cadence duration must be within "
            f"(0, {CADENCE_MAX_DURATION_SEC:.1f}] seconds"
        )
    if (
        not math.isfinite(rate_hz)
        or rate_hz < CADENCE_MIN_RATE_HZ
        or rate_hz > CADENCE_MAX_RATE_HZ
    ):
        raise ValueError(
            "collision FFB cadence rate must be within "
            f"{CADENCE_MIN_RATE_HZ:.0f}..{CADENCE_MAX_RATE_HZ:.0f} Hz"
        )
    sample_count = max(1, int(round(duration_sec * rate_hz)))
    if cadence == "continuous":
        return [True] * sample_count
    pulse_count = 2 if cadence == "double" else 3
    return [
        ((index * pulse_count * 2) // sample_count) % 2 == 0
        for index in range(sample_count)
    ]


class CollisionFfbCadenceController:
    """Gate one collision alert into a finite, non-retriggering cadence."""

    def __init__(
        self,
        cadence="continuous",
        duration_sec=0.5,
        rate_hz=30.0,
        *,
        monotonic_clock=time.monotonic,
    ):
        """Validate timing and initialize the alert latch."""
        self.cadence = str(cadence).strip().lower()
        self.duration_sec = float(duration_sec)
        self.rate_hz = float(rate_hz)
        self.schedule = build_cadence_schedule(
            self.cadence,
            self.duration_sec,
            self.rate_hz,
        )
        self.monotonic_clock = monotonic_clock
        self.reset()

    def reset(self):
        """Re-arm the next alert entry and cancel an active cadence."""
        self.started_sec = None
        self.latched = False
        self.highest_alert_rank = 0

    def describe(self):
        """Return serializable cadence provenance."""
        return {
            "name": self.cadence,
            "duration_sec": self.duration_sec,
            "rate_hz": self.rate_hz,
            "sample_count": len(self.schedule),
            "active_sample_count": sum(self.schedule),
            "retrigger": "clear_or_critical_escalation",
        }

    @staticmethod
    def _inactive(reason):
        """Return an adapter-valid CLEAR command for a cadence gap."""
        return VirtualFfbCommand("CLEAR", False, 0.0, "off", reason)

    def command(self, risk_level, policy):
        """Return the current cadence command for one perception state."""
        base_command = policy.command(risk_level)
        level = base_command.risk_level
        if self.cadence == "continuous":
            return base_command
        if level in {"CLEAR", "PATH"}:
            was_latched = self.latched
            self.reset()
            if was_latched:
                return self._inactive("cadence_cancelled_by_clear")
            return base_command

        alert_rank = 2 if level == "CRITICAL" else 1
        now_sec = float(self.monotonic_clock())
        if not math.isfinite(now_sec):
            raise ValueError("collision FFB cadence clock must be finite")
        if not self.latched or alert_rank > self.highest_alert_rank:
            self.started_sec = now_sec
            self.latched = True
            self.highest_alert_rank = alert_rank

        elapsed_sec = max(0.0, now_sec - self.started_sec)
        sample_index = int(elapsed_sec * self.rate_hz)
        if sample_index >= len(self.schedule):
            return self._inactive("cadence_complete")
        if not self.schedule[sample_index]:
            return self._inactive(f"cadence_gap:{self.cadence}")
        return VirtualFfbCommand(
            base_command.risk_level,
            base_command.active,
            base_command.normalized_magnitude,
            base_command.pattern,
            f"{base_command.reason}:cadence_{self.cadence}",
        )


class CollisionFfbPublisherBridge:
    """Publish risk states while keeping ROS optional for offline tools."""

    def __init__(
        self,
        topic="/collision/ffb_command",
        source="bird_eye",
        warning_magnitude=0.25,
        critical_magnitude=0.40,
        unknown_magnitude=0.15,
        cadence="continuous",
        cadence_duration_sec=0.5,
        cadence_rate_hz=30.0,
        freshness_mode="clock",
        challenge_topic="/collision/ffb_challenge",
        challenge_max_age_sec=0.1,
        *,
        monotonic_clock=time.monotonic,
        ros_api=None,
        message_type=None,
        qos_profile=None,
        challenge_message_type=None,
    ):
        """Initialize one ROS publisher without accessing any FFB device."""
        self.topic = str(topic).strip()
        self.source = str(source).strip()
        if not self.topic:
            raise ValueError("collision FFB command topic must not be empty")
        if not self.source:
            raise ValueError("collision FFB source must not be empty")
        self.freshness_mode = str(freshness_mode).strip().lower()
        if self.freshness_mode not in {"clock", "challenge"}:
            raise ValueError("freshness_mode must be clock or challenge")
        self.challenge_topic = str(challenge_topic).strip()
        self.challenge_max_age_sec = float(challenge_max_age_sec)
        if self.freshness_mode == "challenge" and (
            not self.challenge_topic
            or not math.isfinite(self.challenge_max_age_sec)
            or self.challenge_max_age_sec <= 0.0
        ):
            raise ValueError("challenge topic and positive max age are required")
        self.policy = VirtualFfbPolicy(
            warning_magnitude=warning_magnitude,
            critical_magnitude=critical_magnitude,
            unknown_magnitude=unknown_magnitude,
        )
        self.cadence = CollisionFfbCadenceController(
            cadence=cadence,
            duration_sec=cadence_duration_sec,
            rate_hz=cadence_rate_hz,
            monotonic_clock=monotonic_clock,
        )
        self.sequence = 0
        self.last_record = empty_publish_record(enabled=True)
        self._closed = False
        self._last_error = ""
        self._ros = ros_api if ros_api is not None else rclpy
        self._message_type = (
            message_type if message_type is not None else CollisionFfbCommand
        )
        self._challenge_type = (
            challenge_message_type
            if challenge_message_type is not None else CollisionFfbChallenge
        )
        if self._ros is None or self._message_type is None:
            raise RuntimeError(
                "ROS 2 rclpy/oit_interfaces is unavailable; build and source "
                "the FFB workspace before enabling collision FFB publishing: "
                f"{ROS_IMPORT_ERROR}"
            )
        if self.freshness_mode == "challenge" and (
            self._challenge_type is None
            or not hasattr(self._message_type(), "receiver_token")
        ):
            raise RuntimeError(
                "challenge mode requires the rebuilt oit_interfaces on both PCs"
            )

        self._latest_challenge = None

        self._owns_rclpy = not self._ros.ok()
        self.node = None
        try:
            if self._owns_rclpy:
                self._ros.init(args=None)
            self.node = self._ros.create_node("bird_eye_collision_ffb")
            publisher_qos = (
                qos_profile
                if qos_profile is not None
                else collision_command_qos()
            )
            self.publisher = self.node.create_publisher(
                self._message_type,
                self.topic,
                publisher_qos,
            )
            self.challenge_subscription = None
            if self.freshness_mode == "challenge":
                self.challenge_subscription = self.node.create_subscription(
                    self._challenge_type,
                    self.challenge_topic,
                    self._on_challenge,
                    publisher_qos,
                )
        except Exception:
            if self.node is not None:
                self.node.destroy_node()
                self.node = None
            if self._owns_rclpy and self._ros.ok():
                self._ros.shutdown()
            raise

    def describe(self):
        """Return serializable publisher provenance for recording metadata."""
        return {
            "enabled": True,
            "topic": self.topic,
            "source": self.source,
            "freshness_mode": self.freshness_mode,
            "challenge_topic": (
                self.challenge_topic if self.freshness_mode == "challenge" else ""
            ),
            "warning_magnitude": self.policy.warning_magnitude,
            "critical_magnitude": self.policy.critical_magnitude,
            "unknown_magnitude": self.policy.unknown_magnitude,
            "cadence": self.cadence.describe(),
            "qos": {
                "history": "keep_last",
                "depth": 1,
                "reliability": "best_effort",
                "durability": "volatile",
            },
        }

    def _on_challenge(self, message):
        session_id = int(message.session_id)
        token = int(message.token)
        if session_id > 0 and token > 0:
            self._latest_challenge = (
                session_id, token, float(self.cadence.monotonic_clock())
            )

    def publish_risk(self, risk_level):
        """Map and publish one risk state, returning its recording fields."""
        if self._closed:
            raise RuntimeError("collision FFB publisher is closed")
        if self.sequence > UINT64_MAX:
            raise RuntimeError("collision FFB sequence exhausted uint64 range")

        if self.freshness_mode == "challenge":
            try:
                self._ros.spin_once(self.node, timeout_sec=0.0)
            except Exception as error:
                self._latest_challenge = None
                error_text = f"challenge_receive_error:{type(error).__name__}:{error}"
                if error_text != self._last_error:
                    print(f"[WARN] {error_text}")
                self._last_error = error_text
        virtual_command = self.cadence.command(risk_level, self.policy)
        payload = virtual_command_payload(virtual_command)
        sequence = self.sequence
        self.sequence += 1
        record = {
            "collision_ffb_sequence": sequence,
            "collision_ffb_publish_enabled": 1,
            "collision_ffb_publish_success": 0,
            "collision_ffb_risk_level": payload["risk_level_name"],
            "collision_ffb_active": 1 if payload["active"] else 0,
            "collision_ffb_requested_magnitude": payload[
                "normalized_magnitude"
            ],
            "collision_ffb_pattern": payload["pattern_name"],
            "collision_ffb_reason": payload["reason"],
            "collision_ffb_publish_error": "",
        }
        if self.freshness_mode == "challenge":
            challenge = self._latest_challenge
            now = float(self.cadence.monotonic_clock())
            if challenge is None or not 0.0 <= now - challenge[2] <= self.challenge_max_age_sec:
                self.cadence.reset()
                record.update(
                    collision_ffb_active=0,
                    collision_ffb_requested_magnitude=0.0,
                    collision_ffb_reason="challenge_unavailable",
                    collision_ffb_publish_error="no_recent_receiver_challenge",
                )
                self.last_record = record
                return dict(record)
        try:
            message = self._message_type()
            message.header.stamp = self.node.get_clock().now().to_msg()
            message.sequence = sequence
            message.source = self.source
            message.risk_level = payload["risk_level"]
            message.pattern = payload["pattern"]
            message.active = payload["active"]
            message.normalized_magnitude = payload["normalized_magnitude"]
            message.reason = payload["reason"]
            if self.freshness_mode == "challenge":
                message.receiver_session_id = challenge[0]
                message.receiver_token = challenge[1]
            self.publisher.publish(message)
            record["collision_ffb_publish_success"] = 1
            self._last_error = ""
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
            record["collision_ffb_publish_error"] = error_text
            if error_text != self._last_error:
                print(f"[WARN] Collision FFB publish failed: {error_text}")
            self._last_error = error_text
        self.last_record = record
        return dict(record)

    def close(self):
        """Publish CLEAR once, then release only resources owned here."""
        if self._closed:
            return
        try:
            if self.node is not None:
                self.publish_risk("CLEAR")
        finally:
            self._closed = True
            if self.node is not None:
                self.node.destroy_node()
                self.node = None
            if self._owns_rclpy and self._ros.ok():
                self._ros.shutdown()
