# Phase 5 v10 relay PC間dry-run再試験手順

## 目的と禁止事項

カメラGUIからchallenge処理を分離したv10 relayで、期限切れ・不明token faultがなくなるか確認する。今回は通信経路の検証であり、adapterは必ず`dry_run`にする。ハンコンへの物理出力は行わない。

両PCの`ROS_DOMAIN_ID`は`88`とし、実機`/odom`ではなく`/phase5/mock_odom`を使う。

## 1. ハンコン接続PC（`hsr-Alienware-m16-R2`）

### Terminal H1: adapter

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

起動ログに`mode=dry_run`と`freshness=challenge`がなければ中止する。

### Terminal H2: 起動確認

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

ros2 param get /collision_ffb_node output_mode
ros2 param get /collision_ffb_node freshness_mode
ros2 topic info /collision/ffb_challenge -v
timeout 5 ros2 topic hz /collision/ffb_challenge
```

期待値は`dry_run`、`challenge`、publisher 1、約50 Hzである。

### Terminal H2: rosbag

```bash
mkdir -p ~/yopi_ws/ffb_recordings/2026-09-25

ros2 bag record \
  -o ~/yopi_ws/ffb_recordings/2026-09-25/phase5_v10_relay_hsr_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /phase5/mock_odom
```

## 2. Kobuki PC（`matunuc-NUC13ANHi5`）

各TerminalでROSとFFB message workspaceをsourceし、domain 88を明示する。

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

### Terminal K1: 停止ODOM

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom \
  nav_msgs/msg/Odometry \
  "{twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}"
```

### Terminal K2: rosbag

```bash
mkdir -p ~/theta_ws/ffb_recordings/2026-09-25

ros2 bag record \
  -o ~/theta_ws/ffb_recordings/2026-09-25/phase5_v10_relay_kobuki_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /phase5/mock_odom
```

### Terminal K3: カメラとrelayのワンコマンド起動

青箱を正面約0.9～1.0 mに置いてから実行する。

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v10_ffb_relay_20260925.json \
  --record-dir src/recordings/2026-09-25_phase5_v10_relay \
  --experiment-label phase5_v10_relay_dryrun_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

ログには`FFB relay:`、`Collision FFB relay started`、`Publishing collision FFB intents`の3つが必要である。1つでもなければ録画を始めない。

## 3. 撮影操作

1. GUIで録画を開始し、停止ODOM・青箱可視のまま約3秒待つ。
2. Terminal K1の停止ODOMを`Ctrl+C`で完全に止める。
3. `ros2 topic info /phase5/mock_odom -v`でPublisher countが0になったことを確認する。
4. 別Terminalで0.25 m/sを約3秒送る。青箱は隠さず、WARNING三連を作る。

```bash
timeout 3 ros2 topic pub -r 30 \
  /phase5/mock_odom \
  nav_msgs/msg/Odometry \
  "{twist: {twist: {linear: {x: 0.25}, angular: {z: 0.0}}}}"
```

5. 停止ODOMを再開し、青箱可視のまま約3秒待ってCLEARへ戻す。
6. 停止ODOMを再度完全に止め、Publisher count 0を確認する。
7. 0.25 m/sを約5秒送る。送信開始約1秒後、青箱が検出中のうちに遮蔽物で完全に隠し、約1秒維持してから戻す。走行送信が終わってから隠してはいけない。

```bash
timeout 5 ros2 topic pub -r 30 \
  /phase5/mock_odom \
  nav_msgs/msg/Odometry \
  "{twist: {twist: {linear: {x: 0.25}, angular: {z: 0.0}}}}"
```

8. 停止ODOMを再開して約3秒待つ。
9. GUI録画を停止し、K3を終了する。K3終了時にrelayも自動停止する。
10. K2、H2、最後にH1を`Ctrl+C`で終了する。

## 4. 合格条件

- adapterの`output_mode`は全区間`dry_run`。
- `unknown_receiver_token`、`expired_receiver_token`、その他faultが0件。
- `/collision/ffb_intent`のactiveに対応する`/collision/ffb_command`とactive statusがある。
- WARNINGは三連、遮蔽UNKNOWNは単発となり、同じ警報中に再発火しない。
- 最終statusはinactiveかつ`fault: false`。
- `raw.avi`、`detections.csv`、両PCのbagが保存されている。

この条件を満たして初めて、同じv10経路を使う低強度hardware試験へ進む。
