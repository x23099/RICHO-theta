# Phase 5 v11 一人用reliability dry-run試験手順

## 目的

v10で観測した起動直後のintent転送と、短い測定復帰によるUNKNOWN再通知を抑止できたか確認する。物理出力は行わず、ハンコン接続PCのadapterは必ず`dry_run`にする。

今回のv11では次を同時に記録する。

- 青箱の有効測定が0.5秒連続するまでUNKNOWNを再armしない。
- challengeを1.0秒連続受信するまでrelayはintentを転送しない。
- `/collision/ffb_relay_diagnostics`へ転送・見送り理由をJSONで出力する。
- `/phase5/mock_odom`を停止5秒、0.25 m/sで15秒、停止5秒の順で自動送信し、実送信時刻をCSVへ保存する。

両PCで`ROS_DOMAIN_ID=88`、`ROS_LOCALHOST_ONLY=0`を使う。

## 1. ハンコン接続PC（`hsr-Alienware-m16-R2`）

### Terminal H1: dry-run adapter

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

`mode=dry_run`と`freshness=challenge`を確認する。異なる場合は続行しない。

### Terminal H2: rosbag

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

mkdir -p ~/yopi_ws/ffb_recordings/2026-09-25
ros2 bag record \
  -o ~/yopi_ws/ffb_recordings/2026-09-25/phase5_v11_reliability_hsr_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /phase5/mock_odom
```

## 2. Kobuki PC（`matunuc-NUC13ANHi5`）

各Terminalで最初に以下を実行する。

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

### Terminal K1: rosbag

```bash
mkdir -p ~/theta_ws/ffb_recordings/2026-09-25
ros2 bag record \
  -o ~/theta_ws/ffb_recordings/2026-09-25/phase5_v11_reliability_kobuki_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /phase5/mock_odom
```

### Terminal K2: カメラとrelay

青箱を正面約0.9～1.0 mに置く。実験済みv10ではなくv11設定を指定する。

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v11_ffb_reliability_20260925.json \
  --record-dir src/recordings/2026-09-25_phase5_v11_reliability \
  --experiment-label phase5_v11_reliability_dryrun_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

preflightの後、`FFB relay:`、`stable=1.000s`、`Publishing collision FFB intents`を確認する。

### Terminal K3: 一人用ODOMシナリオ

GUIで録画を開始してから、次の1コマンドを実行する。

```bash
python3 src/publish_mock_odom_scenario.py \
  --topic /phase5/mock_odom \
  --lead-in-sec 5 \
  --motion-sec 15 \
  --lead-out-sec 5 \
  --speed-mps 0.25 \
  --rate-hz 30 \
  --output-csv Experimental_results/2026-09-25/phase5_v11_mock_odom_r01.csv
```

Terminalには`initial_stop`、`forward_0p25`、`final_stop`の開始が表示される。`forward_0p25`表示後は次の順で青箱を隠す。

1. 青箱を見せたまま約3秒待つ。
2. 約2秒完全に隠す。
3. 0.5秒未満だけ見せ、再び約1秒隠す。ここではUNKNOWNが再発火しないことを確認する。
4. 青箱を1秒以上連続して見せる。
5. 余裕があれば再度約1秒隠す。このときは再arm後なので、新しいUNKNOWN単発が許可される。
6. 青箱を戻し、`final_stop`が終わるまで触らない。

操作が間に合わなかった場合もCSVに実送信時刻が残るため、録画と照合して判定する。シナリオ終了後にGUI録画、K2、K1、H2、H1の順で停止する。

## 3. 合格条件

- adapterの全statusが`output_mode: dry_run`で、faultが0件。
- 起動後1.0秒未満のrelay診断は`receiver_challenge_stream_not_stable`で見送られ、commandへ転送されない。
- 安定後は診断`outcome: forwarded`があり、active intentに対応するcommand/statusがある。
- 最初のUNKNOWN後、0.5秒未満の短い測定復帰ではUNKNOWN activeが再発火しない。
- 0.5秒以上の有効測定後はUNKNOWNを再armできる。
- ODOM CSVの全行で`publish_success=1`、phaseが停止→0.25 m/s→停止の順である。
- 最終statusがinactiveかつ`fault: false`である。

この試験がPASSしてから、同じv11経路で低強度hardware試験へ進む。
