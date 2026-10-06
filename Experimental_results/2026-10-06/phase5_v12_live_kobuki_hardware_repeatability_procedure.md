# Phase 5 v12 実Kobuki hardware再現性試験手順

## 目的

r01と同じ正面直進・WARNING 3連FFBをあと2回実施し、合計3試行で再現性を確認する。新しい条件は追加せず、r01で判明した初期距離と速度指令だけを安全側へ整える。

## 条件

- 試行名: `phase5_v12_live_kobuki_hardware_r02`、`r03`
- 青箱初期距離: カメラから1.30～1.35 m
- 停止線: カメラから0.80 m
- 実速度目安: 0.18～0.22 m/s、絶対上限0.25 m/s
- `/cmd_vel`も可能な範囲で0.25 m/s以下へ抑える
- steering中央、前進のみ
- adapter: `hardware`、challenge freshness、上限0.05
- FFBを感じた時点または停止線の早い方で停止
- 遮蔽、旋回、後退、強度変更、速度引き上げは行わない

どちらか1試行でも予期しない連続振動、停止後の残留振動、0.25 m/s超過、停止線超過、通信断があれば、その場で終了してr03へ進まない。

## 1. 共通確認

両PCで次を設定する。

```bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

Kobuki PCで確認する。

```bash
ros2 topic echo /odom --once
ros2 topic info /phase5/mock_odom -v
ros2 topic info /cmd_vel -v
```

続行条件は、実`/odom`が受信でき、`/phase5/mock_odom` publisherが0、`/cmd_vel`送信元が操縦系1件だけであること。

青箱を1.30～1.35 mへ置き、カメラGUIを起動したときに走行前から有効測定・追跡が成立する配置にする。

## 2. ハンコンPCのadapter

r01後にadapterを終了している場合だけ起動する。既存プロセスがある場合は二重起動しない。

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
export G923_EVENT="/dev/input/by-id/usb-Logitech_G923_Racing_Wheel_for_PlayStation_4_and_PC_USYMUGUXEREJOFORUFUMEZIDU-event-joystick"

test -e "$G923_EVENT" || {
  echo "G923が見つかりません"
  exit 1
}

pgrep -af collision_ffb_node

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

`mode=hardware`、`challenge hardware gate armed`、`hardware backend armed`を確認する。

## 3. r02

### ハンコンPC bag

```bash
mkdir -p ~/yopi_ws/ffb_recordings/2026-10-06
ros2 bag record \
  -o ~/yopi_ws/ffb_recordings/2026-10-06/phase5_v12_live_kobuki_hardware_hsr_r02 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /odom \
  /cmd_vel
```

### Kobuki PC bag

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

mkdir -p ~/theta_ws/ffb_recordings/2026-10-06
ros2 bag record \
  -o ~/theta_ws/ffb_recordings/2026-10-06/phase5_v12_live_kobuki_hardware_kobuki_r02 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /odom \
  /cmd_vel
```

### カメラ・relay

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --record-dir src/recordings/2026-10-06_phase5_v12_live_kobuki \
  --experiment-label phase5_v12_live_kobuki_hardware_r02 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /odom \
  --odom-timeout-sec 10
```

完全停止を約5秒記録し、低速で直進する。3連振動または停止線で止まり、停止後約5秒記録する。停止後に振動が残らないことを確認し、カメラと両bagを終了する。adapterは正常ならr03まで起動したままでよい。

## 4. r03

2026-10-06のr02は、実施者が3連振動と物理停止線の超過なしを確認したため、r03へ進める。実測初期距離1.30 mに対してカメラ推定約1.51 mのずれがあり、床面反射は原因候補として記録した。

Kobukiを同じ開始位置へ戻し、カメラ位置から青箱前面まで実測1.30～1.35 mと停止線0.80 mを再確認する。r03では物理距離0.90 mを早めの停止目標として追加し、FFBを感じた時点または0.90 m目標の早い方で停止する。カメラ推定値だけを停止判断に使わない。初期・停止後の実測距離とGUI推定値を記録する。

上記3つのコマンドの`r02`をすべて`r03`へ変えて実施する。初期状態が推定距離のずれでFARになった場合も、その表示を記録し、物理停止目標までにWARNINGが出なければ停止して終了する。

停止目標の追加は条件変更として記録する。r03はWARNING配送と体感の再現性を評価し、距離推定精度は実測との差を別途確認する。

r03終了後はカメラ、両bag、adapterの順で終了し、adapterの`shutdown`を確認する。

## 5. 各試行の記録

各試行について次をメモする。

- 3連振動を明確に感じたか
- 停止後の不要振動がなかったか
- FFBが操舵・停止を妨げなかったか
- 停止線を越えなかったか
- 予期しない音、旋回、通信断がなかったか

解析用に、r02・r03それぞれのカメラarchive、Kobuki PC bag、ハンコンPC bagを保存する。元archiveはGitへ追加しない。

## 合格条件

3試行すべてで次を満たせば、正面低速接近に対する実機FFBの再現性をPASSとする。

- 最大実速度0.25 m/s以下
- 実測した物理停止線0.80 mを超えない（r03の停止目標は0.90 m）
- WARNING activeがintent、command、hardware statusへ欠落なく到達
- applied magnitude 0.05以下、走行中fault 0
- 3連振動を体感
- 停止後に`output_active=false`、不要振動なし
- FFBが停止操作を妨げない
