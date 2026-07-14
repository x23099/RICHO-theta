#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import math
import os
import sys
import threading
import time
from fractions import Fraction

import cv2
import numpy as np
import av
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
import aiohttp

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from std_msgs.msg import String, Int32, Float32

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc_stream")

# ROS 2 テレメトリ購読ノード
class TelemetryNode(Node):
    def __init__(self, odom_topic, mode_topic, page_delta_topic, battery_topic, imu_topic, pedal_topic):
        super().__init__("theta_driver_telemetry_node")
        
        self.speed_mps = 0.0
        self.linear_x = 0.0
        self.angular_z = 0.0
        self.gear_text = "N"
        self.battery_percent = 100.0
        self.battery_voltage = 16.8
        self.mode_text = "Manual"
        self.temperature_c = 0.0
        self.imu_lateral_g = 0.0
        self.imu_longitudinal_g = 0.0
        self.imu_yaw_rate = 0.0
        self.pedal_throttle = 0.0
        self.pedal_brake = 0.0
        self.has_imu = False
        
        # 購読設定
        self.create_subscription(Odometry, odom_topic, self.odom_callback, 10)
        self.create_subscription(String, mode_topic, self.mode_callback, 10)
        self.create_subscription(Int32, page_delta_topic, self.page_callback, 10)
        self.create_subscription(Imu, imu_topic, self.imu_callback, 10)
        self.create_subscription(Twist, pedal_topic, self.pedal_callback, 10)
        
        # ローカルパブリッシャー (Wi-Fi経由しないローカルROS 2用、バッファ詰まり防止のため depth=1)
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel_joy", 1)
        self.kobuki_cmd_pub = self.create_publisher(Twist, "/cmd_vel", 1)
        
        # バッテリーの購読 (トピックの型に合わせて自動分岐する簡易ロジック)
        if "core" in battery_topic:  # kobuki型
            from std_msgs.msg import Float32
            try:
                from kobuki_ros_interfaces.msg import SensorState
                self.create_subscription(SensorState, battery_topic, self.kobuki_battery_callback, 10)
            except ImportError:
                logger.warning("kobuki_ros_interfaces not found, trying Float32 fallback for battery")
                self.create_subscription(Float32, battery_topic, self.float_battery_callback, 10)
        else:
            self.create_subscription(Float32, battery_topic, self.float_battery_callback, 10)

    def publish_control(self, data):
        twist = Twist()
        twist.linear.x = float(data.get("linear_x", 0.0))
        twist.angular.z = float(data.get("angular_z", 0.0))
        self.cmd_pub.publish(twist)
        self.kobuki_cmd_pub.publish(twist)

    def odom_callback(self, msg):
        self.speed_mps = math.sqrt(msg.twist.twist.linear.x**2 + msg.twist.twist.linear.y**2)
        self.linear_x = msg.twist.twist.linear.x
        self.angular_z = msg.twist.twist.angular.z

    def mode_callback(self, msg):
        self.mode_text = msg.data

    def page_callback(self, msg):
        pass

    def float_battery_callback(self, msg):
        self.battery_voltage = float(msg.data)
        self.battery_percent = max(0.0, min(100.0, (self.battery_voltage - 14.0) / (16.8 - 14.0) * 100.0))

    def kobuki_battery_callback(self, msg):
        self.battery_voltage = float(msg.battery) / 10.0
        self.battery_percent = max(0.0, min(100.0, (self.battery_voltage - 14.0) / (16.8 - 14.0) * 100.0))

    def imu_callback(self, msg):
        gravity = 9.80665
        self.imu_longitudinal_g = float(msg.linear_acceleration.x) / gravity
        self.imu_lateral_g = float(msg.linear_acceleration.y) / gravity
        self.imu_yaw_rate = float(msg.angular_velocity.z)
        self.has_imu = True

    def pedal_callback(self, msg):
        val = msg.linear.x
        if val > 0.0:
            self.pedal_throttle = val
            self.pedal_brake = 0.0
        else:
            self.pedal_throttle = 0.0
            self.pedal_brake = -val

    def get_telemetry_dict(self):
        return {
            "speed_mps": self.speed_mps,
            "linear_x": self.linear_x,
            "angular_z": self.angular_z,
            "gear_text": self.gear_text,
            "battery_percent": self.battery_percent,
            "battery_voltage": self.battery_voltage,
            "mode_text": self.mode_text,
            "imu_longitudinal_g": self.imu_longitudinal_g,
            "imu_lateral_g": self.imu_lateral_g,
            "imu_yaw_rate": self.imu_yaw_rate,
            "has_imu": self.has_imu,
            "pedal_throttle": self.pedal_throttle,
            "pedal_brake": self.pedal_brake
        }

# モックのカメラキャプチャ
class MockCapture:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.frame_count = 0

    def isOpened(self):
        return True

    def read(self):
        self.frame_count += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        left_cx = int(self.width * 0.25)
        right_cx = int(self.width * 0.75)
        cy = int(self.height * 0.5)
        radius = int(min(self.width / 4.0, self.height / 2.0) * 0.9)

        frame[:] = (15, 15, 15)

        # 左右の魚眼円を描画
        cv2.circle(frame, (left_cx, cy), radius, (40, 80, 140), -1)
        cv2.circle(frame, (right_cx, cy), radius, (80, 50, 120), -1)
        cv2.circle(frame, (left_cx, cy), radius, (230, 230, 230), 3)
        cv2.circle(frame, (right_cx, cy), radius, (230, 230, 230), 3)

        # 動く特徴点（Visual SLAM等の模擬用）を描く
        move_angle = math.radians((self.frame_count * 3) % 360)
        px1 = int(left_cx + radius * 0.55 * math.cos(move_angle))
        py1 = int(cy + radius * 0.55 * math.sin(move_angle))
        px2 = int(right_cx + radius * 0.55 * math.cos(-move_angle))
        py2 = int(cy + radius * 0.55 * math.sin(-move_angle))

        cv2.circle(frame, (px1, py1), 18, (0, 255, 255), -1)
        cv2.circle(frame, (px2, py2), 18, (0, 255, 180), -1)

        cv2.putText(frame, "MOCK THETA SENDER (ZERO COPY)", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        return True, frame

# WebRTC 映像配信トラック (インプロセス・ゼロコピー)
class CameraVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, device, width, height, fps=24, is_mock=False):
        super().__init__()
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.is_mock = is_mock
        self.frame_count = 0
        self._start_time = None
        self._time_base = Fraction(1, 90000)

        self.latest_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        self.running = True
        self.cap = None

        if self.is_mock:
            self.cap = MockCapture(width, height)
        else:
            if str(device).isdigit():
                self.cap = cv2.VideoCapture(int(device), cv2.CAP_V4L2)
            else:
                self.cap = cv2.VideoCapture(str(device), cv2.CAP_V4L2)

            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)

            if not self.cap.isOpened():
                raise RuntimeError(f"Failed to open camera: {device}")

        # Start capture thread
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                self.latest_frame = frame
            else:
                time.sleep(0.01)

    async def recv(self):
        import time
        if self._start_time is None:
            self._start_time = time.time()

        t_next = self._start_time + (self.frame_count + 1) * (1.0 / self.fps)
        now = time.time()
        if now < t_next:
            await asyncio.sleep(t_next - now)

        self.frame_count += 1
        pts = int((time.time() - self._start_time) * 90000)
        time_base = self._time_base

        # Get latest frame safely (shallow copy is fine for read-only)
        frame = self.latest_frame.copy()

        # BGR -> YUV420p
        yuv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
        av_frame = av.VideoFrame.from_ndarray(yuv_frame, format="yuv420p")
        av_frame.pts = pts
        av_frame.time_base = time_base
        return av_frame

# ROS 2スピン用スレッド
def ros2_spin_thread(node):
    try:
        rclpy.spin(node)
    except Exception as e:
        logger.error(f"ROS 2 spin error: {e}")

async def run(args):
    rclpy.init()
    telemetry_node = TelemetryNode(
        args.odom_topic,
        args.mode_topic,
        args.page_delta_topic,
        args.battery_topic,
        args.imu_topic,
        args.pedal_topic
    )
    
    spin_thread = threading.Thread(target=ros2_spin_thread, args=(telemetry_node,), daemon=True)
    spin_thread.start()

    logger.info("Initializing WebRTC Connection (Zero-copy)...")
    video_track = CameraVideoTrack(
        device=args.device,
        width=args.cam_width,
        height=args.cam_height,
        fps=args.fps,
        is_mock=args.mock_camera
    )

    pc = RTCPeerConnection()
    
    from aiortc import RTCRtpSender
    transceiver = pc.addTransceiver(video_track, direction="sendonly")
    capabilities = RTCRtpSender.getCapabilities("video")
    vp8_codecs = [c for c in capabilities.codecs if c.name == "VP8"]
    if vp8_codecs:
        try:
            transceiver.setCodecPreferences(vp8_codecs)
            logger.info("Enforced VP8 codec preference for ultra-low latency")
        except Exception as e:
            logger.warning(f"Failed to set codec preferences: {e}")

    telemetry_channel = pc.createDataChannel("telemetry")
    logger.info("Created WebRTC DataChannel: telemetry")

    control_channel = pc.createDataChannel("control")
    logger.info("Created WebRTC DataChannel: control")

    @control_channel.on("message")
    def on_control_message(message):
        try:
            data = json.loads(message)
            telemetry_node.publish_control(data)
        except Exception as e:
            logger.warning(f"Error handling control message: {e}")

    channel_opened = False

    @telemetry_channel.on("open")
    def on_open():
        nonlocal channel_opened
        channel_opened = True
        logger.info("DataChannel 'telemetry' is open")

    @telemetry_channel.on("close")
    def on_close():
        nonlocal channel_opened
        channel_opened = False
        logger.info("DataChannel 'telemetry' is closed")

    bitrate_bps = 15000000  # 15Mbps
    if args.bitrate.endswith("M"):
        bitrate_bps = int(args.bitrate[:-1]) * 1000000
    elif args.bitrate.endswith("k"):
        bitrate_bps = int(args.bitrate[:-1]) * 1000

    def munge_sdp_bitrate(sdp, bps):
        kbps = int(bps / 1000)
        lines = sdp.split("\r\n")
        new_lines = []
        for line in lines:
            new_lines.append(line)
            if line.startswith("m=video"):
                new_lines.append(f"b=AS:{kbps}")
        return "\r\n".join(new_lines)

    offer = await pc.createOffer()
    munged_sdp = munge_sdp_bitrate(offer.sdp, bitrate_bps)
    offer = RTCSessionDescription(sdp=munged_sdp, type=offer.type)
    
    await pc.setLocalDescription(offer)
    logger.info(f"Gathering ICE candidates (Bitrate limit: {bitrate_bps/1000000:.1f} Mbps)...")
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)

    local_sdp = pc.localDescription
    receiver_url = f"http://{args.receiver_ip}:5002/offer"
    logger.info(f"Posting Offer to {receiver_url}...")

    payload = {
        "sdp": local_sdp.sdp,
        "type": local_sdp.type
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(receiver_url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"SDP offer rejected by receiver. Status: {response.status}")
                    return
                answer_data = await response.json()
                logger.info("Received SDP Answer")
                answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
                await pc.setRemoteDescription(answer)
                logger.info("WebRTC Session connected successfully!")
        except Exception as e:
            logger.error(f"Signaling failed: {e}")
            return

    try:
        while True:
            if pc.connectionState == "failed":
                logger.error("WebRTC connection failed. Stopping...")
                break

            if channel_opened:
                telemetry = telemetry_node.get_telemetry_dict()
                telemetry["timestamp"] = int(time.time() * 1000)
                try:
                    telemetry_channel.send(json.dumps(telemetry))
                except Exception as e:
                    logger.warning(f"DataChannel sending failed: {e}")

            await asyncio.sleep(1.0 / args.telemetry_hz)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down stream node...")
        await pc.close()
        telemetry_node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Integrated birds-eye-view WebRTC Streamer (Zero-copy)")
    parser.add_argument("--receiver-ip", default="127.0.0.1", help="Receiver IP address")
    parser.add_argument("--device", default="/dev/video0", help="Camera video device file or RTSP stream")
    parser.add_argument("--cam-width", type=int, default=1280)
    parser.add_argument("--cam-height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--bitrate", default="15M", help="VP8 transmission bitrate (e.g. 15M, 1500k)")
    parser.add_argument("--telemetry-hz", type=int, default=24, help="Frequency of telemetry updates")
    parser.add_argument("--mock-camera", action="store_true")
    
    # ROS 2 Topics
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--mode-topic", default="/handle/drive_mode")
    parser.add_argument("--page-delta-topic", default="/handle/page_delta")
    parser.add_argument("--battery-topic", default="/sensors/core")
    parser.add_argument("--imu-topic", default="/sensors/imu_data_raw")
    parser.add_argument("--pedal-topic", default="/cmd_vel")

    # X11 / UI backward compatibility (ignored but kept for shell script compatibility)
    parser.add_argument("--window-id", help="Ignored")
    parser.add_argument("--display", help="Ignored")
    parser.add_argument("--video-size", help="Ignored")

    args = parser.parse_args()
    asyncio.run(run(args))
