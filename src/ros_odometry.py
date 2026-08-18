#!/usr/bin/env python3
"""Optional ROS 2 odometry bridge for the standalone BEV experiment GUI."""

from __future__ import annotations

import time

try:
    import rclpy
    from nav_msgs.msg import Odometry
except ImportError:  # Keep recorded-video and non-ROS use available.
    rclpy = None
    Odometry = None


class RosOdometryBridge:
    """Read the latest body-frame twist without coupling ROS to GUI code."""

    def __init__(self, topic):
        if rclpy is None or Odometry is None:
            raise RuntimeError("ROS 2 rclpy/nav_msgs is not available")
        topic = str(topic).strip()
        if not topic:
            raise ValueError("odometry topic must not be empty")
        self.topic = topic
        self._owns_rclpy = not rclpy.ok()
        if self._owns_rclpy:
            rclpy.init(args=None)
        self.node = rclpy.create_node("bird_eye_experiment_odometry")
        self.subscription = self.node.create_subscription(
            Odometry, topic, self._callback, 10
        )
        self.linear_mps = 0.0
        self.angular_radps = 0.0
        self.last_message_monotonic = None

    def _callback(self, message):
        self.linear_mps = float(message.twist.twist.linear.x)
        self.angular_radps = float(message.twist.twist.angular.z)
        self.last_message_monotonic = time.monotonic()

    def spin_once(self):
        rclpy.spin_once(self.node, timeout_sec=0.0)

    def sample(self):
        if self.last_message_monotonic is None:
            return None
        return {
            "linear_mps": self.linear_mps,
            "angular_radps": self.angular_radps,
            "monotonic_time": self.last_message_monotonic,
        }

    def close(self):
        if self.node is not None:
            self.node.destroy_node()
            self.node = None
        if self._owns_rclpy and rclpy.ok():
            rclpy.shutdown()
