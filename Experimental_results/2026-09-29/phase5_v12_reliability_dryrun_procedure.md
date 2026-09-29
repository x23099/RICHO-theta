# Phase 5 v12 一人用reliability dry-run再試験手順

## 目的と停止条件

v12で、一時的なchallenge間隔の揺らぎが1秒の転送停止へ拡大しないこと、UNKNOWN/WARNINGがadapterまで届くこと、同一publisherの疑似ODOMが両PCのbagへ記録されることを確認する。

- adapterは必ず`dry_run`とする。G923が振動した場合は直ちに中止する。
- Kobukiは走行させない。疑似速度は `/phase5/mock_odom` のみに送る。
- 両PCで `ROS_DOMAIN_ID=88`、`ROS_LOCALHOST_ONLY=0` を使う。
- v12 dry-runがPASSするまでhardwareへ進まない。

## 1. ハンコン接続PC

### H1: dry-run adapter

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

ros2 run oit collision_ffb_node --ros-args \
  -p output_mode:=dry_run \
  -p freshness_mode:=challenge \
  -p max_magnitude:=0.05 \
  -p challenge_max_age_sec:=0.1 \
  -p challenge_rate_hz:=50.0 \
  -p watchdog_timeout_sec:=0.1
```

### H2: rosbag

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

mkdir -p ~/yopi_ws/ffb_recordings/2026-09-29
ros2 bag record \
  -o ~/yopi_ws/ffb_recordings/2026-09-29/phase5_v12_reliability_hsr_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /phase5/mock_odom
```

## 2. Kobuki PC

各Terminalで以下を実行する。

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

### K1: rosbag

```bash
mkdir -p ~/theta_ws/ffb_recordings/2026-09-29
ros2 bag record \
  -o ~/theta_ws/ffb_recordings/2026-09-29/phase5_v12_reliability_kobuki_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /phase5/mock_odom
```

### K2: 同一publisherの疑似ODOMを待機状態で起動

従来のpreflight用 `ros2 topic pub` は使用しない。

```bash
python3 src/publish_mock_odom_scenario.py \
  --topic /phase5/mock_odom \
  --lead-in-sec 5 \
  --motion-sec 15 \
  --lead-out-sec 5 \
  --speed-mps 0.25 \
  --rate-hz 30 \
  --wait-for-enter \
  --output-csv Experimental_results/2026-09-29/phase5_v12_mock_odom_r01.csv
```

`[WAIT] Publishing linear.x=0.000 m/s`が表示されたままにする。まだEnterを押さない。

別Terminalで次を確認する。

```bash
ros2 topic info /phase5/mock_odom -v
ros2 topic echo /phase5/mock_odom --once
```

Publisher countが1、`linear.x: 0.0`でなければ続行しない。

### K3: v12カメラとrelay

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --record-dir src/recordings/2026-09-29_phase5_v12_reliability \
  --experiment-label phase5_v12_reliability_dryrun_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

preflightがPASSし、relayログに次が含まれることを確認する。

- `stable=1.000s`
- `stream_timeout=0.200s`
- `Publishing collision FFB intents`

青箱を正面約0.9～1.0 mに置き、検知を確認してGUI録画を開始する。

## 3. シナリオ開始と遮蔽

GUI録画開始後、K2 Terminalへ戻ってEnterを1回押す。publisherは切り替わらず、`initial_stop`から開始する。

`forward_0p25`表示後に次を行う。

1. 青箱を約3秒見せる。
2. 約2秒完全に隠す。
3. 0.5秒未満だけ見せ、再び約1秒隠す。
4. 青箱を1秒以上連続して見せる。
5. 再度約1秒隠す。
6. 青箱を戻して`final_stop`終了まで触らない。

## 4. 終了と保存

1. K2が`[PASS] Scenario log:`で終了したことを確認する。
2. GUI録画を停止し、K3を終了する。
3. K1、H2の順でbagを終了する。
4. H1 adapterを終了する。
5. カメラ録画、両PC bag、ODOM CSVの4点を保存する。

`--wait-for-enter`使用時のCSVは待機行が加わるため751行より多くなる。次を確認する。

```bash
wc -l Experimental_results/2026-09-29/phase5_v12_mock_odom_r01.csv
tail -3 Experimental_results/2026-09-29/phase5_v12_mock_odom_r01.csv
```

末尾が`final_stop`、`linear_mps=0.000000`、`publish_success=1`であることを確認する。

## 5. 合格条件

- 両bagの `/phase5/mock_odom` に待機0、0.25 m/s、最終0が記録される。
- adapter statusはすべて`dry_run`で、fault 0件。
- 起動直後以外に `receiver_challenge_stream_not_stable` が連続しない。
- 各UNKNOWN/WARNING active群に少なくとも1件のcommandとactive statusが対応する。
- 0.5秒未満の測定復帰ではUNKNOWNを再armせず、0.5秒以上の有効測定後には再armする。
- 個別に古いchallengeを使うintentは`stale_receiver_challenge`で安全に見送られる。
- 最終statusがinactiveかつ`fault=false`。

