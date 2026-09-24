# Phase 5 challenge方式・録画TTC hardware再生手順

## 目的

ハンコン接続PCが発行するchallengeをKobuki PCの録画再生publisherが受信し、過去録画のTTCリスク列から0.05・3連FFBを1イベントだけG923へ出力する。カメラ、模擬ODOM、Kobuki走行は使用しない。

## 使用する録画

```text
/home/matunuc/theta_ws/src/recordings/2026-09-08/ttc_v6_holdout/approach_center_v0p20_r02_v6holdout_20260908_163811_391/detections.csv
```

このsessionは以前の録画再生でTTC警告1イベントを確認済みである。約630 command、約21秒の再生を想定する。

## 事前条件

1. 両PCを最新commitへ更新し、Kobuki PCでは`replay_collision_ffb_commands.py`に`--acknowledge-physical-output`があることを確認する。
2. 両PCを`ROS_DOMAIN_ID=88`、`ROS_LOCALHOST_ONLY=0`へ統一する。
3. G923を固定し、USBまたは電源を即時切断できるようにする。
4. Kobukiは停止し、速度指令を出さない。
5. ハンコン接続PCで他のFFB writerをすべて停止する。
6. 強度上限は0.05から上げない。

## ハンコン接続PC・端末A: adapter

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
export G923_EVENT="/dev/input/by-id/usb-Logitech_G923_Racing_Wheel_for_PlayStation_4_and_PC_USYMUGUXEREJOFORUFUMEZIDU-event-joystick"

test -e "$G923_EVENT" || { echo "G923が見つかりません"; exit 1; }
pgrep -af 'ffb_follow|spring|periodic|collision_ffb_node' || true

ros2 run oit collision_ffb_node --ros-args \
  -p output_mode:=hardware \
  -p freshness_mode:=challenge \
  -p hardware_armed:=true \
  -p challenge_hardware_armed:=true \
  -p hardware_initial_test_passed:=true \
  -p max_magnitude:=0.05 \
  -p challenge_max_age_sec:=0.1 \
  -p challenge_rate_hz:=50.0 \
  -p watchdog_timeout_sec:=0.1 \
  -p device_path:="${G923_EVENT:?G923_EVENTが未設定です}" \
  -p effect_duration_ms:=120
```

`mode=hardware`、`freshness=challenge`、`challenge hardware gate armed`、`hardware backend armed`を確認する。起動直後に振動した場合は中止する。

## ハンコン接続PC・端末B: status監視

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

## Kobuki PC: 録画リスク再生

Kobukiを動かさず、G923へ軽く触れた担当者と声を掛け合って1回だけ実行する。

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source theta-env/bin/activate
source ~/ffb/install/setup.bash

export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

python3 src/replay_collision_ffb_commands.py \
  --input /home/matunuc/theta_ws/src/recordings/2026-09-08/ttc_v6_holdout/approach_center_v0p20_r02_v6holdout_20260908_163811_391/detections.csv \
  --output-dir Experimental_results/2026-09-24/phase5_challenge_hardware_recorded_replay_r01 \
  --rate 30 \
  --cadence triple \
  --cadence-duration 0.5 \
  --cadence-rate 30 \
  --freshness-mode challenge \
  --expect-output-mode hardware \
  --acknowledge-physical-output \
  --discovery-sec 5 \
  --settle-sec 0.5
```

Kobuki PCのFFB interface workspaceが`~/ffb`でない場合は、`oit_interfaces`をbuildした実際のworkspaceの`install/setup.bash`へ読み替える。

## 合格条件

1. 再生結果が`Decision: PASS`になる。
2. 1回のTTC警告開始に対して3連振動を知覚する。
3. active statusがhardware・0.05以下・faultなしになる。
4. 警告終了と再生終了でinactiveになる。
5. 残留力、急回転、異音、発熱、Autocenter変化がない。

## 終了と回収

1. ハンコン接続PCのadapterを`Ctrl+C`で終了し、`shutdown`のinactiveを確認する。
2. status監視を終了する。
3. Kobuki PCの結果ディレクトリを圧縮する。

```bash
cd ~/theta_ws/Experimental_results/2026-09-24
tar -cJf phase5_challenge_hardware_recorded_replay_r01.tar.xz \
  phase5_challenge_hardware_recorded_replay_r01
```

異常時はコマンド操作より先にG923のUSBまたは電源を切る。
