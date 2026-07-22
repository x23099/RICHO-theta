import sys
import argparse
import glob
import math
import os
import select
import signal
import threading
import time
import socket
import queue
import json
import logging
import asyncio
from fractions import Fraction
import aiohttp
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QObject, Signal, Slot
from PySide6.QtGui import QImage, QPixmap, QKeyEvent, QPainter, QColor, QPen, QFont, QPolygonF
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QHBoxLayout

# logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc_receive_ui")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(SCRIPT_DIR, "theta-env", "bin", "python")

if (
    os.path.exists(VENV_PYTHON)
    and os.path.abspath(sys.executable) != os.path.abspath(VENV_PYTHON)
    and os.environ.get("THETA_UI_NO_VENV") != "1"
):
    os.execv(VENV_PYTHON, [VENV_PYTHON, __file__] + sys.argv[1:])

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from std_msgs.msg import String, Int32, Float32
import socket
import queue
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPixmap, QKeyEvent, QPainter, QColor, QPen, QFont, QPolygonF
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QHBoxLayout

try:
    from evdev import InputDevice, ecodes
except ImportError:
    InputDevice = None
    ecodes = None

try:
    from kobuki_ros_interfaces.msg import SensorState
except ImportError:
    SensorState = None


def make_theta_view_map(
    in_w,
    in_h,
    out_w,
    out_h,
    yaw_deg,
    pitch_deg=0.0,
    fov_deg=100.0,
    front_lens="left",
    radius_scale=0.96,
    roll_deg=0.0,
):
    # 魚眼円の中心と半径を決める.
    radius = min(in_w / 4.0, in_h / 2.0) * radius_scale
    cy = in_h / 2.0

    if front_lens == "left":
        front_cx = in_w * 0.25
        back_cx = in_w * 0.75
    else:
        front_cx = in_w * 0.75
        back_cx = in_w * 0.25

    # 出力画像の座標を作る.
    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))

    # FOVから焦点距離を決める.
    fov = np.deg2rad(fov_deg)
    focal = (out_w / 2.0) / np.tan(fov / 2.0)

    # ピンホール画像の各画素を3D方向ベクトルにする.
    x = (xs - out_w / 2.0) / focal
    y = -(ys - out_h / 2.0) / focal
    z = np.ones_like(x)

    norm = np.sqrt(x * x + y * y + z * z)
    x /= norm
    y /= norm
    z /= norm

    # pitch(ピッチ)方向に回す.
    pitch = np.deg2rad(pitch_deg)
    y_ptr = np.cos(pitch) * y - np.sin(pitch) * z
    z_ptr = np.sin(pitch) * y + np.cos(pitch) * z

    # yaw方向に視線を回す.
    yaw = np.deg2rad(yaw_deg)
    world_x = np.cos(yaw) * x + np.sin(yaw) * z_ptr
    world_y = y_ptr
    world_z = -np.sin(yaw) * x + np.cos(yaw) * z_ptr

    # 前後レンズを方向で選ぶ.
    use_front = world_z >= 0.0
    cx = np.where(use_front, front_cx, back_cx)

    # 選んだ魚眼レンズのローカル座標に変換する.
    lens_x = np.where(use_front, world_x, -world_x)
    lens_y = world_y
    lens_z = np.where(use_front, world_z, -world_z)

    lens_z = np.clip(lens_z, -1.0, 1.0)

    # 魚眼中心からの角度を求める.
    theta = np.arccos(lens_z)
    sin_theta = np.sin(theta)

    # 等距離魚眼モデルで半径方向に投影する.
    r = radius * theta / (np.pi / 2.0)

    dx = np.zeros_like(theta)
    dy = np.zeros_like(theta)

    valid = sin_theta > 1e-6
    dx[valid] = lens_x[valid] / sin_theta[valid]
    dy[valid] = lens_y[valid] / sin_theta[valid]

    map_dx = r * dx
    map_dy = -r * dy

    # 画面の回転補正をする.
    roll = np.deg2rad(roll_deg)
    rot_x = np.cos(roll) * map_dx - np.sin(roll) * map_dy
    rot_y = np.sin(roll) * map_dx + np.cos(roll) * map_dy

    map_x = cx + rot_x
    map_y = cy + rot_y

    # レンズ範囲外は黒にする.
    invalid = theta > (np.pi / 2.0)
    map_x[invalid] = -1
    map_y[invalid] = -1

    return map_x.astype(np.float32), map_y.astype(np.float32)


def make_theta_bev_map(
    in_w,
    in_h,
    out_w,
    out_h,
    fov_deg=180.0,
    front_lens="left",
    radius_scale=0.96,
):
    # 魚眼円の中心と半径を決める.
    radius = min(in_w / 4.0, in_h / 2.0) * radius_scale
    cy = in_h / 2.0
    front_cx = in_w * 0.25 if front_lens == "left" else in_w * 0.75
    back_cx = in_w * 0.75 if front_lens == "left" else in_w * 0.25

    # 出力画像の各ピクセルの中心からの相対座標を求める.
    xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
    dx = xs - out_w / 2.0
    dy = ys - out_h / 2.0
    r_out = np.sqrt(dx * dx + dy * dy)
    r_max = min(out_w, out_h) / 2.0

    # 中心からの距離r_outを天頂角theta（真下からの角度）に変換する.
    # r_out = r_max のときに theta = fov_rad / 2 となるように等距離射影する.
    fov_rad = np.deg2rad(fov_deg)
    theta = (r_out / r_max) * (fov_rad / 2.0)
    phi = np.arctan2(-dx, -dy)  # 上方向が前方

    # 3Dワールド座標系（Z:前, X:右, Y:下）の方向ベクトルを計算する
    # 真下が theta = 0（中心）
    world_y = np.cos(theta)
    world_x = np.sin(theta) * np.sin(phi)
    world_z = np.sin(theta) * np.cos(phi)

    # 3Dベクトルを規格化
    norm = np.sqrt(world_x*world_x + world_y*world_y + world_z*world_z)
    norm = np.where(norm < 1e-6, 1.0, norm)
    world_x /= norm
    world_y /= norm
    world_z /= norm

    use_front = world_z >= 0.0
    cx = np.where(use_front, front_cx, back_cx)
    lens_x = np.where(use_front, world_x, -world_x)
    lens_y = world_y
    lens_z = np.clip(np.where(use_front, world_z, -world_z), -1.0, 1.0)

    # 魚眼中心からの角度を求める
    lens_theta = np.arccos(lens_z)
    sin_lens_theta = np.sin(lens_theta)

    # 等距離魚眼モデルで半径方向に投影する
    r = radius * lens_theta / (np.pi / 2.0)

    map_dx = np.zeros_like(lens_theta)
    map_dy = np.zeros_like(lens_theta)

    valid = sin_lens_theta > 1e-6
    map_dx[valid] = r[valid] * (lens_x[valid] / sin_lens_theta[valid])
    map_dy[valid] = -r[valid] * (lens_y[valid] / sin_lens_theta[valid])

    map_x = cx + map_dx
    map_y = cy + map_dy

    # レンズ範囲外は黒にする
    invalid = (lens_theta > (np.pi / 2.0)) | (r_out > r_max)
    map_x[invalid] = -1
    map_y[invalid] = -1

    return map_x.astype(np.float32), map_y.astype(np.float32)


class MockCapture:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.frame_count = 0

    def isOpened(self):
        return True

    def set(self, prop_id, value):
        return True

    def read(self):
        # 仮のDual-Fisheye風画像を作る.
        self.frame_count += 1

        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        left_cx = int(self.width * 0.25)
        right_cx = int(self.width * 0.75)
        cy = int(self.height * 0.5)
        radius = int(min(self.width / 4.0, self.height / 2.0) * 0.9)

        frame[:] = (15, 15, 15)

        # 左右の魚眼円を描く.
        cv2.circle(frame, (left_cx, cy), radius, (40, 80, 140), -1)
        cv2.circle(frame, (right_cx, cy), radius, (80, 50, 120), -1)

        cv2.circle(frame, (left_cx, cy), radius, (230, 230, 230), 3)
        cv2.circle(frame, (right_cx, cy), radius, (230, 230, 230), 3)

        # 方位線を描く.
        for angle in range(0, 360, 30):
            rad = math.radians(angle)

            lx = int(left_cx + radius * math.cos(rad))
            ly = int(cy + radius * math.sin(rad))
            rx = int(right_cx + radius * math.cos(rad))
            ry = int(cy + radius * math.sin(rad))

            cv2.line(frame, (left_cx, cy), (lx, ly), (110, 150, 210), 1)
            cv2.line(frame, (right_cx, cy), (rx, ry), (150, 120, 210), 1)

        # 動く点を描く.
        move_angle = math.radians((self.frame_count * 3) % 360)

        px1 = int(left_cx + radius * 0.55 * math.cos(move_angle))
        py1 = int(cy + radius * 0.55 * math.sin(move_angle))
        px2 = int(right_cx + radius * 0.55 * math.cos(-move_angle))
        py2 = int(cy + radius * 0.55 * math.sin(-move_angle))

        cv2.circle(frame, (px1, py1), 18, (0, 255, 255), -1)
        cv2.circle(frame, (px2, py2), 18, (0, 255, 180), -1)

        # 文字を描く.
        cv2.putText(
            frame,
            "MOCK THETA LEFT",
            (left_cx - 170, cy - radius - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            "MOCK THETA RIGHT",
            (right_cx - 180, cy - radius - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            "FRONT / SIDE / BACK UI PREVIEW",
            (40, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
        )

        return True, frame

    def release(self):
        pass


class OdomSpeedNode:
    def __init__(self):
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
        self.has_pose = False
        self.pose_x = 0.0
        self.pose_y = 0.0
        self.pose_yaw = 0.0
        self.path_points = []
        self.handle_limit_deg = 450.0

    def predict_path_points(self, prediction_time=3.5, dt=0.05):
        v_cmd = 0.0
        w_cmd = 0.0
        if hasattr(self, "ui_window") and self.ui_window is not None:
            v_cmd = getattr(self.ui_window, "cmd_linear_x", 0.0)
            w_cmd = getattr(self.ui_window, "cmd_angular_z", 0.0)

        v_odom = float(self.linear_x)
        w_odom = float(self.angular_z)

        # 動き出しラグ解消：指令値優先、なければオドメトリにフォールバック
        use_cmd = abs(v_cmd) >= 1e-4 or abs(w_cmd) >= 1e-4
        v = v_cmd if use_cmd else v_odom
        w = w_cmd if use_cmd else w_odom

        v_abs = abs(v)
        # 完全に停止している場合のみ処理をスキップ
        if v_abs < 1e-4 and abs(w) < 1e-4:
            return []

        # 1. アッカーマン特性（速度比例）を考慮した旋回角速度wの再計算
        if use_cmd:
            abs_cmd_w = abs(w)
            if abs_cmd_w > 1e-4:
                # G923操舵特性に基づく目標ヨー角
                target_yaw_deg = 90.0 * ((abs_cmd_w / 0.8) ** (1.0 / 0.60))
                target_yaw_deg = min(360.0, target_yaw_deg)
                target_yaw_rad = math.radians(target_yaw_deg)
                
                # 基準速度 0.8 m/s に対する比率を掛けることで、超低速時でも旋回半径を一定に維持する
                w_base = target_yaw_rad / prediction_time
                v_ref = 0.8
                w = math.copysign(w_base * (v_abs / v_ref), w)
            else:
                w = 0.0

        # 2. 低速時の死角対策：前方 1.5 メートルを確保するように予測時間を動的に延長
        min_distance = 1.5
        if v_abs > 1e-4:
            required_time = max(prediction_time, min_distance / v_abs)
            required_time = min(15.0, required_time)  # 無限ループ防止のため最大15秒に制限
        else:
            required_time = prediction_time

        x = 0.0
        y = 0.0
        yaw = 0.0
        points = []
        steps = int(required_time / dt)
        
        # 回り込みすぎ防止：最大100度 (約1.75 rad) に制限
        max_yaw_limit = math.radians(100.0)

        for _ in range(steps):
            x += v * math.cos(yaw) * dt
            y += v * math.sin(yaw) * dt
            yaw += w * dt
            points.append((x, y, yaw))
            if abs(yaw) >= max_yaw_limit:
                break
        return points

    def update_telemetry(self, data):
        self.speed_mps = float(data.get("speed_mps", 0.0))
        self.linear_x = float(data.get("linear_x", 0.0))
        self.angular_z = float(data.get("angular_z", 0.0))
        self.gear_text = str(data.get("gear_text", "N"))
        self.battery_percent = float(data.get("battery_percent", 100.0))
        self.battery_voltage = float(data.get("battery_voltage", 16.8))
        self.mode_text = str(data.get("mode_text", "Manual"))
        self.imu_longitudinal_g = float(data.get("imu_longitudinal_g", 0.0))
        self.imu_lateral_g = float(data.get("imu_lateral_g", 0.0))
        self.imu_yaw_rate = float(data.get("imu_yaw_rate", 0.0))
        self.has_imu = bool(data.get("has_imu", False))
        self.pedal_throttle = float(data.get("pedal_throttle", 0.0))
        self.pedal_brake = float(data.get("pedal_brake", 0.0))

class VideoLabel(QOpenGLWidget):
    def __init__(self, title):
        super().__init__()

        self.title = title
        self.image = None
        self.mutex = threading.Lock()

        # ラベルの見た目を設定する.
        self.setMinimumSize(120, 90)

    def set_cv_image(self, frame_bgr):
        with self.mutex:
            # 高速な参照渡しコピー
            self.image = frame_bgr.copy()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True) # バイリニア補間（GPU処理のため超高速）

        # 背景色を塗りつぶす
        painter.fillRect(self.rect(), QColor("#111111"))

        frame_bgr = None
        with self.mutex:
            frame_bgr = self.image

        if frame_bgr is not None:
            # BGRからRGBへの高速変換
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w

            qimg = QImage(
                frame_rgb.data,
                w,
                h,
                bytes_per_line,
                QImage.Format_RGB888,
            )

            # アスペクト比を維持した描画矩形の計算
            rect = self.rect()
            scale_w = rect.width() / w
            scale_h = rect.height() / h
            scale = min(scale_w, scale_h)

            draw_w = int(w * scale)
            draw_h = int(h * scale)
            draw_x = int((rect.width() - draw_w) / 2)
            draw_y = int((rect.height() - draw_h) / 2)

            target_rect = QRectF(draw_x, draw_y, draw_w, draw_h)
            
            # GPU側で自動的にテクスチャアップロードされて超高速描画されます
            painter.drawImage(target_rect, qimg)
        else:
            # 接続待ち時は白文字でタイトルを表示
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Arial", 16, QFont.Bold))
            painter.drawText(self.rect(), Qt.AlignCenter, self.title)

        painter.end()


class BEVVideoLabel(VideoLabel):
    def paintEvent(self, event):
        # まず通常のカメラ背景（GPU描画）を描画
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        # Kobukiの大きさ (半径約27px of 円形)
        kobuki_r = 27

        # Kobuki車体の描画 (透過ダークグレーにシルバー枠)
        painter.setPen(QPen(QColor(200, 200, 200, 255), 2))
        painter.setBrush(QColor(25, 25, 25, 220))
        painter.drawEllipse(QPointF(cx, cy), kobuki_r, kobuki_r)

        # 前方のバンパー目印 (上部120度の円弧)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(80, 255, 80, 200))
        painter.drawChord(
            int(cx - kobuki_r), int(cy - kobuki_r),
            int(kobuki_r * 2), int(kobuki_r * 2),
            30 * 16, 120 * 16
        )

        # カメラ位置 (中央の赤い丸)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 65, 125, 255))
        painter.drawEllipse(QPointF(cx, cy), 4, 4)
        
        painter.end()


class DashboardWidget(QWidget):
    def __init__(self, max_speed_kmh=120.0, max_rpm=9000.0, speed_scale=12.0):
        super().__init__()

        self.speed_mps = 0.0
        self.linear_x = 0.0
        self.gear_text = "--"

        self.mode_text = "MT"
        self.battery_percent = 0.0
        self.battery_voltage = 0.0

        self.max_speed_kmh = max_speed_kmh
        self.max_rpm = max_rpm
        self.speed_scale = speed_scale
        self.idle_rpm = 900.0

        # 背景を透過する.
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 3連メーター用に横長にする.
        # 枠とメーターを少し小さくして, 盤面ぎりぎりに収める.
        self.setFixedSize(585, 250)

    def set_status(
        self,
        speed_mps,
        linear_x,
        gear_text,
        battery_percent,
        battery_voltage,
        mode_text,
    ):
        self.speed_mps = speed_mps
        self.linear_x = linear_x
        self.gear_text = gear_text
        self.battery_percent = battery_percent
        self.battery_voltage = battery_voltage
        self.mode_text = str(mode_text).upper()
        self.update()

    def speed_value_to_angle(self, value, min_value, max_value):
        # スピードメーターは下を0度として, 時計回りに225度まで使う.
        ratio = (value - min_value) / (max_value - min_value)
        ratio = max(0.0, min(1.0, ratio))

        start_angle = 270.0
        sweep_angle = 225.0

        return start_angle - sweep_angle * ratio

    def tacho_value_to_angle(self, value, min_value, max_value):
        # タコメーター用の角度に変換する.
        ratio = (value - min_value) / (max_value - min_value)
        ratio = max(0.0, min(1.0, ratio))

        # 0が下側, 最大が右上付近になるようにする.
        start_angle = 270.0
        end_angle = 30.0

        return start_angle + (end_angle - start_angle) * ratio

    def battery_value_to_angle(self, percent_value):
        # バッテリーメーター用の角度に変換する.
        ratio = max(0.0, min(1.0, percent_value / 100.0))

        # 右下がE, 右上がF.
        start_angle = -65.0
        end_angle = 65.0

        return start_angle + (end_angle - start_angle) * ratio

    def point_on_circle(self, cx, cy, radius, angle_deg):
        # 円周上の座標を求める.
        rad = math.radians(angle_deg)
        x = cx + radius * math.cos(rad)
        y = cy - radius * math.sin(rad)
        return x, y

    def draw_speed_gauge(self, painter, cx, cy, radius, value):
        # 外側の影を描く.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawEllipse(
            int(cx - radius - 8),
            int(cy - radius - 8),
            int((radius + 8) * 2),
            int((radius + 8) * 2),
        )

        # 外枠を描く.
        painter.setPen(QPen(QColor(210, 210, 210), 4))
        painter.setBrush(QColor(18, 18, 18, 235))
        painter.drawEllipse(
            int(cx - radius),
            int(cy - radius),
            int(radius * 2),
            int(radius * 2),
        )

        # 内側を描く.
        painter.setPen(QPen(QColor(65, 65, 65), 2))
        painter.setBrush(QColor(5, 5, 5, 235))
        painter.drawEllipse(
            int(cx - radius + 12),
            int(cy - radius + 12),
            int((radius - 12) * 2),
            int((radius - 12) * 2),
        )

        min_value = 0.0
        max_value = self.max_speed_kmh
        major_step = 20.0
        minor_step = 5.0

        # 細かい目盛りを描く.
        current = min_value
        while current <= max_value + 0.001:
            if abs(current % major_step) > 1e-6:
                angle = self.speed_value_to_angle(current, min_value, max_value)

                outer_x, outer_y = self.point_on_circle(cx, cy, radius - 16, angle)
                inner_x, inner_y = self.point_on_circle(cx, cy, radius - 24, angle)

                painter.setPen(QPen(QColor(155, 155, 155), 2))
                painter.drawLine(
                    int(inner_x),
                    int(inner_y),
                    int(outer_x),
                    int(outer_y),
                )

            current += minor_step

        # 主目盛りと数字を描く.
        current = min_value
        while current <= max_value + 0.001:
            angle = self.speed_value_to_angle(current, min_value, max_value)

            outer_x, outer_y = self.point_on_circle(cx, cy, radius - 14, angle)
            inner_x, inner_y = self.point_on_circle(cx, cy, radius - 30, angle)

            painter.setPen(QPen(QColor(245, 245, 245), 4))
            painter.drawLine(
                int(inner_x),
                int(inner_y),
                int(outer_x),
                int(outer_y),
            )

            text_x, text_y = self.point_on_circle(cx, cy, radius - 47, angle)

            painter.setPen(QColor(245, 245, 245))
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(
                int(text_x - 20),
                int(text_y - 10),
                40,
                22,
                Qt.AlignCenter,
                f"{int(current)}",
            )

            current += major_step

        # 針を描く.
        needle_angle = self.speed_value_to_angle(value, min_value, max_value)
        needle_x, needle_y = self.point_on_circle(cx, cy, radius - 42, needle_angle)

        painter.setPen(QPen(QColor(255, 55, 45), 5))
        painter.drawLine(
            int(cx),
            int(cy),
            int(needle_x),
            int(needle_y),
        )

        # 中心を描く.
        painter.setPen(QPen(QColor(230, 230, 230), 2))
        painter.setBrush(QColor(35, 35, 35))
        painter.drawEllipse(int(cx - 13), int(cy - 13), 26, 26)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 70, 60))
        painter.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)

        # 単位を100の数字の下に描く.
        unit_angle = self.speed_value_to_angle(100.0, min_value, max_value)
        unit_x, unit_y = self.point_on_circle(cx, cy, radius - 47, unit_angle)

        painter.setPen(QColor(230, 230, 230))
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.drawText(
            int(unit_x - 34),
            int(unit_y + 30),
            56,
            18,
            Qt.AlignCenter,
            "km/h",
        )

    def draw_tacho_gauge(self, painter, cx, cy, radius, rpm_value):
        # 外側の影を描く.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawEllipse(
            int(cx - radius - 8),
            int(cy - radius - 8),
            int((radius + 8) * 2),
            int((radius + 8) * 2),
        )

        # 外枠を描く.
        painter.setPen(QPen(QColor(210, 210, 210), 4))
        painter.setBrush(QColor(18, 18, 18, 235))
        painter.drawEllipse(
            int(cx - radius),
            int(cy - radius),
            int(radius * 2),
            int(radius * 2),
        )

        # 白い盤面を描く.
        painter.setPen(QPen(QColor(65, 65, 65), 2))
        painter.setBrush(QColor(230, 230, 225, 240))
        painter.drawEllipse(
            int(cx - radius + 12),
            int(cy - radius + 12),
            int((radius - 12) * 2),
            int((radius - 12) * 2),
        )

        # 中心の黒い円を描く.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(12, 14, 16, 245))
        painter.drawEllipse(
            int(cx - radius + 68),
            int(cy - radius + 68),
            int((radius - 68) * 2),
            int((radius - 68) * 2),
        )

        min_value = 0.0
        max_value = self.max_rpm / 1000.0
        major_step = 1.0
        minor_step = 0.2
        red_zone_start = 7.5

        # 細かい目盛りを描く.
        current = min_value
        while current <= max_value + 0.001:
            if abs(current - round(current)) > 1e-6:
                angle = self.tacho_value_to_angle(current, min_value, max_value)

                outer_x, outer_y = self.point_on_circle(cx, cy, radius - 16, angle)
                inner_x, inner_y = self.point_on_circle(cx, cy, radius - 25, angle)

                if current >= red_zone_start:
                    tick_color = QColor(220, 45, 45)
                else:
                    tick_color = QColor(30, 30, 30)

                painter.setPen(QPen(tick_color, 2))
                painter.drawLine(
                    int(inner_x),
                    int(inner_y),
                    int(outer_x),
                    int(outer_y),
                )

            current += minor_step

        # 主目盛りと数字を描く.
        current = min_value
        while current <= max_value + 0.001:
            angle = self.tacho_value_to_angle(current, min_value, max_value)

            outer_x, outer_y = self.point_on_circle(cx, cy, radius - 14, angle)
            inner_x, inner_y = self.point_on_circle(cx, cy, radius - 32, angle)

            if current >= red_zone_start:
                tick_color = QColor(220, 45, 45)
            else:
                tick_color = QColor(20, 20, 20)

            painter.setPen(QPen(tick_color, 4))
            painter.drawLine(
                int(inner_x),
                int(inner_y),
                int(outer_x),
                int(outer_y),
            )

            text_x, text_y = self.point_on_circle(cx, cy, radius - 49, angle)

            painter.setPen(QColor(20, 20, 20))
            painter.setFont(QFont("Arial", 13, QFont.Bold))
            painter.drawText(
                int(text_x - 22),
                int(text_y - 12),
                44,
                24,
                Qt.AlignCenter,
                f"{int(current)}",
            )

            current += major_step

        # 針を描く.
        needle_angle = self.tacho_value_to_angle(rpm_value / 1000.0, min_value, max_value)
        needle_x, needle_y = self.point_on_circle(cx, cy, radius - 45, needle_angle)

        painter.setPen(QPen(QColor(255, 55, 45), 5))
        painter.drawLine(
            int(cx),
            int(cy),
            int(needle_x),
            int(needle_y),
        )

        # 中心を描く.
        painter.setPen(QPen(QColor(230, 230, 230), 2))
        painter.setBrush(QColor(35, 35, 35))
        painter.drawEllipse(int(cx - 14), int(cy - 14), 28, 28)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 70, 60))
        painter.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)

        # 表記を中央の黒い円の中に描く.
        painter.setPen(QColor(230, 230, 230))
        painter.setFont(QFont("Arial", 7, QFont.Bold))
        painter.drawText(
            int(cx - 48),
            int(cy - 30),
            96,
            19,
            Qt.AlignCenter,
            "x 1000r/min",
        )

    def draw_battery_gauge(self, painter, cx, cy, radius, battery_percent, battery_voltage):
        # 外側の影を描く.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawEllipse(
            int(cx - radius - 8),
            int(cy - radius - 8),
            int((radius + 8) * 2),
            int((radius + 8) * 2),
        )

        # 外枠を描く.
        painter.setPen(QPen(QColor(210, 210, 210), 4))
        painter.setBrush(QColor(18, 18, 18, 235))
        painter.drawEllipse(
            int(cx - radius),
            int(cy - radius),
            int(radius * 2),
            int(radius * 2),
        )

        # 内側を描く.
        painter.setPen(QPen(QColor(65, 65, 65), 2))
        painter.setBrush(QColor(5, 5, 5, 235))
        painter.drawEllipse(
            int(cx - radius + 12),
            int(cy - radius + 12),
            int((radius - 12) * 2),
            int((radius - 12) * 2),
        )

        # 左側にMODEを文字だけで描く.
        mode_center_x = cx - 32

        painter.setPen(QColor(220, 220, 220))
        painter.setFont(QFont("Arial", 7, QFont.Bold))
        painter.drawText(
            int(mode_center_x - 36),
            int(cy - 20),
            72,
            20,
            Qt.AlignCenter,
            "MODE",
        )

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 13, QFont.Bold))
        painter.drawText(
            int(mode_center_x - 36),
            int(cy + 1),
            72,
            30,
            Qt.AlignCenter,
            self.mode_text,
        )

        # 右側にバッテリー文字を寄せて描く.
        batt_center_x = cx + 30

        painter.setPen(QColor(220, 220, 220))
        painter.setFont(QFont("Arial", 7, QFont.Bold))
        painter.drawText(
            int(batt_center_x - 42),
            int(cy - 27),
            84,
            20,
            Qt.AlignCenter,
            "BATT",
        )

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        painter.drawText(
            int(batt_center_x - 42),
            int(cy - 4),
            84,
            24,
            Qt.AlignCenter,
            f"{battery_percent:.0f}%",
        )

        painter.setPen(QColor(170, 170, 170))
        painter.setFont(QFont("Arial", 7, QFont.Bold))
        painter.drawText(
            int(batt_center_x - 42),
            int(cy + 20),
            84,
            18,
            Qt.AlignCenter,
            f"{battery_voltage:.1f} V",
        )

        # 右側の縁に沿ったバッテリーメーターを描く.
        start_angle = -65.0
        end_angle = 65.0
        arc_radius = radius - 20

        # 背景トラックを描く.
        a = start_angle
        while a < end_angle:
            p1 = self.point_on_circle(cx, cy, arc_radius, a)
            p2 = self.point_on_circle(cx, cy, arc_radius, a + 2.0)

            painter.setPen(QPen(QColor(90, 90, 90), 5))
            painter.drawLine(
                int(p1[0]),
                int(p1[1]),
                int(p2[0]),
                int(p2[1]),
            )
            a += 2.0

        # 残量トラックを描く.
        battery_angle = self.battery_value_to_angle(battery_percent)
        a = start_angle
        while a < battery_angle:
            p1 = self.point_on_circle(cx, cy, arc_radius, a)
            p2 = self.point_on_circle(cx, cy, arc_radius, a + 2.0)

            painter.setPen(QPen(QColor(235, 235, 235), 5))
            painter.drawLine(
                int(p1[0]),
                int(p1[1]),
                int(p2[0]),
                int(p2[1]),
            )
            a += 2.0

        # 目盛りを描く.
        for percent in [0, 25, 50, 75, 100]:
            angle = self.battery_value_to_angle(percent)

            outer_x, outer_y = self.point_on_circle(cx, cy, radius - 12, angle)
            inner_x, inner_y = self.point_on_circle(cx, cy, radius - 30, angle)

            painter.setPen(QPen(QColor(220, 220, 220), 3))
            painter.drawLine(
                int(inner_x),
                int(inner_y),
                int(outer_x),
                int(outer_y),
            )

        # 針を描く.
        needle_angle = self.battery_value_to_angle(battery_percent)
        needle_outer_x, needle_outer_y = self.point_on_circle(cx, cy, radius - 16, needle_angle)
        needle_inner_x, needle_inner_y = self.point_on_circle(cx, cy, radius - 38, needle_angle)

        painter.setPen(QPen(QColor(255, 90, 70), 4))
        painter.drawLine(
            int(needle_inner_x),
            int(needle_inner_y),
            int(needle_outer_x),
            int(needle_outer_y),
        )

        # EとFを描く.
        fx, fy = self.point_on_circle(cx, cy, radius - 48, 62)
        ex, ey = self.point_on_circle(cx, cy, radius - 48, -62)

        painter.setPen(QColor(235, 235, 235))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(int(fx - 10), int(fy + 5), 20, 20, Qt.AlignCenter, "F")
        painter.drawText(int(ex - 10), int(ey + 5), 20, 20, Qt.AlignCenter, "E")

    def draw_mode_box(self, painter):
        # 左寄りの空きスペースにモード表示を描く.
        box_x = 285
        box_y = 236
        box_w = 170
        box_h = 38

        painter.setPen(QPen(QColor(90, 90, 90), 2))
        painter.setBrush(QColor(10, 10, 10, 180))
        painter.drawRoundedRect(box_x, box_y, box_w, box_h, 10, 10)

        painter.setPen(QColor(230, 230, 230))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(
            box_x,
            box_y,
            box_w,
            box_h,
            Qt.AlignCenter,
            f"MODE : {self.mode_text}",
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # クラスタ全体の薄い背景を描く.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 130))
        painter.drawRoundedRect(0, 0, w - 1, h - 1, 28, 28)

        actual_speed_kmh = abs(self.speed_mps) * 3.6

        # 表示速度はkm/h換算後に倍率を掛ける.
        display_speed_kmh = actual_speed_kmh * self.speed_scale
        display_speed_kmh = min(display_speed_kmh, self.max_speed_kmh)

        # 疑似RPMを作る.
        speed_ratio = min(display_speed_kmh / self.max_speed_kmh, 1.0)
        rpm = self.idle_rpm + speed_ratio * (self.max_rpm - self.idle_rpm)

        if display_speed_kmh < 0.2:
            rpm = 0.0

        # 3連メーターの位置を決める.
        # 枠を小さくした分, 各メーターも縮小して中央寄りにする.
        left_cx = 100
        center_cx = 292
        right_cx = 485

        side_cy = 148
        center_cy = 128

        # 左にスピードメーターを描く.
        # 先に描くので, 中央メーターの下側に回る.
        self.draw_speed_gauge(
            painter=painter,
            cx=left_cx,
            cy=side_cy,
            radius=86,
            value=display_speed_kmh,
        )

        # 右にバッテリーメーターを描く.
        # 先に描くので, 中央メーターの下側に回る.
        self.draw_battery_gauge(
            painter=painter,
            cx=right_cx,
            cy=side_cy,
            radius=86,
            battery_percent=self.battery_percent,
            battery_voltage=self.battery_voltage,
        )

        # 真ん中にタコメーターを描く.
        # 最後に描くことで一番上に表示する.
        self.draw_tacho_gauge(
            painter=painter,
            cx=center_cx,
            cy=center_cy,
            radius=112,
            rpm_value=rpm,
        )


class ClassicDashboardWidget(QWidget):
    PAGE_TRIP = 0
    PAGE_IMU = 1
    PAGE_PEDAL = 2

    def __init__(self, max_speed_kmh=120.0, max_rpm=9000.0, speed_scale=12.0, display_scale=0.663):
        super().__init__()

        self.speed_mps = 0.0
        self.linear_x = 0.0
        self.gear_text = "--"
        self.mode_text = "MT"
        self.battery_percent = 0.0
        self.battery_voltage = 0.0
        self.temperature_c = None
        self.throttle = 0.0
        self.brake = 0.0
        self.imu_lateral_g = 0.0
        self.imu_longitudinal_g = 0.0
        self.imu_yaw_rate = 0.0
        self.has_imu = False
        self.pedal_history = []
        self.max_pedal_history = 48
        self.last_pedal_sample_time = 0.0
        self.pose_x = 0.0
        self.pose_y = 0.0
        self.pose_yaw = 0.0
        self.path_points = []
        self.has_pose = False
        self.page = self.PAGE_TRIP

        self.max_speed_kmh = max_speed_kmh
        self.max_rpm = max_rpm
        self.speed_scale = speed_scale
        self.idle_rpm = 900.0
        self.logical_width = 980
        self.logical_height = 380
        self.display_scale = display_scale

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(
            int(self.logical_width * self.display_scale),
            int(self.logical_height * self.display_scale),
        )

    def set_status(
        self,
        speed_mps,
        linear_x,
        gear_text,
        battery_percent,
        battery_voltage,
        mode_text,
        temperature_c=None,
        throttle=0.0,
        brake=0.0,
        imu_lateral_g=0.0,
        imu_longitudinal_g=0.0,
        imu_yaw_rate=0.0,
        has_imu=False,
    ):
        self.speed_mps = speed_mps
        self.linear_x = linear_x
        self.gear_text = gear_text
        self.battery_percent = battery_percent
        self.battery_voltage = battery_voltage
        self.mode_text = str(mode_text).upper()
        self.temperature_c = temperature_c
        self.throttle = max(0.0, min(1.0, float(throttle)))
        self.brake = max(0.0, min(1.0, float(brake)))
        self.imu_lateral_g = max(-1.0, min(1.0, float(imu_lateral_g)))
        self.imu_longitudinal_g = max(-1.0, min(1.0, float(imu_longitudinal_g)))
        self.imu_yaw_rate = float(imu_yaw_rate)
        self.has_imu = bool(has_imu)
        now = time.time()
        if now - self.last_pedal_sample_time >= 0.06:
            self.pedal_history.insert(0, (self.throttle, self.brake))
            self.pedal_history = self.pedal_history[: self.max_pedal_history]
            self.last_pedal_sample_time = now
        self.update()

    def set_pose_data(self, x, y, yaw, path_points, has_pose):
        self.pose_x = x
        self.pose_y = y
        self.pose_yaw = yaw
        self.path_points = list(path_points)
        self.has_pose = has_pose
        self.update()

    def change_page(self, delta):
        self.page = (self.page + delta) % 3
        self.update()

    def value_to_angle(self, value, min_value, max_value, start_angle, end_angle):
        if max_value <= min_value:
            return start_angle
        ratio = (value - min_value) / (max_value - min_value)
        ratio = max(0.0, min(1.0, ratio))
        return start_angle + (end_angle - start_angle) * ratio

    def point_on_circle(self, cx, cy, radius, angle_deg):
        rad = math.radians(angle_deg)
        return cx + radius * math.cos(rad), cy - radius * math.sin(rad)

    def display_speed_kmh(self):
        return min(abs(self.speed_mps) * 3.6 * self.speed_scale, self.max_speed_kmh)

    def display_rpm(self):
        speed_kmh = self.display_speed_kmh()
        if speed_kmh < 0.2:
            return 0.0
        ratio = min(speed_kmh / max(1.0, self.max_speed_kmh), 1.0)
        return self.idle_rpm + ratio * (self.max_rpm - self.idle_rpm)

    def trip_distance_m(self):
        if len(self.path_points) < 2:
            return 0.0
        distance = 0.0
        last_x, last_y = self.path_points[0]
        for x, y in self.path_points[1:]:
            distance += math.hypot(x - last_x, y - last_y)
            last_x, last_y = x, y
        return distance

    def draw_outer_shell(self, painter, cx, cy, radius, band_color):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 210))
        painter.drawEllipse(int(cx - radius - 18), int(cy - radius - 18), int((radius + 18) * 2), int((radius + 18) * 2))

        painter.setPen(QPen(QColor(28, 28, 28), 10))
        painter.setBrush(QColor(18, 19, 18, 245))
        painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))

        # Photo-like outer layers: red glow, thick silver rim, then the wide number band.
        painter.setPen(QPen(QColor(255, 28, 38, 70), 14))
        painter.drawEllipse(int(cx - radius + 11), int(cy - radius + 11), int((radius - 11) * 2), int((radius - 11) * 2))
        painter.setPen(QPen(QColor(255, 40, 45), 4))
        painter.drawEllipse(int(cx - radius + 18), int(cy - radius + 18), int((radius - 18) * 2), int((radius - 18) * 2))
        painter.setPen(QPen(QColor(178, 176, 164), 10))
        painter.drawEllipse(int(cx - radius + 29), int(cy - radius + 29), int((radius - 29) * 2), int((radius - 29) * 2))

        painter.setPen(QPen(band_color, 44))
        painter.drawEllipse(int(cx - radius + 55), int(cy - radius + 55), int((radius - 55) * 2), int((radius - 55) * 2))

        painter.setPen(QPen(QColor(24, 24, 22), 5))
        painter.setBrush(QColor(0, 0, 0, 245))
        painter.drawEllipse(int(cx - radius + 94), int(cy - radius + 94), int((radius - 94) * 2), int((radius - 94) * 2))

    def draw_text_with_shadow(self, painter, rect, text, font, color, align=Qt.AlignCenter):
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0, 190))
        shadow = QRectF(rect)
        shadow.translate(2, 2)
        painter.drawText(shadow, align, text)
        painter.setPen(color)
        painter.drawText(rect, align, text)

    def draw_major_tick(self, painter, cx, cy, radius, angle, length=16):
        outer = self.point_on_circle(cx, cy, radius - 32, angle)
        inner = self.point_on_circle(cx, cy, radius - 32 - length, angle)
        painter.setPen(QPen(QColor(244, 224, 224), 8))
        painter.drawLine(int(inner[0]), int(inner[1]), int(outer[0]), int(outer[1]))
        painter.setPen(QPen(QColor(80, 76, 70), 2))
        painter.drawLine(int(inner[0]), int(inner[1]), int(outer[0]), int(outer[1]))

    def draw_minor_tick(self, painter, cx, cy, radius, angle, color=None):
        if color is None:
            color = QColor(238, 238, 228)
        outer = self.point_on_circle(cx, cy, radius - 34, angle)
        inner = self.point_on_circle(cx, cy, radius - 47, angle)
        painter.setPen(QPen(color, 2))
        painter.drawLine(int(inner[0]), int(inner[1]), int(outer[0]), int(outer[1]))

    def draw_needle(self, painter, cx, cy, radius, angle, color=QColor(245, 232, 232)):
        tip = self.point_on_circle(cx, cy, radius - 78, angle)
        tail = self.point_on_circle(cx, cy, 34, angle + 180.0)
        painter.setPen(QPen(QColor(0, 0, 0, 180), 8, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(tail[0]), int(tail[1]), int(tip[0]), int(tip[1]))
        painter.setPen(QPen(color, 6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(tail[0]), int(tail[1]), int(tip[0]), int(tip[1]))
        painter.setPen(QPen(QColor(26, 26, 24), 2))
        painter.setBrush(QColor(35, 35, 32))
        painter.drawEllipse(int(cx - 19), int(cy - 19), 38, 38)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(8, 8, 8))
        painter.drawEllipse(int(cx - 9), int(cy - 9), 18, 18)

    def draw_tachometer(self, painter, cx, cy, radius, rpm):
        self.draw_outer_shell(painter, cx, cy, radius, QColor(132, 55, 58))
        min_v = 0.0
        max_v = self.max_rpm / 1000.0
        start = 270.0
        end = 0.0
        value = 0.0
        while value <= max_v + 0.001:
            angle = self.value_to_angle(value, min_v, max_v, start, end)
            if abs(value - round(value)) < 0.001:
                self.draw_major_tick(painter, cx, cy, radius, angle)
                tx, ty = self.point_on_circle(cx, cy, radius - 64, angle)
                self.draw_text_with_shadow(
                    painter,
                    QRectF(tx - 22, ty - 15, 44, 30),
                    f"{int(round(value))}",
                    QFont("Arial", 16, QFont.Bold),
                    QColor(238, 228, 228),
                )
            else:
                color = QColor(255, 45, 45) if value >= 7.2 else QColor(236, 236, 226)
                self.draw_minor_tick(painter, cx, cy, radius, angle, color)
            value += 0.2

        self.draw_text_with_shadow(
            painter,
            QRectF(cx - 86, cy - 70, 172, 28),
            "x1000RPM",
            QFont("Arial", 13, QFont.Bold),
            QColor(230, 230, 224),
        )
        self.draw_small_temp_gauge(painter, cx + radius * 0.38, cy + radius * 0.42, radius * 0.28)
        angle = self.value_to_angle(rpm / 1000.0, min_v, max_v, start, end)
        self.draw_needle(painter, cx, cy, radius, angle)

    def draw_speedometer(self, painter, cx, cy, radius, speed_kmh):
        self.draw_outer_shell(painter, cx, cy, radius, QColor(96, 95, 82))
        min_v = 0.0
        max_v = self.max_speed_kmh
        start = 270.0
        end = 0.0
        value = min_v
        while value <= max_v + 0.001:
            angle = self.value_to_angle(value, min_v, max_v, start, end)
            if abs(value % 10.0) < 0.001:
                self.draw_major_tick(painter, cx, cy, radius, angle)
                tx, ty = self.point_on_circle(cx, cy, radius - 64, angle)
                self.draw_text_with_shadow(
                    painter,
                    QRectF(tx - 26, ty - 15, 52, 30),
                    f"{int(round(value))}",
                    QFont("Arial", 15, QFont.Bold),
                    QColor(238, 228, 228),
                )
            else:
                self.draw_minor_tick(painter, cx, cy, radius, angle)
            value += 2.0

        self.draw_text_with_shadow(
            painter,
            QRectF(cx - 52, cy - 70, 104, 26),
            "km/h",
            QFont("Arial", 14, QFont.Bold),
            QColor(230, 230, 224),
        )
        self.draw_small_battery_gauge(painter, cx + radius * 0.38, cy + radius * 0.42, radius * 0.28)
        angle = self.value_to_angle(speed_kmh, min_v, max_v, start, end)
        self.draw_needle(painter, cx, cy, radius, angle)

    def draw_small_temp_gauge(self, painter, cx, cy, radius):
        painter.setPen(QPen(QColor(216, 209, 190), 3))
        painter.setBrush(QColor(26, 26, 22, 245))
        painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))
        start = -90.0
        end = 0.0
        for value in range(20, 101, 10):
            angle = self.value_to_angle(value, 20.0, 100.0, start, end)
            outer = self.point_on_circle(cx, cy, radius - 8, angle)
            is_major = value in (20, 60, 100)
            inner = self.point_on_circle(cx, cy, radius - (18 if is_major else 14), angle)
            painter.setPen(QPen(QColor(236, 236, 226), 3 if is_major else 1))
            painter.drawLine(int(inner[0]), int(inner[1]), int(outer[0]), int(outer[1]))
        self.draw_text_with_shadow(
            painter,
            QRectF(cx + radius * 0.42, cy - 20, 24, 20),
            "H",
            QFont("Arial", 11, QFont.Bold),
            QColor(236, 226, 226),
        )
        temp = self.temperature_c
        if temp is None:
            temp = 20.0
        angle = self.value_to_angle(temp, 20.0, 100.0, start, end)
        tip = self.point_on_circle(cx, cy, radius - 10, angle)
        painter.setPen(QPen(QColor(245, 232, 232), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(cx), int(cy), int(tip[0]), int(tip[1]))
        painter.setBrush(QColor(8, 8, 8))
        painter.drawEllipse(int(cx - 9), int(cy - 9), 18, 18)
        self.draw_text_with_shadow(
            painter,
            QRectF(cx - 34, cy + radius * 0.22, 22, 22),
            "C",
            QFont("Arial", 11, QFont.Bold),
            QColor(236, 226, 226),
        )

    def draw_small_battery_gauge(self, painter, cx, cy, radius):
        painter.setPen(QPen(QColor(216, 209, 190), 3))
        painter.setBrush(QColor(26, 26, 22, 245))
        painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))
        start = -90.0
        end = 0.0
        for value in range(0, 101, 10):
            angle = self.value_to_angle(value, 0.0, 100.0, start, end)
            outer = self.point_on_circle(cx, cy, radius - 8, angle)
            is_major = value in (0, 50, 100)
            inner = self.point_on_circle(cx, cy, radius - (18 if is_major else 14), angle)
            painter.setPen(QPen(QColor(236, 236, 226), 3 if is_major else 1))
            painter.drawLine(int(inner[0]), int(inner[1]), int(outer[0]), int(outer[1]))
        self.draw_text_with_shadow(
            painter,
            QRectF(cx + radius * 0.42, cy - 20, 24, 20),
            "F",
            QFont("Arial", 11, QFont.Bold),
            QColor(236, 226, 226),
        )
        angle = self.value_to_angle(self.battery_percent, 0.0, 100.0, start, end)
        tip = self.point_on_circle(cx, cy, radius - 10, angle)
        painter.setPen(QPen(QColor(245, 232, 232), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(cx), int(cy), int(tip[0]), int(tip[1]))
        painter.setBrush(QColor(8, 8, 8))
        painter.drawEllipse(int(cx - 9), int(cy - 9), 18, 18)
        self.draw_text_with_shadow(
            painter,
            QRectF(cx - 34, cy + radius * 0.24, 22, 22),
            "E",
            QFont("Arial", 11, QFont.Bold),
            QColor(236, 226, 226),
        )

    def draw_center_screen(self, painter, x, y, w, h):
        painter.setPen(QPen(QColor(30, 34, 46), 3))
        painter.setBrush(QColor(4, 8, 17, 235))
        painter.drawRoundedRect(QRectF(x, y, w, h), 10, 10)
        painter.setPen(QPen(QColor(120, 156, 220, 130), 1))
        painter.drawRoundedRect(QRectF(x + 5, y + 5, w - 10, h - 10), 8, 8)

        titles = ["TRIP", "IMU", "PEDAL"]
        self.draw_text_with_shadow(painter, QRectF(x + 10, y + 10, w - 20, 24), titles[self.page], QFont("Arial", 13, QFont.Bold), QColor(220, 232, 255))
        painter.setPen(QPen(QColor(120, 156, 220, 90), 1))
        painter.drawLine(x + 18, y + 42, x + w - 18, y + 42)

        if self.page == self.PAGE_TRIP:
            distance = self.trip_distance_m()
            km = distance / 1000.0
            self.draw_text_with_shadow(painter, QRectF(x + 12, y + 64, w - 24, 54), f"{km:.3f}", QFont("Arial", 30, QFont.Bold), QColor(255, 255, 255))
            self.draw_text_with_shadow(painter, QRectF(x + 12, y + 120, w - 24, 24), "km since start", QFont("Arial", 10, QFont.Bold), QColor(172, 192, 226))
            self.draw_info_row(painter, x + 16, y + 174, "MODE", self.mode_text)
            self.draw_info_row(painter, x + 16, y + 216, "GEAR", self.gear_text)
        elif self.page == self.PAGE_IMU:
            if self.has_imu:
                lateral_g = self.imu_lateral_g
                longitudinal_g = self.imu_longitudinal_g
            else:
                lateral_g = self.speed_mps * 0.28 * math.sin(self.pose_yaw)
                longitudinal_g = max(-1.0, min(1.0, self.throttle - self.brake))
            self.draw_g_ball(painter, x + w * 0.5, y + 132, 62, lateral_g, longitudinal_g)
            yaw_text = f"{math.degrees(self.imu_yaw_rate):.1f} d/s" if self.has_imu else f"{math.degrees(self.pose_yaw):.0f} deg"
            self.draw_info_row(painter, x + 16, y + 210, "LAT", f"{lateral_g:+.2f} G")
            self.draw_info_row(painter, x + 16, y + 242, "LONG", f"{longitudinal_g:+.2f} G")
            self.draw_info_row(painter, x + 16, y + 274, "YAW", yaw_text)
        else:
            self.draw_pedal_history_graph(painter, x + 20, y + 62, w - 40, 190)

        for idx in range(3):
            dot_x = x + w * 0.5 + (idx - 1) * 18
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(230, 240, 255) if idx == self.page else QColor(80, 100, 130))
            painter.drawEllipse(int(dot_x - 4), int(y + h - 18), 8, 8)

    def draw_info_row(self, painter, x, y, label, value):
        painter.setPen(QColor(138, 166, 210))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(int(x), int(y), 54, 24, Qt.AlignLeft | Qt.AlignVCenter, label)
        painter.setPen(QColor(250, 250, 250))
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        painter.drawText(int(x + 62), int(y), 106, 24, Qt.AlignLeft | Qt.AlignVCenter, value)

    def draw_bar(self, painter, x, y, w, h, value, color, label):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(28, 35, 48))
        painter.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(x, y, w * value, h), 4, 4)
        painter.setPen(QColor(245, 248, 255))
        painter.setFont(QFont("Arial", 11, QFont.Bold))
        painter.drawText(QRectF(x + 8, y, w - 16, h), Qt.AlignVCenter | Qt.AlignLeft, label)
        painter.drawText(QRectF(x + 8, y, w - 16, h), Qt.AlignVCenter | Qt.AlignRight, f"{value * 100:.0f}%")

    def draw_pedal_history_graph(self, painter, x, y, w, h):
        top_label_h = 28
        bottom_label_h = 30
        graph_top = y + top_label_h + 10
        graph_bottom = y + h - bottom_label_h - 8
        center_y = (graph_top + graph_bottom) * 0.5
        graph_h = graph_bottom - graph_top
        max_bar_h = graph_h * 0.42

        self.draw_text_with_shadow(
            painter,
            QRectF(x, y, w, top_label_h),
            "ACCEL",
            QFont("Arial", 13, QFont.Bold),
            QColor(245, 248, 255),
        )
        self.draw_text_with_shadow(
            painter,
            QRectF(x, graph_bottom + 8, w, bottom_label_h),
            "BRAKE",
            QFont("Arial", 13, QFont.Bold),
            QColor(245, 248, 255),
        )

        painter.setPen(QPen(QColor(118, 155, 210, 120), 1))
        painter.drawLine(int(x + 6), int(center_y), int(x + w - 6), int(center_y))
        painter.drawLine(int(x + 8), int(graph_top), int(x + 8), int(graph_bottom))

        history = self.pedal_history
        if not history:
            history = [(self.throttle, self.brake)]

        bar_w = 4
        gap = 2
        start_x = x + 16
        max_samples = int((x + w - start_x - 8) / (bar_w + gap))
        for index, (throttle, brake) in enumerate(history[:max_samples]):
            bx = start_x + index * (bar_w + gap)
            throttle_h = max_bar_h * max(0.0, min(1.0, throttle))
            brake_h = max_bar_h * max(0.0, min(1.0, brake))

            if throttle_h > 1.0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(105, 186, 245))
                painter.drawRoundedRect(
                    QRectF(bx, center_y - throttle_h, bar_w, throttle_h),
                    1.5,
                    1.5,
                )

            if brake_h > 1.0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 106, 55))
                painter.drawRoundedRect(
                    QRectF(bx, center_y, bar_w, brake_h),
                    1.5,
                    1.5,
                )

    def draw_g_ball(self, painter, cx, cy, radius, lateral_g, longitudinal_g):
        painter.setPen(QPen(QColor(120, 156, 220), 2))
        painter.setBrush(QColor(10, 15, 28))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.setPen(QPen(QColor(80, 105, 145), 1))
        painter.drawLine(int(cx - radius), int(cy), int(cx + radius), int(cy))
        painter.drawLine(int(cx), int(cy - radius), int(cx), int(cy + radius))
        dot_x = cx + max(-1.0, min(1.0, lateral_g)) * radius * 0.75
        dot_y = cy - max(-1.0, min(1.0, longitudinal_g)) * radius * 0.75
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(245, 245, 255))
        painter.drawEllipse(QPointF(dot_x, dot_y), 8, 8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.display_scale, self.display_scale)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(
            QRectF(0, 0, self.logical_width - 1, self.logical_height - 1),
            36,
            36,
        )

        speed_kmh = self.display_speed_kmh()
        rpm = self.display_rpm()
        left_cx = 210
        right_cx = 770
        cy = 190
        radius = 170
        self.draw_tachometer(painter, left_cx, cy, radius, rpm)
        self.draw_speedometer(painter, right_cx, cy, radius, speed_kmh)
        self.draw_center_screen(painter, 390, 42, 200, 306)


class MiniMapWidget(QWidget):
    def __init__(
        self,
        width=230,
        height=230,
        scale=18.0,
        course_image="",
        origin_x=0.0,
        origin_y=0.0,
        image_zoom=1.0,
        image_offset_x=0.0,
        image_offset_y=0.0,
    ):
        super().__init__()

        self.pose_x = 0.0
        self.pose_y = 0.0
        self.pose_yaw = 0.0
        self.has_pose = False
        self.path_points = []

        self.scale = scale
        self.course_image = QPixmap()
        if course_image:
            self.course_image = QPixmap(course_image)
            if self.course_image.isNull():
                print(f"[WARN] Minimap course image could not be loaded: {course_image}")
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.image_zoom = image_zoom
        self.image_offset_x = image_offset_x
        self.image_offset_y = image_offset_y
        self.padding = 18

        self.setFixedSize(width, height)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_pose(self, x, y, yaw, path_points, has_pose):
        self.pose_x = x
        self.pose_y = y
        self.pose_yaw = yaw
        self.has_pose = has_pose
        self.path_points = list(path_points)
        self.update()

    def compute_auto_view(self):
        points = list(self.path_points)
        if self.has_pose:
            points.append((self.pose_x, self.pose_y))

        if not points:
            return 0.0, 0.0, self.scale

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5

        available_w = max(1, self.width() - self.padding * 2)
        available_h = max(1, self.height() - self.padding * 2)
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)

        fit_scale = min(available_w / span_x, available_h / span_y)
        view_scale = min(self.scale, fit_scale)
        return center_x, center_y, view_scale

    def world_to_screen(self, x, y, center_x, center_y, view_scale):
        px = self.width() * 0.5 + (x - center_x) * view_scale
        py = self.height() * 0.5 - (y - center_y) * view_scale
        return QPointF(px, py)

    def draw_course_background(self, painter):
        rect = self.rect().adjusted(8, 8, -8, -8)
        if self.course_image.isNull():
            painter.setPen(QPen(QColor(210, 210, 210, 70), 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, 12, 12)
            return

        image_w = self.course_image.width()
        image_h = self.course_image.height()
        fit_scale = min(rect.width() / image_w, rect.height() / image_h)
        draw_scale = fit_scale * max(0.05, self.image_zoom)
        draw_w = image_w * draw_scale
        draw_h = image_h * draw_scale
        draw_x = rect.center().x() - draw_w * 0.5 + self.image_offset_x
        draw_y = rect.center().y() - draw_h * 0.5 + self.image_offset_y
        target_rect = QRectF(draw_x, draw_y, draw_w, draw_h)

        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(target_rect, self.course_image, QRectF(self.course_image.rect()))
        painter.restore()

        painter.setPen(QPen(QColor(255, 255, 255, 90), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)

    def draw_pose_marker(self, painter, center_x, center_y, view_scale):
        pos = self.world_to_screen(self.pose_x, self.pose_y, center_x, center_y, view_scale)

        heading = self.pose_yaw
        front = QPointF(
            pos.x() + math.cos(heading) * 13.0,
            pos.y() - math.sin(heading) * 13.0,
        )
        left = QPointF(
            pos.x() + math.cos(heading + math.radians(135.0)) * 9.0,
            pos.y() - math.sin(heading + math.radians(135.0)) * 9.0,
        )
        right = QPointF(
            pos.x() + math.cos(heading - math.radians(135.0)) * 9.0,
            pos.y() - math.sin(heading - math.radians(135.0)) * 9.0,
        )

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QColor(255, 72, 64))
        painter.drawPolygon(QPolygonF([front, left, right]))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 225, 70))
        painter.drawEllipse(pos, 4.5, 4.5)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 125))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)

        self.draw_course_background(painter)

        if self.course_image.isNull():
            center_x, center_y, view_scale = self.compute_auto_view()
        else:
            center_x = self.origin_x
            center_y = self.origin_y
            view_scale = self.scale

        if len(self.path_points) >= 2:
            painter.setPen(QPen(QColor(255, 255, 255, 150), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            previous = self.world_to_screen(
                self.path_points[0][0],
                self.path_points[0][1],
                center_x,
                center_y,
                view_scale,
            )
            for x, y in self.path_points[1:]:
                current = self.world_to_screen(x, y, center_x, center_y, view_scale)
                painter.drawLine(previous, current)
                previous = current

            painter.setPen(QPen(QColor(70, 185, 255, 220), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            previous = self.world_to_screen(
                self.path_points[0][0],
                self.path_points[0][1],
                center_x,
                center_y,
                view_scale,
            )
            for x, y in self.path_points[1:]:
                current = self.world_to_screen(x, y, center_x, center_y, view_scale)
                painter.drawLine(previous, current)
                previous = current

        if self.has_pose:
            self.draw_pose_marker(painter, center_x, center_y, view_scale)

        painter.setPen(QPen(QColor(255, 65, 125), 4))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(3, 3, -4, -4), 15, 15)


class CenterViewWidget(QWidget):
    def __init__(
        self,
        width,
        height,
        rear_width,
        rear_height,
        max_speed_kmh,
        speed_scale,
        minimap_enabled,
        minimap_width,
        minimap_height,
        minimap_scale,
        minimap_course_image,
        minimap_origin_x,
        minimap_origin_y,
        minimap_image_zoom,
        minimap_image_offset_x,
        minimap_image_offset_y,
        aiformula_mode=False,
    ):
        super().__init__()

        self.video_label = VideoLabel("FRONT")
        self.rear_label = VideoLabel("BACK MIRROR")

        # 画面幅（フロント解像度）が小さい場合はメーターと俯瞰映像を縮小する
        if width <= 900:
            self.display_scale = 0.45
            self.bev_width = 200
        else:
            self.display_scale = 0.663
            self.bev_width = 300

        self.dashboard = ClassicDashboardWidget(
            max_speed_kmh=max_speed_kmh,
            speed_scale=speed_scale,
            display_scale=self.display_scale,
        )
        self.bev_label = BEVVideoLabel("BIRD'S-EYE VIEW")

        # ミニマップは表示しない.
        self.minimap = None
        self.aiformula_mode = aiformula_mode

        self.front_width = width
        self.front_height = height
        self.rear_width = rear_width
        self.rear_height = rear_height

        # UI全体を横長にする.
        # 正面映像は16:9のまま, 左右の黒帯は許可する.
        # モニターが小さい場合(1024x768等)を考慮し最小サイズを縮小
        self.setMinimumSize(
            900,
            700,
        )

        self.video_label.setParent(self)
        self.dashboard.setParent(self)

        # バックミラーと俯瞰映像(BEV)は非表示にする
        self.rear_label.setParent(self)
        self.rear_label.hide()
        self.bev_label.setParent(self)
        self.bev_label.hide()

        # オーバーレイを前面に出す.
        self.dashboard.raise_()

        self.setStyleSheet("background-color: #050505;")

    def resizeEvent(self, event):
        # 正面映像を16:9で大きく固定表示する.
        dash_w = self.dashboard.width()
        dash_h = self.dashboard.height()

        top_margin = 8
        gap = 8

        # 1450x800に近い16:9サイズ.
        target_video_w = 1334
        target_video_h = 750

        # ウィンドウが小さい場合だけ縮小する.
        available_w = self.width()
        available_h = self.height() - dash_h - gap - top_margin - 8

        scale_w = available_w / target_video_w
        scale_h = available_h / target_video_h
        
        if self.aiformula_mode:
            scale = min(1.0, scale_w, scale_h)
        else:
            scale = min(scale_w, scale_h)

        video_w = int(target_video_w * scale)
        video_h = int(target_video_h * scale)

        # 正面映像を上側中央に置く.
        video_x = int((self.width() - video_w) / 2)
        video_y = top_margin

        self.video_label.setGeometry(
            video_x,
            video_y,
            video_w,
            video_h,
        )

        # バックミラーは正面映像の上中央に置く.
        rear_x = int(video_x + (video_w - self.rear_width) / 2)
        rear_y = video_y + 12

        self.rear_label.setGeometry(
            rear_x,
            rear_y,
            self.rear_width,
            self.rear_height,
        )

        # メーターは正面映像の下の黒い領域の「左側」に寄せて置く.
        # フロントカメラの左端 (video_x) に合わせる
        dash_x = video_x
        dash_y = int(video_y + video_h + gap)

        self.dashboard.setGeometry(
            dash_x,
            dash_y,
            dash_w,
            dash_h,
        )

        # 俯瞰映像はフロントカメラの右端 (video_x + video_w) に揃え、
        # メーターと同じ高さ (dash_h) で表示する.
        bev_w = self.bev_width
        bev_h = dash_h
        bev_x = video_x + video_w - bev_w
        bev_y = dash_y

        self.bev_label.setGeometry(
            bev_x,
            bev_y,
            bev_w,
            bev_h,
        )

    def set_front_image(self, frame_bgr):
        self.video_label.set_cv_image(frame_bgr)

    def set_rear_image(self, frame_bgr):
        self.rear_label.set_cv_image(frame_bgr)

    def set_bev_image(self, frame_bgr):
        self.bev_label.set_cv_image(frame_bgr)

    def set_status(
        self,
        speed_mps,
        linear_x,
        gear_text,
        battery_percent,
        battery_voltage,
        mode_text,
        temperature_c=None,
        throttle=0.0,
        brake=0.0,
        imu_lateral_g=0.0,
        imu_longitudinal_g=0.0,
        imu_yaw_rate=0.0,
        has_imu=False,
    ):
        self.dashboard.set_status(
            speed_mps,
            linear_x,
            gear_text,
            battery_percent,
            battery_voltage,
            mode_text,
            temperature_c,
            throttle,
            brake,
            imu_lateral_g,
            imu_longitudinal_g,
            imu_yaw_rate,
            has_imu,
        )

    def set_minimap_pose(self, x, y, yaw, path_points, has_pose):
        # ミニマップは消すが, メーター内部のTRIP計算用にはposeを渡す.
        self.dashboard.set_pose_data(x, y, yaw, path_points, has_pose)

    def change_dashboard_page(self, delta):
        self.dashboard.change_page(delta)


class ControlBridgeNode(Node):
    def __init__(self, ui_window):
        super().__init__("theta_control_bridge_node")
        self.ui_window = ui_window
        # ハンコン入力トピックを購読する (depth=1 でパケット詰まりを防止)
        self.create_subscription(Twist, "/cmd_vel_joy", self.control_callback, 1)
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel_joy", 10)

    def control_callback(self, msg):
        data = {
            "linear_x": msg.linear.x,
            "angular_z": msg.angular.z
        }
        self.ui_window.cmd_linear_x = msg.linear.x
        self.ui_window.cmd_angular_z = msg.angular.z
        if hasattr(self.ui_window, "server_thread"):
            self.ui_window.server_thread.send_control_data(data)


class ReceiveSignals(QObject):
    frame_received = Signal(np.ndarray)
    telemetry_received = Signal(dict)
    latency_updated = Signal(float, float, str)

class WebRTCServerThread(threading.Thread):
    def __init__(self, signals):
        super().__init__(daemon=True)
        self.signals = signals
        self.loop = None
        self.pc = None
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.control_channel = None

    def send_control_data(self, data_dict):
        if self.control_channel and self.control_channel.readyState == "open":
            asyncio.run_coroutine_threadsafe(
                self._async_send(self.control_channel, json.dumps(data_dict)),
                self.loop
            )

    async def _async_send(self, channel, message):
        try:
            channel.send(message)
        except Exception as e:
            logger.warning(f"Failed to send control message: {e}")

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.start_server())

    async def start_server(self):
        app = web.Application()
        app.router.add_post("/offer", self.handle_offer)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 5002) # HTTP Signaling Port
        logger.info("Starting signaling server on port 5002...")
        await site.start()
        while True:
            await asyncio.sleep(3600)

    async def handle_offer(self, request):
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        self.pc = RTCPeerConnection()

        @self.pc.on("track")
        def on_track(track):
            logger.info(f"Video track received: {track.kind}")
            if track.kind == "video":
                asyncio.ensure_future(self.process_video(track))

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"DataChannel received: {channel.label}")
            if channel.label == "telemetry":
                @channel.on("message")
                def on_message(message):
                    try:
                        data = json.loads(message)
                        self.signals.telemetry_received.emit(data)
                    except Exception as e:
                        logger.error(f"Failed to parse telemetry DataChannel: {e}")
            elif channel.label == "control":
                self.control_channel = channel
                logger.info("DataChannel 'control' bound successfully")

        await self.pc.setRemoteDescription(offer)
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return web.Response(
            content_type="application/json",
            text=json.dumps({"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type})
        )

    async def process_video(self, track):
        recv_count = 0
        t_last = time.time()
        while True:
            try:
                frame = await track.recv()
                img = frame.to_ndarray(format="bgr24")
                with self.frame_lock:
                    self.latest_frame = img
                
                # FPS / タイムスタンプの簡易測定
                recv_count += 1
                now = time.time()
                if now - t_last >= 1.0:
                    fps = recv_count / (now - t_last)
                    self.signals.latency_updated.emit(0.0, fps, "sender")
                    recv_count = 0
                    t_last = now
            except Exception as e:
                logger.error(f"Video receive error: {e}")
                break

class ThetaDriverUI(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.start_time = time.time()
        
        # Keyboard steering controller simulation (WASD)
        self.keys_pressed = {
            Qt.Key_W: False,
            Qt.Key_A: False,
            Qt.Key_S: False,
            Qt.Key_D: False
        }
        self.cmd_linear_x = 0.0
        self.cmd_angular_z = 0.0
        self.show_path = not args.hide_path

        # ダミーのデータストア
        self.odom_node = OdomSpeedNode()

        # デフォルトのカメラパラメータとオフセット
        self.camera_height = 0.55
        self.camera_pitch_deg = 6.0
        self.car_offset_x = 0.0
        self.car_offset_z = 0.0

        # bird_eye_config.json があれば読み込んでパラメータを上書きする
        config_candidates = [
            "bird_eye_config.json",
            "src/bird_eye_config.json",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "bird_eye_config.json")
        ]
        for path in config_candidates:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        config = json.load(f)
                        self.camera_height = config.get("camera_height", self.camera_height)
                        self.camera_pitch_deg = config.get("pitch_deg", self.camera_pitch_deg)
                        self.car_offset_x = config.get("car_offset_x", self.car_offset_x)
                        self.car_offset_z = config.get("car_offset_z", self.car_offset_z)
                        logger.info(f"Loaded camera config from {path}: height={self.camera_height}, pitch={self.camera_pitch_deg}, offset_x={self.car_offset_x}, offset_z={self.car_offset_z}")
                        break
                except Exception as e:
                    logger.warning(f"Failed to load camera config from {path}: {e}")
        self.odom_node.ui_window = self
        
        # 指定された解像度 (デフォルト 1920x960) で展開マップを生成する
        self.in_w = args.cam_width
        self.in_h = args.cam_height
        
        # 各ビューの展開マップの初期化
        self.front_map = make_theta_view_map(
            self.in_w, self.in_h, args.front_width, args.front_height,
            yaw_deg=0.0, fov_deg=args.front_fov, front_lens=args.front_lens, roll_deg=args.roll
        )
        self.rear_map = make_theta_view_map(
            self.in_w, self.in_h, args.rear_width, args.rear_height,
            yaw_deg=180.0, fov_deg=args.rear_fov, front_lens=args.front_lens, roll_deg=args.roll
        )
        self.left_mirror_map = make_theta_view_map(
            self.in_w, self.in_h, args.mirror_width, args.mirror_height,
            yaw_deg=args.left_mirror_yaw, fov_deg=args.mirror_fov, front_lens=args.front_lens, roll_deg=args.roll
        )
        self.right_mirror_map = make_theta_view_map(
            self.in_w, self.in_h, args.mirror_width, args.mirror_height,
            yaw_deg=args.right_mirror_yaw, fov_deg=args.mirror_fov, front_lens=args.front_lens, roll_deg=args.roll
        )
        self.bev_map = make_theta_bev_map(
            self.in_w, self.in_h, out_w=300, out_h=251, fov_deg=180.0, front_lens=args.front_lens
        )
        
        self.init_ui()
        
        # WebRTC 受信エンジンの開始
        self.signals = ReceiveSignals()
        self.signals.telemetry_received.connect(self.update_telemetry)
        
        self.server_thread = WebRTCServerThread(self.signals)
        self.server_thread.start()

        # 映像表示更新用の定周期タイマー (24FPS = 約41ms)
        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.update_frame)
        self.video_timer.start(41)

        # モック速度用タイマー (デモ用)
        if args.mock_speed:
            self.input_timer = QTimer(self)
            self.input_timer.timeout.connect(self.update_input_state)
            self.input_timer.start(30)

    @Slot(dict)
    def update_telemetry(self, data):
        self.odom_node.update_telemetry(data)
        
        # DataChannel 遅延測定
        if "timestamp" in data:
            lat = (time.time() * 1000) - float(data["timestamp"])
            if not hasattr(self, "telemetry_latencies"):
                self.telemetry_latencies = []
            self.telemetry_latencies.append(lat)
            if len(self.telemetry_latencies) >= 30:
                avg_lat = sum(self.telemetry_latencies) / 30
                print(f"[LATENCY] Avg DataChannel Telemetry Latency (30 frames): {avg_lat:.1f} ms")
                self.telemetry_latencies = []

        # メーター表示の更新
        self.center_widget.dashboard.set_status(
            self.odom_node.speed_mps,
            self.odom_node.linear_x,
            self.odom_node.gear_text,
            self.odom_node.battery_percent,
            self.odom_node.battery_voltage,
            self.odom_node.mode_text,
            self.odom_node.temperature_c,
            self.odom_node.pedal_throttle,
            self.odom_node.pedal_brake,
            self.odom_node.imu_lateral_g,
            self.odom_node.imu_longitudinal_g,
            self.odom_node.imu_yaw_rate,
            self.odom_node.has_imu
        )

    def init_ui(self):
        self.setWindowTitle("THETA S Driver View with Classic Analog Cluster")
        self.setStyleSheet("background-color: #050505;")

        self.center_widget = CenterViewWidget(
            width=self.args.front_width,
            height=self.args.front_height,
            rear_width=self.args.rear_width,
            rear_height=self.args.rear_height,
            max_speed_kmh=self.args.max_speed,
            speed_scale=self.args.speed_scale,
            minimap_enabled=False,
            minimap_width=self.args.minimap_width,
            minimap_height=self.args.minimap_height,
            minimap_scale=self.args.minimap_scale,
            minimap_course_image=self.args.minimap_course_image,
            minimap_origin_x=self.args.minimap_origin_x,
            minimap_origin_y=self.args.minimap_origin_y,
            minimap_image_zoom=self.args.minimap_image_zoom,
            minimap_image_offset_x=self.args.minimap_image_offset_x,
            minimap_image_offset_y=self.args.minimap_image_offset_y,
            aiformula_mode=self.args.aiformula,
        )

        self.center_widget.setMinimumSize(self.args.front_width, self.args.front_height)

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        
        # 通常モード時はアライメント指定なし、aiformulaモード時は中央固定
        if self.args.aiformula:
            layout.addWidget(self.center_widget, alignment=Qt.AlignCenter)
        else:
            layout.addWidget(self.center_widget)

        self.setLayout(layout)

        if self.args.fullscreen:
            self.showFullScreen()
        else:
            self.resize(1650, 850)

    def update_input_state(self):
        if self.args.mock_speed:
            # 擬似的に時間経過で変化する速度を作る (テスト用)
            import time
            import math
            mock_speed_mps = 1.0 + 0.8 * math.sin(time.time() * 0.5)
            mock_linear_x = mock_speed_mps
            # 
            if mock_speed_mps < 0.2:
                mock_gear = "N"
            elif mock_speed_mps < 1.0:
                mock_gear = "1"
            elif mock_speed_mps < 1.8:
                mock_gear = "2"
            else:
                mock_gear = "3"

            self.center_widget.set_status(
                mock_speed_mps,
                mock_linear_x,
                mock_gear,
                self.odom_node.battery_percent,
                self.odom_node.battery_voltage,
                self.odom_node.mode_text,
                self.odom_node.temperature_c,
                min(1.0, mock_speed_mps / 2.7),
                0.0,
            )
            self.center_widget.set_minimap_pose(
                self.odom_node.pose_x,
                self.odom_node.pose_y,
                self.odom_node.pose_yaw,
                self.odom_node.path_points,
                self.odom_node.has_pose,
            )
            return

        # 通常時は設定されたROS2入力から速度, ギア, バッテリーを取得する.
        throttle = self.odom_node.pedal_throttle
        brake = self.odom_node.pedal_brake
        if self.g923_reader is not None:
            g923_throttle, g923_brake = self.g923_reader.get_pedals()
            if g923_throttle > 0.001 or g923_brake > 0.001:
                throttle, brake = g923_throttle, g923_brake

        self.center_widget.set_status(
            self.odom_node.speed_mps,
            self.odom_node.linear_x,
            self.odom_node.gear_text,
            self.odom_node.battery_percent,
            self.odom_node.battery_voltage,
            self.odom_node.mode_text,
            self.odom_node.temperature_c,
            throttle,
            brake,
            self.odom_node.imu_lateral_g,
            self.odom_node.imu_longitudinal_g,
            self.odom_node.imu_yaw_rate,
            self.odom_node.has_imu,
        )
        self.center_widget.set_minimap_pose(
            self.odom_node.pose_x,
            self.odom_node.pose_y,
            self.odom_node.pose_yaw,
            self.odom_node.path_points,
            self.odom_node.has_pose,
        )

        # Process WASD keyboard control
        self.process_keyboard_control()

    def process_keyboard_control(self):
        # Calculate speed and angular velocity based on W, A, S, D states
        target_v = 0.0
        target_w = 0.0

        if self.keys_pressed.get(Qt.Key_W, False):
            target_v = 0.35  # forward speed m/s
        elif self.keys_pressed.get(Qt.Key_S, False):
            target_v = -0.25 # backward speed m/s

        if self.keys_pressed.get(Qt.Key_A, False):
            target_w = 0.55  # turn left rad/s
        elif self.keys_pressed.get(Qt.Key_D, False):
            target_w = -0.55 # turn right rad/s

        any_key = any(self.keys_pressed.values())
        
        # Override cmd values and publish Twist if keyboard input is active or was active (to send stop command once)
        if any_key or getattr(self, '_had_keyboard_input', False):
            self.cmd_linear_x = target_v
            self.cmd_angular_z = target_w
            
            logger.info(f"[KEYBOARD-CONTROL] Command: linear_x={target_v:.2f} m/s, angular_z={target_w:.2f} rad/s")
            
            # Publish Twist message locally via bridge_node if available
            if hasattr(self, 'bridge_node') and self.bridge_node is not None:
                from geometry_msgs.msg import Twist
                msg = Twist()
                msg.linear.x = target_v
                msg.angular.z = target_w
                self.bridge_node.cmd_pub.publish(msg)

            if any_key:
                self._had_keyboard_input = True
            else:
                self._had_keyboard_input = False

    def draw_predicted_path_on_bev_view(self, bev_view):
        # 現在の速度指令から予測経路を取得する.
        points = self.odom_node.predict_path_points(prediction_time=3.5, dt=0.05)

        if len(points) < 2:
            return bev_view

        h, w = bev_view.shape[:2]
        cx = w / 2.0
        cy = h / 2.0
        r_max = min(w, h) / 2.0

        # カメラ高さ（床面投影 of パラメータ）
        camera_height = 0.5  # メートル
        import numpy as np
        import math
        fov_rad = np.deg2rad(180.0)

        screen_points = []

        for x, y, _ in points:
            d = math.sqrt(x*x + y*y)
            if d < 1e-3:
                screen_points.append((int(cx), int(cy)))
                continue

            # 等距離射影変換モデル
            # 真下からの天頂角 theta = atan(d / h)
            theta = math.atan2(d, camera_height)
            # 中心からの距離 r_out (ピクセル単位)
            r_out = r_max * (theta / (fov_rad / 2.0))

            # ROSの座標系: xが前方(上方向), yが左方向(左方向)
            u = cx - r_out * (y / d)
            v = cy - r_out * (x / d)

            if 0 <= u < w and 0 <= v < h:
                screen_points.append((int(u), int(v)))

        if len(screen_points) < 2:
            return bev_view

        pts = np.array(screen_points, dtype=np.int32).reshape((-1, 1, 2))

        # 半透明の太い走行予測帯（車幅に相当する厚み）を描く.
        overlay = bev_view.copy()
        import cv2
        cv2.polylines(
            overlay,
            [pts],
            isClosed=False,
            color=(180, 50, 0),
            thickness=40,
            lineType=cv2.LINE_AA,
        )
        bev_view = cv2.addWeighted(overlay, 0.35, bev_view, 0.65, 0)

        # 中心の明るい線を描く.
        cv2.polylines(
            bev_view,
            [pts],
            isClosed=False,
            color=(255, 120, 0),
            thickness=4,
            lineType=cv2.LINE_AA,
        )

        return bev_view

    def draw_predicted_path_on_front_view(self, front_view):
        # 現在の速度指令から予測経路を取得する.
        points = self.odom_node.predict_path_points(prediction_time=3.5, dt=0.05)

        if len(points) < 2:
            return front_view

        # ロボットの中心(0,0,0)を先頭に追加して、自車位置の足元からパスを描画する
        points = [(0.0, 0.0, 0.0)] + points

        h, w = front_view.shape[:2]

        # 3Dカメラ投影用パラメータの設定 (設定ファイルから読み込まれた値を使用)
        camera_height = getattr(self, 'camera_height', 0.55)
        pitch_offset = math.radians(getattr(self, 'camera_pitch_deg', 6.0))
        fov_rad = math.radians(self.args.front_fov)
        focal = (w / 2.0) / math.tan(fov_rad / 2.0)
        
        offset_x = getattr(self, 'car_offset_x', 0.0)
        offset_z = getattr(self, 'car_offset_z', 0.0)

        # 走行予測線を少し細め（車体幅約33cm相当）にするため、左右に 0.165m
        half_width = 0.165

        left_screen_points = []
        right_screen_points = []

        def project_point(x_p, y_p):
            # 1. カメラ座標系への変換
            X_c = offset_x - y_p   # カメラの右方向
            Y_c = -camera_height   # カメラの上方向
            Z_c = x_p - offset_z   # カメラの前方方向

            # 2. カメラの下向きチルト（ピッチ角）の適用
            cos_p = math.cos(pitch_offset)
            sin_p = math.sin(pitch_offset)
            
            Z_rot = Z_c * cos_p - Y_c * sin_p
            Y_rot = Z_c * sin_p + Y_c * cos_p
            X_rot = X_c

            # カメラの後方にある点は投影不可
            if Z_rot < 0.05:
                return None

            # 3. 2D画面座標への透視投影
            u = w / 2.0 + focal * (X_rot / Z_rot)
            v = h / 2.0 - focal * (Y_rot / Z_rot)
            return int(u), int(v)

        for x, y, yaw in points:
            # 左右の境界点を計算
            # xは前方(longitudinal), yは横方向(lateral, 左が正)
            x_l = x - half_width * math.sin(yaw)
            y_l = y + half_width * math.cos(yaw)

            x_r = x + half_width * math.sin(yaw)
            y_r = y - half_width * math.cos(yaw)

            # 画面上に投影
            pt_l = project_point(x_l, y_l)
            pt_r = project_point(x_r, y_r)

            # 画面内に収まる投影点のみ追加
            if pt_l is not None and 0 <= pt_l[0] < w and 0 <= pt_l[1] < h:
                left_screen_points.append(pt_l)
            if pt_r is not None and 0 <= pt_r[0] < w and 0 <= pt_r[1] < h:
                right_screen_points.append(pt_r)

        if len(left_screen_points) < 2 or len(right_screen_points) < 2:
            return front_view

        # ポリゴンを形成する点リスト (左境界を奥へ進み、右境界を手前に戻る)
        poly_points = left_screen_points + list(reversed(right_screen_points))
        pts = np.array(poly_points, dtype=np.int32).reshape((-1, 1, 2))

        # 描画用のオーバーレイを作成 (半透明描画のため)
        overlay = front_view.copy()

        # 1. パスの塗りつぶし (テスラ風の濃く均一な青色)
        # BGR: (240, 110, 0)
        cv2.fillPoly(overlay, [pts], color=(240, 110, 0))

        # オーバーレイをブレンド (不透明度 0.70)
        front_view = cv2.addWeighted(overlay, 0.70, front_view, 0.30, 0)

        return front_view

    def update_frame(self):
        # WebRTCスレッドから最新の画像フレームをスレッドセーフに取得する
        frame = None
        if hasattr(self, "server_thread") and self.server_thread is not None:
            with self.server_thread.frame_lock:
                if self.server_thread.latest_frame is not None:
                    frame = self.server_thread.latest_frame.copy()

        if frame is None:
            return # まだ映像が届いていない場合は何もしない

        # 1. フロントビュー展開
        interp = cv2.INTER_NEAREST if self.args.interpolation == "nearest" else cv2.INTER_LINEAR
        front_view = cv2.remap(
            frame,
            self.front_map[0],
            self.front_map[1],
            interpolation=interp,
            borderMode=cv2.BORDER_CONSTANT,
        )

        # 2. 俯瞰ビュー(BEV)展開
        bev_view = cv2.remap(
            frame,
            self.bev_map[0],
            self.bev_map[1],
            interpolation=interp,
            borderMode=cv2.BORDER_CONSTANT,
        )

        # 3. 走行予測線の描画
        if self.show_path:
            points = self.odom_node.predict_path_points(prediction_time=3.5, dt=0.05)
            front_view = self.draw_predicted_path_on_front_view(front_view)
            bev_view = self.draw_predicted_path_on_bev_view(bev_view)

        # 4. GUIへのセット
        self.center_widget.set_front_image(front_view)
        self.center_widget.set_bev_image(bev_view)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Q, Qt.Key_Escape):
            self.close()
        elif event.key() == Qt.Key_Left:
            self.center_widget.change_dashboard_page(-1)
        elif event.key() == Qt.Key_Right:
            self.center_widget.change_dashboard_page(1)
        elif event.key() in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D):
            self.keys_pressed[event.key()] = True
            self.process_keyboard_control()
        elif event.key() == Qt.Key_P:
            self.show_path = not self.show_path
            logger.info(f"Toggle path display: {self.show_path}")
        elif event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D) and not event.isAutoRepeat():
            self.keys_pressed[event.key()] = False
            self.process_keyboard_control()

    def closeEvent(self, event):
        if hasattr(self, "input_timer"):
            self.input_timer.stop()

        if hasattr(self, "server_thread"):
            logger.info("Stopping WebRTC connection...")
            if self.server_thread.pc is not None:
                try:
                    asyncio.run_coroutine_threadsafe(self.server_thread.pc.close(), self.server_thread.loop)
                except Exception as e:
                    logger.warning(f"Error closing RTCPeerConnection: {e}")

        event.accept()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--front-width", type=int, default=1120)
    parser.add_argument("--front-height", type=int, default=720)
    parser.add_argument("--front-fov", type=float, default=100.0)
    parser.add_argument("--rear-width", type=int, default=560)
    parser.add_argument("--rear-height", type=int, default=135)
    parser.add_argument("--rear-fov", type=float, default=110.0)
    parser.add_argument("--mirror-width", type=int, default=210)
    parser.add_argument("--mirror-height", type=int, default=250)
    parser.add_argument("--mirror-fov", type=float, default=90.0)
    parser.add_argument("--left-mirror-yaw", type=float, default=-135.0)
    parser.add_argument("--right-mirror-yaw", type=float, default=135.0)
    parser.add_argument("--front-lens", choices=["left", "right"], default="left")
    parser.add_argument("--roll", type=float, default=0.0)
    parser.add_argument("--max-speed", type=float, default=120.0)
    parser.add_argument("--speed-scale", type=float, default=12.0)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--aiformula", action="store_true", help="Run in aiformula mode with smaller window size constraints")
    parser.add_argument("--hide-path", action="store_true", help="Hide predicted path on startup")
    parser.add_argument("--interpolation", choices=["linear", "nearest"], default="linear")
    
    # Dummy args
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--cam-width", type=int, default=1920)
    parser.add_argument("--cam-height", type=int, default=960)
    parser.add_argument("--mock-camera", action="store_true")
    parser.add_argument("--mock-speed", action="store_true")
    
    parser.add_argument("--minimap-width", type=int, default=230)
    parser.add_argument("--minimap-height", type=int, default=230)
    parser.add_argument("--minimap-scale", type=float, default=22.0)
    parser.add_argument("--minimap-course-image", default="")
    parser.add_argument("--minimap-origin-x", type=float, default=0.0)
    parser.add_argument("--minimap-origin-y", type=float, default=0.0)
    parser.add_argument("--minimap-image-zoom", type=float, default=1.0)
    parser.add_argument("--minimap-image-offset-x", type=float, default=0.0)
    parser.add_argument("--minimap-image-offset-y", type=float, default=0.0)

    args = parser.parse_args()

    app = QApplication(sys.argv)
    
    # Disable V-Sync (swapInterval = 0) for ultra-low latency
    from PySide6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    logger.info("Disabled V-Sync (swapInterval = 0) for ultra-low latency")

    rclpy.init()

    window = ThetaDriverUI(args)
    window.show()

    # ROS 2スピンスレッドの開始 (ハンコンデータ中継用)
    bridge_node = ControlBridgeNode(window)
    window.bridge_node = bridge_node
    spin_thread = threading.Thread(target=rclpy.spin, args=(bridge_node,), daemon=True)
    spin_thread.start()

    signal.signal(signal.SIGINT, lambda signum, frame: window.close())

    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(100)

    try:
        sys.exit(app.exec())
    finally:
        try:
            rclpy.shutdown()
        except Exception:
            pass

if __name__ == "__main__":
    main()