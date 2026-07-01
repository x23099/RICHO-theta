#!/usr/bin/env python3


import os
import glob
import time
import select
import threading
import math


import rclpy
from rclpy.node import Node


from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, Float32, Int32, String


from evdev import InputDevice, ecodes




class HandleNode(Node):
   def __init__(self):
       super().__init__('dualshock3_handle_node')


       # Kobuki手動操作用の速度指令
       self.cmd_pub = self.create_publisher(Twist, '/cmd_vel_joy', 10)
       self.kobuki_cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)


       # FFB制御側で使うためのハンドル情報
       self.steering_deg_pub = self.create_publisher(Float32, '/handle/steering_angle_deg', 10)
       self.steering_norm_pub = self.create_publisher(Float32, '/handle/steering_norm', 10)


       # 人間が手動操作中かFFB側へ通知する。
       self.manual_active_pub = self.create_publisher(Bool, '/handle/manual_active', 10)
     
       # 現在、人間が手動介入中か。
       self.manual_active = False
      
       # 現在のギア情報.
       self.gear_pub = self.create_publisher(Int32, '/handle/gear', 10)


       # 現在の走行モードをUI側へ通知する.
       self.drive_mode_pub = self.create_publisher(String, '/handle/drive_mode', 10)
       self.page_delta_pub = self.create_publisher(Int32, '/handle/page_delta', 10)


       # G923のLED制御用hidraw.
       self.led_hidraw_path = '/dev/g923_led'


       # LEDの現在状態.
       self.led_current_mask = None
       self.led_blink_state = False
       self.led_last_blink_time = time.time()


       # LED点滅周期.
       self.led_blink_interval = 0.2


       # シフトライト判定閾値.
       self.led_low_threshold = 0.15
       self.led_middle_threshold = 0.45
       self.led_high_threshold = 0.70
       self.led_shift_threshold = 0.90
      
       # 走行モード.
       self.drive_mode = 'MT'


       # MTモードの状態.
       self.mt_gear = 0


       # ATモードの状態.
       self.at_selector = 'N'
       self.at_gear = 1
       self.at_min_gear = 1
       self.at_max_gear = 6


       # 各段の速度倍率.
       self.forward_gear_gains = {
           1: 0.5,
           2: 1.0,
           3: 1.5,
           4: 2.0,
           5: 2.5,
           6: 3.0,
       }


       # Hパターンのイベントコード.
       self.mt_gear_codes = {
           300: 1,
           301: 2,
           302: 3,
           303: 4,
           704: 5,
           705: 6,
           706: -1,
       }


       # ATモードのセレクター位置.
       self.at_selector_codes = {
           300: 'P',
           301: 'D',
           705: 'R',
       }


       # モード切り替えボタン.
       self.mode_switch_code = 712


       # モード切り替えの連打防止.
       self.last_mode_switch_time = 0.0
       self.mode_switch_debounce_sec = 0.30


       # パドルのイベントコード.
       # evtestで確認した値へ変更する.
       self.paddle_up_code = 292
       self.paddle_down_code = 293
       self.page_hat_x_code = 16
       self.page_left_key_codes = {
           getattr(ecodes, 'BTN_DPAD_LEFT', 544),
       }
       self.page_right_key_codes = {
           getattr(ecodes, 'BTN_DPAD_RIGHT', 545),
       }


       # 起動時はニュートラルにする.
       self.gear = 0
       self.linear_gain = 0.0
      
       # ===== 操縦パラメータ =====


       # Kobukiの最大速度
       self.max_linear = 0.6


       # Kobukiの最大旋回速度.小さいとハンドルを切っても曲がりにくい
       self.max_angular = 1.6


       # G923は左右それぞれ450度まで
       self.steering_limit_deg = 450.0


       # ハンドル中心付近の小さなブレを無視する範囲
       self.steering_deadzone_deg = 2.0
      
       # このハンドル角で基準となる旋回速度を出す
       self.reference_steering_deg = 112.5
      
       # ハンドル112.5度時に出す旋回角速度[rad/s].
       self.reference_angular = 0.8
      
       # 小さい舵角の感度を高くする指数
       # 1.0なら完全な比例、0.5〜0.8なら中心付近が敏感になる.
       self.steering_curve_exponent = 0.60


       # アクセルを少し踏んだら手動操作中とみなす閾値
       self.throttle_threshold = 0.03


       # ブレーキ判定
       self.brake_threshold_raw = 240
      
       # 小さな直進指令を0として扱う閾値.
       self.linear_command_deadzone = 0.01


       # 小さな旋回指令を0として扱う閾値.
       self.angular_command_deadzone = 0.03


       # 手動操作終了時にゼロ指令を送る回数.
       self.stop_publish_cycles = 3


       # 残りのゼロ指令送信回数.
       self.stop_publish_remaining = 0
      
       # 旋回時の速度制限設定.
       self.corner_speed_limit_enabled = False
      
       # 高速時のステア感度補正.
       self.high_speed_steering_boost_enabled = True


       # この速度を超えたらステア補正を始める.
       self.high_speed_boost_start_linear = 0.45


       # この速度でステア補正を最大にする.
       self.high_speed_boost_full_linear = 0.90


       # 高速時にangular.zを最大何倍まで増やすか.
       self.high_speed_angular_boost = 1.5


       # 高速時のangular.z上限.
       self.high_speed_max_angular = 4.0


       # このステア量を超えたら速度制限を始める.
       self.corner_speed_start = 0.15


       # 全切り時に残す最低速度倍率.
       self.corner_min_speed_scale = 0.45


       # 速度制限の強さ.
       self.corner_speed_reduction = 0.55


       # ===== G923を開く =====


       self.g923 = self.find_g923_device()


       if self.g923 is None:
           self.get_logger().error('Logitech G923 not found.')
           self.get_logger().error(
               'Check /dev/input/by-id for a G923/G29 event-joystick device.'
           )
           return


       self.get_logger().info(f'Connected: {self.g923.name}')


       # ステアリング軸ABS_Xの範囲を取得する
       try:
           absinfo = self.g923.absinfo(ecodes.ABS_X)


           self.steering_center = (absinfo.min + absinfo.max) / 2.0
           self.steering_half_range = max((absinfo.max - absinfo.min) / 2.0, 1.0)


           self.get_logger().info(
               f'ABS_X min={absinfo.min}, max={absinfo.max}, '
               f'center={self.steering_center}, half={self.steering_half_range}'
           )


       except Exception as e:
           self.get_logger().warn(f'Failed to get ABS_X info: {e}')


           self.steering_center = 32768.0
           self.steering_half_range = 32768.0


       # ===== 入力状態 =====


       self.steering_raw = int(self.steering_center)
       self.steering_norm = 0.0
       self.steering_deg = 0.0


       self.throttle_norm = 0.0
       self.brake_active = False
       self.clutch_active = False


       # ギア状態.
       # 1〜5: 前進
       # -1 : リバース
       self.gear = 1
       self.linear_gain = 1.0


       # 入力スレッド管理
       self.running = True


       self.input_thread = threading.Thread(
           target=self.input_loop,
           daemon=True
       )
       self.input_thread.start()


       # 20Hzで現在状態をpublishし続ける
       self.publish_period = 0.05
       self.create_timer(self.publish_period, self.publish_loop)


       # 起動直後の走行モードを通知する.
       self.publish_drive_mode()


       self.get_logger().info('handle.py started.')


   def find_g923_device(self):
       """
       G923のevent-joystickデバイスを探して開く.
       固定パスがあればそれを優先する.
       """
       stable_path = (
           '/dev/input/by-id/'
           'usb-Logitech_G923_Racing_Wheel_for_PlayStation_4_and_PC_'
           'USYMUGUXEREJOFORUFUMEZIDU-event-joystick'
       )


       if os.path.exists(stable_path):
           try:
               return InputDevice(stable_path)
           except Exception as e:
               self.get_logger().warn(f'Failed to open stable path: {e}')


       patterns = [
           '/dev/input/by-id/*G923*event-joystick',
           '/dev/input/by-id/*G29*event-joystick',
           '/dev/input/by-id/*Logitech*Racing*event-joystick',
       ]


       for pattern in patterns:
           for path in glob.glob(pattern):
               try:
                   return InputDevice(path)
               except Exception:
                   pass


       for path in glob.glob('/dev/input/event*'):
           try:
               dev = InputDevice(path)
               name = dev.name.lower()


               if 'g923' in name or ('logitech' in name and 'racing wheel' in name):
                   return dev


               dev.close()


           except Exception:
               pass


       return None


   def input_loop(self):
       """
       G923の入力イベントを読み続ける.
       ここではpublishせず、内部状態だけ更新する.
       実際のpublishはpublish_loopで20Hz周期で行う.
       """
       while self.running:
           try:
               r, _, _ = select.select([self.g923.fd], [], [], 0.01)


               if not r:
                   continue


               for event in self.g923.read():
                   # プレステマークは環境によってtypeやvalueが変わることがあるため, code 712を最優先で拾う.
                   if event.code == self.mode_switch_code:
                       self.handle_mode_switch_event(event)
                       continue

                   if self.handle_page_event(event):
                       continue

                   if event.type == ecodes.EV_ABS:
                       self.handle_abs_event(event)


                   elif event.type == ecodes.EV_KEY:
                       self.handle_key_event(event)


           except BlockingIOError:
               continue


           except Exception as e:
               self.get_logger().error(f'Input error: {e}')


   def publish_page_delta(self, delta):
       msg = Int32()
       msg.data = int(delta)
       self.page_delta_pub.publish(msg)
       self.get_logger().info(f'UI page delta: {delta}')


   def handle_page_event(self, event):
       if event.type == ecodes.EV_ABS and event.code in (ecodes.ABS_HAT0X, self.page_hat_x_code):
           if event.value < 0:
               self.publish_page_delta(-1)
               return True
           if event.value > 0:
               self.publish_page_delta(1)
               return True
           return False

       if event.type == ecodes.EV_KEY and event.value == 1:
           if event.code in self.page_left_key_codes:
               self.publish_page_delta(-1)
               return True
           if event.code in self.page_right_key_codes:
               self.publish_page_delta(1)
               return True

       return False


   def handle_mode_switch_event(self, event):
       """
       プレステマークでMT/ATを切り替える.
       eventcode 712を検出したら, typeに関係なく処理する.
       """
       # 離したイベントでは切り替えない.
       if event.value == 0:
           return


       now = time.time()


       # 長押しや連続イベントで何度も切り替わるのを防ぐ.
       if now - self.last_mode_switch_time < self.mode_switch_debounce_sec:
           return


       self.last_mode_switch_time = now


       self.get_logger().info(
           f'Mode switch button detected: '
           f'type={event.type}, code={event.code}, value={event.value}'
       )


       self.toggle_drive_mode()




   def calculate_angular_command(self, linear_x=0.0):
       """
       ハンドル角度から汎用的な旋回角速度angular.zを計算する.


       ハンドル角を最終的な旋回角度には変換せず、
       ハンドルを切っている間の旋回速度としてTwistへ変換する.
       """
       steering_deg = self.steering_deg


       # 中心付近の小さな揺れを無視する.
       if abs(steering_deg) <= self.steering_deadzone_deg:
           return 0.0


       # デッドゾーンを除いた実効ハンドル角を求める.
       effective_deg = abs(steering_deg) - self.steering_deadzone_deg


       # 112.5度を基準として0以上の比率に変換する.
       steering_ratio = effective_deg / self.reference_steering_deg


       # 小さい舵角でも旋回しやすくする.
       curved_ratio = steering_ratio ** self.steering_curve_exponent


       # 基準角速度を掛けてangular.zを計算する.
       angular = curved_ratio * self.reference_angular


       # 最大旋回速度を超えないように制限する.
       angular = min(angular, self.max_angular)


       # ハンドルの左右方向を反映する.
       angular = math.copysign(angular, steering_deg)


       # ROSでは通常, 右旋回がangular.zのマイナスになるため反転する.
       angular = -angular


       # 高速走行時は旋回角速度を強くする.
       angular = self.apply_high_speed_steering_boost(
           angular,
           linear_x
       )


       return angular


   def handle_abs_event(self, event):
       """
       ステアリング、アクセル、ブレーキ、クラッチの入力処理.
       """
      
       # ハンコンの生値
       raw_val = event.value
       code = event.code


       # ステアリング.
       if code == ecodes.ABS_X:
           self.steering_raw = raw_val # 現在のハンコン位置の生値を保存


           # 生値を-1.0〜1.0に正規化
           norm = (raw_val - self.steering_center) / self.steering_half_range
           norm = max(-1.0, min(1.0, norm))


           # 正規化値×450
           deg = norm * self.steering_limit_deg


           if abs(deg) < self.steering_deadzone_deg:
               deg = 0.0
               norm = 0.0


           self.steering_norm = norm
           self.steering_deg = deg


       # アクセル.
       elif code == ecodes.ABS_Z:
           if raw_val < 250:
               self.throttle_norm = (250 - raw_val) / 250.0
           else:
               self.throttle_norm = 0.0


           self.throttle_norm = max(0.0, min(1.0, self.throttle_norm))


       # ブレーキ.
       elif code == ecodes.ABS_RZ:
           self.brake_active = raw_val < self.brake_threshold_raw


       # クラッチ.
       elif code == ecodes.ABS_Y:
           self.clutch_active = raw_val < 240


   def handle_key_event(self, event):
       """
       MT, AT, パドルシフトの入力を処理する.
       """
       code = event.code
       pressed = event.value == 1
       released = event.value == 0


       # プレステマーク, eventcode 712を押したときにMTとATを切り替える.
       if code == self.mode_switch_code and pressed:
           self.toggle_drive_mode()
           return


       # MTモードのシフト入力を処理する.
       if self.drive_mode == 'MT':
           self.handle_mt_shift(
               code,
               pressed,
               released
           )
           return


       # ATモードのセレクターとパドル入力を処理する.
       if self.drive_mode == 'AT':
           self.handle_at_shift(
               code,
               pressed,
               released
           )




   def toggle_drive_mode(self):
       """
       MTモードとATモードを切り替える.
       """
       if self.drive_mode == 'MT':
           self.drive_mode = 'AT'
           self.at_selector = 'N'
           self.at_gear = 1
       else:
           self.drive_mode = 'MT'
           self.mt_gear = 0


       # モード切り替え時はニュートラルにする.
       self.gear = 0
       self.linear_gain = 0.0


       # 残っている走行指令を停止させる.
       self.stop_publish_remaining = max(
           self.stop_publish_remaining,
           self.stop_publish_cycles
       )


       self.publish_drive_mode()


       self.get_logger().info(
           f'Drive mode changed: {self.drive_mode}'
       )




   def publish_drive_mode(self):
       """
       現在の走行モードをUI側へpublishする.
       """
       mode_msg = String()
       mode_msg.data = self.drive_mode
       self.drive_mode_pub.publish(mode_msg)


  
   def apply_high_speed_steering_boost(self, angular_z, linear_x):
       """
       高速走行時に旋回角速度を強くする.
       """
       if not self.high_speed_steering_boost_enabled:
           return angular_z


       speed = abs(linear_x)


       if speed <= self.high_speed_boost_start_linear:
           return angular_z


       speed_rate = (
           speed - self.high_speed_boost_start_linear
       ) / (
           self.high_speed_boost_full_linear
           - self.high_speed_boost_start_linear
       )


       speed_rate = max(
           0.0,
           min(1.0, speed_rate)
       )


       boost = 1.0 + (
           self.high_speed_angular_boost
           * speed_rate
       )


       boosted_angular = angular_z * boost


       boosted_angular = max(
           -self.high_speed_max_angular,
           min(
               self.high_speed_max_angular,
               boosted_angular
           )
       )


       return boosted_angular
  
   def send_led_mask(self, mask):
       """
       G923のLEDへ点灯パターンを送る.
       """
       if mask == self.led_current_mask:
           return


       report = bytes([
           0xf8,
           0x12,
           mask & 0x1f,
           0x00,
           0x00,
           0x00,
           0x01,
       ])


       try:
           with open(self.led_hidraw_path, 'wb', buffering=0) as device:
               device.write(report)


           self.led_current_mask = mask


       except OSError as error:
           self.get_logger().warn(
               f'LED write failed: {error}'
           )




   def set_shift_leds(self, count):
       """
       指定した個数だけLEDを点灯する.
       """
       count = max(0, min(5, count))


       if count == 0:
           self.send_led_mask(0x00)
           return


       mask = (1 << count) - 1
       self.send_led_mask(mask)




   def blink_shift_leds(self, count):
       """
       指定した個数のLEDを点滅させる.
       """
       now = time.time()


       if now - self.led_last_blink_time < self.led_blink_interval:
           return


       self.led_last_blink_time = now
       self.led_blink_state = not self.led_blink_state


       if self.led_blink_state:
           self.set_shift_leds(count)
       else:
           self.set_shift_leds(0)




   def update_shift_leds(self):
       """
       走行状態に応じてG923のシフトLEDを更新する.
       """
       # ATのP,Nでは消灯する.
       if self.drive_mode == 'AT' and self.at_selector in ['P', 'N']:
           self.set_shift_leds(0)
           return


       # MTのニュートラルでは消灯する.
       if self.drive_mode == 'MT' and self.gear == 0:
           self.set_shift_leds(0)
           return


       # Rギアでは5個を点滅させる.
       if self.gear == -1:
           self.blink_shift_leds(5)
           return


       # 前進ギア以外では消灯する.
       if self.gear <= 0:
           self.set_shift_leds(0)
           return


       # アクセル開度を疑似RPMとして使う.
       rpm_ratio = self.throttle_norm


       if rpm_ratio < self.led_low_threshold:
           self.set_shift_leds(0)


       elif rpm_ratio < self.led_middle_threshold:
           self.set_shift_leds(1)


       elif rpm_ratio < self.led_high_threshold:
           self.set_shift_leds(3)


       elif rpm_ratio < self.led_shift_threshold:
           self.set_shift_leds(5)


       else:
           self.blink_shift_leds(5)
  
   def handle_mt_shift(self, code, pressed, released):
       """
       MTモードのHパターンシフトを処理する.
       """
       if code not in self.mt_gear_codes:
           return


       selected_gear = self.mt_gear_codes[code]


       # ギア位置から抜けたらニュートラルにする.
       if released and self.mt_gear == selected_gear:
           self.mt_gear = 0
           self.gear = 0
           self.linear_gain = 0.0


           self.get_logger().info('MT gear: N')
           return


       if not pressed:
           return


       # MTではクラッチを踏んでいるときだけ変速する.
       if not self.clutch_active:
           self.get_logger().warn(
               'MT shift rejected: clutch is not pressed.'
           )
           return


       self.mt_gear = selected_gear
       self.gear = selected_gear


       if selected_gear == -1:
           self.linear_gain = -0.5
       else:
           self.linear_gain = self.forward_gear_gains[
               selected_gear
           ]


       self.get_logger().info(
           f'MT gear: {self.gear}, '
           f'linear_gain={self.linear_gain:.1f}'
       )




   def handle_at_shift(self, code, pressed, released):
       """
       ATモードのセレクターとパドルシフトを処理する.
       """
       # 右パドルで1段上げる.
       if code == self.paddle_up_code and pressed:
           self.shift_at_gear(1)
           return


       # 左パドルで1段下げる.
       if code == self.paddle_down_code and pressed:
           self.shift_at_gear(-1)
           return


       if code not in self.at_selector_codes:
           return


       selected_position = self.at_selector_codes[code]


       # セレクター位置から抜けたらNにする.
       if released and self.at_selector == selected_position:
           self.set_at_selector('N')
           return


       if pressed:
           self.set_at_selector(selected_position)




   def set_at_selector(self, selector):
       """
       ATモードのP, R, N, Dを設定する.
       """
       previous_selector = self.at_selector
       self.at_selector = selector


       if selector == 'P':
           self.gear = 0
           self.linear_gain = 0.0


       elif selector == 'R':
           self.gear = -1
           self.linear_gain = -0.5


       elif selector == 'N':
           self.gear = 0
           self.linear_gain = 0.0


       elif selector == 'D':
           # D以外からDへ入れたときは1速へ戻す.
           if previous_selector != 'D':
               self.at_gear = 1


           self.gear = self.at_gear
           self.linear_gain = self.forward_gear_gains[
               self.at_gear
           ]


       # セレクター変更時に古い走行指令を停止させる.
       self.stop_publish_remaining = max(
           self.stop_publish_remaining,
           self.stop_publish_cycles
       )


       self.get_logger().info(
           f'AT selector: {self.at_selector}, '
           f'gear={self.at_gear}'
       )




   def shift_at_gear(self, direction):
       """
       ATのDレンジ中にパドルで仮想段数を変更する.
       """
       if self.at_selector != 'D':
           self.get_logger().info(
               'Paddle shift ignored: selector is not D.'
           )
           return


       new_gear = self.at_gear + direction
       new_gear = max(
           self.at_min_gear,
           min(self.at_max_gear, new_gear)
       )


       if new_gear == self.at_gear:
           return


       self.at_gear = new_gear
       self.gear = self.at_gear
       self.linear_gain = self.forward_gear_gains[
           self.at_gear
       ]


       self.get_logger().info(
           f'AT paddle shift: D{self.at_gear}, '
           f'linear_gain={self.linear_gain:.1f}'
       )


   def publish_loop(self):
       """
       現在の入力状態を20Hzでpublishし続ける.
       手動操作終了時はゼロ指令を数回送ってからpublishを停止する.
       """


       # ハンドル角度[deg]をpublish.
       deg_msg = Float32()
       deg_msg.data = float(self.steering_deg)
       self.steering_deg_pub.publish(deg_msg)


       # ハンドル正規化値[-1.0〜1.0]をpublish.
       norm_msg = Float32()
       norm_msg.data = float(self.steering_norm)
       self.steering_norm_pub.publish(norm_msg)


       # ギア情報をpublish.
       gear_msg = Int32()
       gear_msg.data = int(self.gear)
       self.gear_pub.publish(gear_msg)


       # 走行モードをpublish.
       self.publish_drive_mode()


       # アクセルかブレーキ操作中を手動操作として扱う.
       manual_active = (
           self.throttle_norm > self.throttle_threshold
           or self.brake_active
       )


       # FFB側へ手動操作状態を通知する.
       manual_msg = Bool()
       manual_msg.data = manual_active
       self.manual_active_pub.publish(manual_msg)


       # シフトライトを更新する.
       self.update_shift_leds()
      
       if manual_active:
           # 手動操作終了後に送るゼロ指令回数を準備する.
           self.stop_publish_remaining = self.stop_publish_cycles


           twist = Twist()


           if self.brake_active:
               # ブレーキ中は直進と旋回を両方停止する.
               twist.linear.x = 0.0
               twist.angular.z = 0.0


           else:
               # アクセル量とギア倍率から直進速度を作る.
               twist.linear.x = (
                   self.throttle_norm
                   * self.max_linear
                   * self.linear_gain
               )


               # ハンドル角度と速度から旋回角速度を作る.
               angular_command = self.calculate_angular_command(
                   twist.linear.x
               )
               # 後退時は操舵方向を反転する.
               if self.linear_gain < 0:
                   twist.angular.z = -angular_command
               else:
                   twist.angular.z = angular_command


               # 小さな直進指令を0にする.
               if abs(twist.linear.x) < self.linear_command_deadzone:
                   twist.linear.x = 0.0


               # 小さな旋回指令を0にする.
               if abs(twist.angular.z) < self.angular_command_deadzone:
                   twist.angular.z = 0.0


           self.cmd_pub.publish(twist)
           self.kobuki_cmd_pub.publish(twist)
           return


       # 手動操作終了後にゼロ指令を数回だけ送る.
       if self.stop_publish_remaining > 0:
           stop_twist = Twist()
           self.cmd_pub.publish(stop_twist)
           self.kobuki_cmd_pub.publish(stop_twist)
           self.stop_publish_remaining -= 1


   def destroy_node(self):
       self.running = False


       try:
           if self.g923 is not None:
               self.g923.close()
       except Exception:
           pass


       super().destroy_node()




def main(args=None):
   rclpy.init(args=args)


   node = HandleNode()


   try:
       rclpy.spin(node)


   except KeyboardInterrupt:
       pass


   finally:
       node.destroy_node()
       rclpy.shutdown()




if __name__ == '__main__':
   main()
