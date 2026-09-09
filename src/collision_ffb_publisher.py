#!/usr/bin/env python3
"""Optional ROS 2 publisher for device-independent collision FFB commands."""

from __future__ import annotations

import math

from virtual_ffb import VirtualFfbPolicy


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

try:
    import rclpy
    from oit_interfaces.msg import CollisionFfbCommand
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


class CollisionFfbPublisherBridge:
    """Publish risk states while keeping ROS optional for offline tools."""

    def __init__(
        self,
        topic="/collision/ffb_command",
        source="bird_eye",
        warning_magnitude=0.25,
        critical_magnitude=0.40,
        unknown_magnitude=0.15,
        *,
        ros_api=None,
        message_type=None,
        qos_profile=None,
    ):
        """Initialize one ROS publisher without accessing any FFB device."""
        self.topic = str(topic).strip()
        self.source = str(source).strip()
        if not self.topic:
            raise ValueError("collision FFB command topic must not be empty")
        if not self.source:
            raise ValueError("collision FFB source must not be empty")
        self.policy = VirtualFfbPolicy(
            warning_magnitude=warning_magnitude,
            critical_magnitude=critical_magnitude,
            unknown_magnitude=unknown_magnitude,
        )
        self.sequence = 0
        self.last_record = empty_publish_record(enabled=True)
        self._closed = False
        self._last_error = ""
        self._ros = ros_api if ros_api is not None else rclpy
        self._message_type = (
            message_type if message_type is not None else CollisionFfbCommand
        )
        if self._ros is None or self._message_type is None:
            raise RuntimeError(
                "ROS 2 rclpy/oit_interfaces is unavailable; build and source "
                "the FFB workspace before enabling collision FFB publishing: "
                f"{ROS_IMPORT_ERROR}"
            )

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
            "warning_magnitude": self.policy.warning_magnitude,
            "critical_magnitude": self.policy.critical_magnitude,
            "unknown_magnitude": self.policy.unknown_magnitude,
            "qos": {
                "history": "keep_last",
                "depth": 1,
                "reliability": "best_effort",
                "durability": "volatile",
            },
        }

    def publish_risk(self, risk_level):
        """Map and publish one risk state, returning its recording fields."""
        if self._closed:
            raise RuntimeError("collision FFB publisher is closed")
        if self.sequence > UINT64_MAX:
            raise RuntimeError("collision FFB sequence exhausted uint64 range")

        virtual_command = self.policy.command(risk_level)
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
