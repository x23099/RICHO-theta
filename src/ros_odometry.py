#!/usr/bin/env python3
"""Optional ROS 2 odometry bridge for the standalone BEV experiment GUI."""

from __future__ import annotations

import threading
import time

from ros_executor_thread import RosExecutorThread

try:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.executors import SingleThreadedExecutor
except ImportError:  # Keep recorded-video and non-ROS use available.
    rclpy = None
    Odometry = None
    SingleThreadedExecutor = None


class RosOdometryBridge:
    """Read the latest body-frame twist without coupling ROS to GUI code."""

    def __init__(
        self,
        topic,
        *,
        ros_api=None,
        message_type=None,
        executor_factory=None,
        monotonic_clock=time.monotonic,
        start_executor=True,
    ):
        self._ros = ros_api if ros_api is not None else rclpy
        self._message_type = message_type if message_type is not None else Odometry
        if self._ros is None or self._message_type is None:
            raise RuntimeError("ROS 2 rclpy/nav_msgs is not available")
        topic = str(topic).strip()
        if not topic:
            raise ValueError("odometry topic must not be empty")
        self.topic = topic
        self._monotonic_clock = monotonic_clock
        self._owns_rclpy = not self._ros.ok()
        self._sample_lock = threading.Lock()
        self.linear_mps = 0.0
        self.angular_radps = 0.0
        self.last_message_monotonic = None
        self.received_count = 0
        self.node = None
        self.executor_thread = None
        try:
            if self._owns_rclpy:
                self._ros.init(args=None)
            self.node = self._ros.create_node("bird_eye_experiment_odometry")
            self.subscription = self.node.create_subscription(
                self._message_type, topic, self._callback, 10
            )
            if start_executor:
                factory = executor_factory or SingleThreadedExecutor
                if factory is None:
                    raise RuntimeError(
                        "ROS 2 SingleThreadedExecutor is unavailable"
                    )
                self.executor_thread = RosExecutorThread(
                    factory(), self.node, name="bird-eye-odometry-executor"
                )
        except Exception:
            if self.executor_thread is not None:
                self.executor_thread.close()
                self.executor_thread = None
            if self.node is not None:
                self.node.destroy_node()
                self.node = None
            if self._owns_rclpy and self._ros.ok():
                self._ros.shutdown()
            raise

    def _callback(self, message):
        with self._sample_lock:
            self.linear_mps = float(message.twist.twist.linear.x)
            self.angular_radps = float(message.twist.twist.angular.z)
            self.last_message_monotonic = self._monotonic_clock()
            self.received_count += 1

    def spin_once(self):
        """Compatibility health check; callbacks run on the executor thread."""
        if self.executor_thread is not None:
            self.executor_thread.raise_if_failed()

    def sample(self):
        if self.executor_thread is not None:
            self.executor_thread.raise_if_failed()
        with self._sample_lock:
            if self.last_message_monotonic is None:
                return None
            return {
                "linear_mps": self.linear_mps,
                "angular_radps": self.angular_radps,
                "monotonic_time": self.last_message_monotonic,
                "received_count": self.received_count,
            }

    def close(self):
        if self.executor_thread is not None:
            self.executor_thread.close()
            self.executor_thread = None
        if self.node is not None:
            self.node.destroy_node()
            self.node = None
        if self._owns_rclpy and self._ros.ok():
            self._ros.shutdown()
