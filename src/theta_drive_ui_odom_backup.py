import sys
import argparse
import math
import time
import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import String, Int32
from kobuki_ros_interfaces.msg import SensorState

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QKeyEvent, QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QHBoxLayout


def make_theta_view_map(
    in_w,
    in_h,
    out_w,
    out_h,
    yaw_deg,
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

    # yaw方向に視線を回す.
    yaw = np.deg2rad(yaw_deg)
    world_x = np.cos(yaw) * x + np.sin(yaw) * z
    world_y = y
    world_z = -np.sin(yaw) * x + np.cos(yaw) * z

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


class OdomSpeedNode(Node):
    def __init__(
        self,
        odom_topic,
        gear_topic,
        gear_int_topic,
        battery_topic,
        mode_topic,
        mode_text,
        battery_empty_voltage,
        battery_full_voltage,
    ):
        super().__init__("theta_driver_ui_odom_node")

        self.speed_mps = 0.0
        self.linear_x = 0.0
        self.gear_text = "--"

        self.mode_text = mode_text.upper()
        self.battery_voltage = 0.0
        self.battery_percent = 0.0
        self.battery_empty_voltage = battery_empty_voltage
        self.battery_full_voltage = battery_full_voltage

        # /odomを購読する.
        self.odom_subscription = self.create_subscription(
            Odometry,
            odom_topic,
            self.odom_callback,
            10,
        )

        # /shift_gearを購読する.
        self.gear_subscription = None
        if gear_topic != "":
            self.gear_subscription = self.create_subscription(
                String,
                gear_topic,
                self.gear_callback,
                10,
            )

        # /handle/gearを購読する.
        self.gear_int_subscription = None
        if gear_int_topic != "":
            self.gear_int_subscription = self.create_subscription(
                Int32,
                gear_int_topic,
                self.gear_int_callback,
                10,
            )

        # ハンコン側のMT/AT切り替え状態を購読する.
        self.mode_subscription = None
        if mode_topic != "":
            self.mode_subscription = self.create_subscription(
                String,
                mode_topic,
                self.mode_callback,
                10,
            )

        # Kobukiのバッテリー状態を購読する.
        self.battery_subscription = self.create_subscription(
            SensorState,
            battery_topic,
            self.battery_callback,
            10,
        )

    def odom_callback(self, msg):
        vx = msg.twist.twist.linear.x
        vy = msg.twist.twist.linear.y
        vz = msg.twist.twist.linear.z

        # 速度の大きさを計算する.
        self.linear_x = vx
        self.speed_mps = float(np.sqrt(vx * vx + vy * vy + vz * vz))

    def gear_callback(self, msg):
        raw = msg.data.strip()

        # ギア表示用に短く整える.
        if raw == "":
            self.gear_text = "--"
        elif raw.lower() in ["neutral", "n"]:
            self.gear_text = "N"
        elif raw.lower() in ["reverse", "r"]:
            self.gear_text = "R"
        elif raw.lower() in ["parking", "p"]:
            self.gear_text = "P"
        else:
            self.gear_text = raw

    def gear_int_callback(self, msg):
        gear = int(msg.data)

        # Int32のギア表示用に短く整える.
        if gear == 0:
            self.gear_text = "N"
        elif gear < 0:
            self.gear_text = "R"
        else:
            self.gear_text = str(gear)

    def mode_callback(self, msg):
        raw = msg.data.strip().upper()

        # ハンコン側から来た文字列をMT/AT表示に変換する.
        if raw in ["MT", "MANUAL", "MANUAL_MODE"]:
            self.mode_text = "MT"
        elif raw in ["AT", "AUTO", "AUTO_MODE", "AUTOMATIC"]:
            self.mode_text = "AT"

    def battery_callback(self, msg):
        # Kobukiのbatteryは 0.1V 単位で入る想定.
        self.battery_voltage = float(msg.battery) / 10.0

        if self.battery_full_voltage > self.battery_empty_voltage:
            ratio = (
                (self.battery_voltage - self.battery_empty_voltage)
                / (self.battery_full_voltage - self.battery_empty_voltage)
            )
        else:
            ratio = 0.0

        ratio = max(0.0, min(1.0, ratio))
        self.battery_percent = ratio * 100.0


class VideoLabel(QLabel):
    def __init__(self, title):
        super().__init__()

        self.title = title

        # ラベルの見た目を設定する.
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(120, 90)
        self.setStyleSheet("""
            QLabel {
                background-color: #111111;
                color: white;
                border: 2px solid #444444;
                border-radius: 12px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        self.setText(title)

    def set_cv_image(self, frame_bgr):
        # OpenCV画像をQt画像に変換する.
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w

        qimg = QImage(
            frame_rgb.data,
            w,
            h,
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()

        pixmap = QPixmap.fromImage(qimg)
        pixmap = pixmap.scaled(
            self.width(),
            self.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self.setPixmap(pixmap)


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

        # 単位をメーター中心のほぼ真上に描く.
        painter.setPen(QColor(230, 230, 230))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(
            int(cx - 60),
            int(cy - 58),
            120,
            20,
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

        # 表記をメーター中心のほぼ真上に描く.
        painter.setPen(QColor(230, 230, 230))
        painter.setFont(QFont("Arial", 7, QFont.Bold))
        painter.drawText(
            int(cx - 70),
            int(cy - 62),
            140,
            20,
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


class CenterViewWidget(QWidget):
    def __init__(self, width, height, rear_width, rear_height, max_speed_kmh, speed_scale):
        super().__init__()

        self.video_label = VideoLabel("FRONT")
        self.rear_label = VideoLabel("BACK MIRROR")
        self.dashboard = DashboardWidget(
            max_speed_kmh=max_speed_kmh,
            speed_scale=speed_scale,
        )

        self.setMinimumSize(width, height)

        self.video_label.setParent(self)
        self.rear_label.setParent(self)
        self.dashboard.setParent(self)

        # オーバーレイを前面に出す.
        self.rear_label.raise_()
        self.dashboard.raise_()

        self.rear_width = rear_width
        self.rear_height = rear_height

    def resizeEvent(self, event):
        # 正面映像を全体に広げる.
        self.video_label.setGeometry(0, 0, self.width(), self.height())

        # バックミラーを上中央に置く.
        rear_x = int((self.width() - self.rear_width) / 2)
        rear_y = 14
        self.rear_label.setGeometry(rear_x, rear_y, self.rear_width, self.rear_height)

        # 3連メーターを下中央に置く.
        dash_w = self.dashboard.width()
        dash_h = self.dashboard.height()
        dash_x = int((self.width() - dash_w) / 2)
        dash_y = int(self.height() - dash_h - 4)
        self.dashboard.setGeometry(dash_x, dash_y, dash_w, dash_h)

    def set_front_image(self, frame_bgr):
        self.video_label.set_cv_image(frame_bgr)

    def set_rear_image(self, frame_bgr):
        self.rear_label.set_cv_image(frame_bgr)

    def set_status(
        self,
        speed_mps,
        linear_x,
        gear_text,
        battery_percent,
        battery_voltage,
        mode_text,
    ):
        self.dashboard.set_status(
            speed_mps,
            linear_x,
            gear_text,
            battery_percent,
            battery_voltage,
            mode_text,
        )


class ThetaDriverUI(QWidget):
    def __init__(self, args):
        super().__init__()

        self.args = args
        self.start_time = time.time()

        if args.mock_camera:
            print("[INFO] Mock camera mode")
            self.cap = MockCapture(args.cam_width, args.cam_height)
        else:
            print(f"[INFO] Real camera mode: {args.device}")
            self.cap = self.open_camera(args.device, args.cam_width, args.cam_height)

        self.odom_node = OdomSpeedNode(
            args.odom_topic,
            args.gear_topic,
            args.gear_int_topic,
            args.battery_topic,
            args.mode_topic,
            args.mode,
            args.battery_empty_voltage,
            args.battery_full_voltage,
        )

        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError("最初のフレームを取得できませんでした.")

        self.in_h, self.in_w = frame.shape[:2]

        # 各ビューの変換マップを作る.
        self.front_map = make_theta_view_map(
            self.in_w,
            self.in_h,
            args.front_width,
            args.front_height,
            yaw_deg=0.0,
            fov_deg=args.front_fov,
            front_lens=args.front_lens,
            roll_deg=args.roll,
        )

        self.rear_map = make_theta_view_map(
            self.in_w,
            self.in_h,
            args.rear_width,
            args.rear_height,
            yaw_deg=180.0,
            fov_deg=args.rear_fov,
            front_lens=args.front_lens,
            roll_deg=args.roll,
        )

        self.left_mirror_map = make_theta_view_map(
            self.in_w,
            self.in_h,
            args.mirror_width,
            args.mirror_height,
            yaw_deg=args.left_mirror_yaw,
            fov_deg=args.mirror_fov,
            front_lens=args.front_lens,
            roll_deg=args.roll,
        )

        self.right_mirror_map = make_theta_view_map(
            self.in_w,
            self.in_h,
            args.mirror_width,
            args.mirror_height,
            yaw_deg=args.right_mirror_yaw,
            fov_deg=args.mirror_fov,
            front_lens=args.front_lens,
            roll_deg=args.roll,
        )

        self.init_ui()

        # 映像更新タイマーを開始する.
        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.update_frame)
        self.video_timer.start(args.interval_ms)

        # ROS2処理タイマーを開始する.
        self.ros_timer = QTimer(self)
        self.ros_timer.timeout.connect(self.spin_ros_once)
        self.ros_timer.start(args.ros_interval_ms)

    def open_camera(self, device, width, height):
        # 数字かデバイスパスでカメラを開く.
        if str(device).isdigit():
            cap = cv2.VideoCapture(int(device), cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(str(device), cv2.CAP_V4L2)

        # MJPGを優先して設定する.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, 30)

        if not cap.isOpened():
            raise RuntimeError(f"カメラを開けませんでした: {device}")

        return cap

    def init_ui(self):
        self.setWindowTitle("THETA S Driver View with Analog Cluster")
        self.setStyleSheet("background-color: #050505;")

        self.left_label = VideoLabel("LEFT MIRROR")
        self.right_label = VideoLabel("RIGHT MIRROR")

        self.center_widget = CenterViewWidget(
            width=self.args.front_width,
            height=self.args.front_height,
            rear_width=self.args.rear_width,
            rear_height=self.args.rear_height,
            max_speed_kmh=self.args.max_speed,
            speed_scale=self.args.speed_scale,
        )

        self.left_label.setMinimumSize(self.args.mirror_width, self.args.mirror_height)
        self.right_label.setMinimumSize(self.args.mirror_width, self.args.mirror_height)
        self.center_widget.setMinimumSize(self.args.front_width, self.args.front_height)

        layout = QHBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(self.left_label, alignment=Qt.AlignCenter)
        layout.addWidget(self.center_widget, alignment=Qt.AlignCenter)
        layout.addWidget(self.right_label, alignment=Qt.AlignCenter)

        self.setLayout(layout)

        if self.args.fullscreen:
            self.showFullScreen()
        else:
            self.resize(1650, 850)

    def spin_ros_once(self):
        # バッテリーは常にROS2から取得する.
        rclpy.spin_once(self.odom_node, timeout_sec=0.0)

        # 仮速度モードなら, 速度とギアだけ仮の値にする.
        if self.args.mock_speed:
            elapsed = time.time() - self.start_time

            mock_speed_mps = abs(math.sin(elapsed * 0.5)) * 2.7
            mock_linear_x = mock_speed_mps

            # 仮ギアも切り替える.
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
            )
            return

        # 通常時は速度, ギア, バッテリーをすべてROS2から取得する.
        self.center_widget.set_status(
            self.odom_node.speed_mps,
            self.odom_node.linear_x,
            self.odom_node.gear_text,
            self.odom_node.battery_percent,
            self.odom_node.battery_voltage,
            self.odom_node.mode_text,
        )

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            print("フレーム取得に失敗しました.")
            return

        # 正面ビューを作る.
        front_view = cv2.remap(
            frame,
            self.front_map[0],
            self.front_map[1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )

        # 後方ビューを作る.
        rear_view = cv2.remap(
            frame,
            self.rear_map[0],
            self.rear_map[1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )

        # 左サイドミラービューを作る.
        left_view = cv2.remap(
            frame,
            self.left_mirror_map[0],
            self.left_mirror_map[1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )

        # 右サイドミラービューを作る.
        right_view = cv2.remap(
            frame,
            self.right_mirror_map[0],
            self.right_mirror_map[1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )

        # ミラーらしく左右反転する.
        rear_view = cv2.flip(rear_view, 1)
        left_view = cv2.flip(left_view, 1)
        right_view = cv2.flip(right_view, 1)

        # 画面に表示する.
        self.center_widget.set_front_image(front_view)
        self.center_widget.set_rear_image(rear_view)
        self.left_label.set_cv_image(left_view)
        self.right_label.set_cv_image(right_view)

    def keyPressEvent(self, event: QKeyEvent):
        # qかEscで終了する.
        if event.key() in (Qt.Key_Q, Qt.Key_Escape):
            self.close()

    def closeEvent(self, event):
        # タイマーを止める.
        if hasattr(self, "video_timer"):
            self.video_timer.stop()

        if hasattr(self, "ros_timer"):
            self.ros_timer.stop()

        # カメラを解放する.
        if self.cap is not None:
            self.cap.release()

        # ROS2ノードを破棄する.
        if self.odom_node is not None:
            self.odom_node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()

        event.accept()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--cam-width", type=int, default=1280)
    parser.add_argument("--cam-height", type=int, default=720)

    parser.add_argument("--mock-camera", action="store_true")
    parser.add_argument("--mock-speed", action="store_true")

    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--gear-topic", default="/shift_gear")
    parser.add_argument("--gear-int-topic", default="/handle/gear")

    parser.add_argument("--battery-topic", default="/sensors/core")
    parser.add_argument("--mode-topic", default="/handle/mode")
    parser.add_argument("--mode", choices=["MT", "AT"], default="MT")
    parser.add_argument("--battery-empty-voltage", type=float, default=13.2)
    parser.add_argument("--battery-full-voltage", type=float, default=16.7)
        
    parser.add_argument("--max-speed", type=float, default=120.0)
    parser.add_argument("--speed-scale", type=float, default=12.0)

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

    parser.add_argument("--interval-ms", type=int, default=30)
    parser.add_argument("--ros-interval-ms", type=int, default=20)
    parser.add_argument("--fullscreen", action="store_true")

    args = parser.parse_args()

    rclpy.init(args=None)

    app = QApplication(sys.argv)
    window = ThetaDriverUI(args)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()