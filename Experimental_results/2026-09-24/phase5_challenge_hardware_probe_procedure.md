# Phase 5 challenge方式・停止状態hardware probe手順（0.03、1イベント）

## 目的

G923を固定しKobukiを走行させない状態で、受信側challengeによる鮮度検証とhardware FFBを初めて接続する。試験は0.03、0.5秒、3連、1イベントに限定する。

## 事前条件

1. 安全ゲート実装をハンコン接続PCの`~/yopi_ws`へ反映し、`oit_interfaces`と`oit`をbuild済みにする。
2. G923を机へ固定し、周囲の手、物、ケーブルを退避する。
3. G923のUSBまたは電源をすぐ切れる状態にする。
4. Kobukiは停止し、この最初の試験では起動しない。
5. `ffb_follow`、`spring`、`periodic`、既存`collision_ffb_node`が動いていないことを確認する。
6. 0.03で振動を感じなくても、この試験中は0.05へ上げない。

## 端末0: 更新・build・事前確認

ハンコン接続PCで実行する。

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash

git status --short
git log -1 --oneline

colcon build --packages-select oit_interfaces oit --symlink-install
source install/setup.bash

export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
export G923_EVENT="/dev/input/by-id/usb-Logitech_G923_Racing_Wheel_for_PlayStation_4_and_PC_USYMUGUXEREJOFORUFUMEZIDU-event-joystick"

test -e "$G923_EVENT" || { echo "G923が見つかりません"; exit 1; }
pgrep -af 'ffb_follow|spring|periodic|collision_ffb_node' || true
```

既存writerが表示された場合は新しいadapterを起動しない。該当プロセスを正常終了してから再確認する。

## 端末A: challenge＋hardware adapter

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
export G923_EVENT="/dev/input/by-id/usb-Logitech_G923_Racing_Wheel_for_PlayStation_4_and_PC_USYMUGUXEREJOFORUFUMEZIDU-event-joystick"

ros2 run oit collision_ffb_node --ros-args \
  -p output_mode:=hardware \
  -p freshness_mode:=challenge \
  -p hardware_armed:=true \
  -p challenge_hardware_armed:=true \
  -p hardware_initial_test_passed:=false \
  -p max_magnitude:=0.03 \
  -p challenge_max_age_sec:=0.1 \
  -p challenge_rate_hz:=50.0 \
  -p watchdog_timeout_sec:=0.1 \
  -p device_path:="${G923_EVENT:?G923_EVENTが未設定です}" \
  -p effect_duration_ms:=120
```

次の起動ログを確認する。

- `mode=hardware`
- `freshness=challenge`
- `challenge hardware gate armed`
- `hardware backend armed`

この時点では振動しないのが正常である。エラー、勝手な振動、急回転、異音があれば中止してUSBまたは電源を切る。

## 端末B: status監視

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

ros2 topic echo \
  --qos-reliability best_effort \
  --qos-durability volatile \
  /collision/ffb_status \
  oit_interfaces/msg/CollisionFfbStatus
```

## 端末C: 0.03・3連・1イベント送信

G923へ軽く触れてから、1回だけ実行する。

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

ros2 run oit collision_ffb_probe \
  --freshness-mode challenge \
  --pattern steady \
  --cadence triple \
  --magnitude 0.03 \
  --duration 0.5 \
  --rate 30 \
  --expect-output-mode hardware \
  --acknowledge-physical-output \
  --discovery-sec 2 \
  --settle-sec 0.5 \
  --output-dir Experimental_results/2026-09-24/phase5_challenge_hardware_probe_0p03_r01
```

## 合格条件

1. probeが`Decision: PASS`になる。
2. active中のstatusが`output_mode: hardware`、`action: apply`、`output_active: true`になる。
3. 要求・適用強度が0.03以下になる。
4. 3連の後にCLEARで`action: stop`、`output_active: false`になる。
5. `fault: false`で終了する。
6. 残留力、急回転、異音、発熱、Autocenter変化がない。

0.03を知覚できなくても、安全経路と停止が成立していれば結果として記録する。0.05試験はログ確認後の別ステップとする。

## 終了

端末Aで`Ctrl+C`を押し、`reason=shutdown`、`output_active=false`を確認する。その後に端末Bを終了する。

異常時はコマンド入力より先にG923のUSBまたは電源を切る。
