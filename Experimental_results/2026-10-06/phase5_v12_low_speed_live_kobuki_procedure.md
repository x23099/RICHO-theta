# 2026-10-06 Phase 5 v12 低速Kobuki実走行手順

## 目的

実Kobukiの`/odom`と実カメラを使い、正面の青箱へ低速で接近したときにTTC WARNINGが生成され、PC間relayを通ってG923へ通知されることを確認する。

新しい要素は「Kobukiの実走行」と「実ODOM」である。最初から物理FFBを使わず、同じ配置で次の順に進める。

1. 操縦・停止・ODOMの読み取り専用確認
2. 実走行 + adapter `dry_run`
3. dry-run合格後だけ、実走行 + adapter `hardware`、上限0.05

## 役割と安全条件

二人で実施する。

| 担当 | 役割 |
|---|---|
| 操縦者 | G923を軽く保持し、直進操作とFFB体感を担当する。指をスポーク内へ入れない |
| 安全担当 | Kobuki横で停止操作、進路、停止線、ケーブル、人の侵入を監視する |

- 平坦で幅1.5 m以上、前方2 m以上の空間を確保する。
- 青箱以外の人、椅子、ケーブルを走行帯から除く。
- 青箱はKobuki正面中央へ固定し、人が持たない。
- カメラから青箱までの初期距離を約1.30 m、停止線を約0.80 mにする。最大移動量は約0.50 mとする。
- 目標速度は0.20 m/s、許容目安は0.18～0.22 m/s、上限0.25 m/sとする。速度が安定しなくても上限と停止線を優先する。
- 警告がなくても停止線で必ず停止する。警告を出すために0.80 mより近づかない。
- steeringは中央を維持し、本日の初回試験では旋回、後退、遮蔽を行わない。
- G923は机へ固定し、FFB上限0.05、watchdog 0.10秒、challenge安全ゲートを変更しない。
- `dry_run`と`hardware` adapterを同時に起動しない。
- `/phase5/mock_odom` publisherを残さず、実`/odom`だけを使用する。
- 大容量ダウンロード、圧縮、Google Drive同期を録画と同時に行わない。

次のいずれかが起きたら直ちにアクセルを離し、ブレーキまたは非常停止でKobukiを止め、adapterも終了する。

- 0.25 m/sを超えた。
- 停止線を越えた、または直進を維持できない。
- 予期しない連続FFB、強い操舵力、振動の停止失敗。
- `/odom`、カメラ、challenge、statusの途絶。
- 複数のadapterまたは複数の`/cmd_vel`送信元を検出した。
- 人や物が走行帯へ入った。

## 1. 両PCの共通確認

両PCで、使用する各ターミナルの冒頭に次を設定する。

```bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "ROS_LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY"
```

Kobuki PCの`RICHO-theta`とハンコンPCのFFB側リポジトリで、意図したcommitへ揃っていることを確認する。

```bash
git status --short
git log -1 --oneline
```

未コミット変更がある場合は勝手に破棄しない。`run_field_experiment.py`はclean gitを要求するため、内容を確認してから整理する。

## 2. Kobukiと実ODOM

Kobuki PC `matunuc-NUC13ANHi5`で、通常使用している起動スクリプトからKobukiを起動する。

```bash
./start_kobuki_ffb.sh
```

別ターミナルで確認する。

```bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

ros2 topic info /odom -v
ros2 topic echo /odom --once
ros2 topic info /phase5/mock_odom -v
ros2 topic info /cmd_vel -v
```

続行条件は次のとおり。

- `/odom` publisherがKobukiの1件だけ。
- 停止中の`linear.x`と`angular.z`がほぼ0。
- `/phase5/mock_odom` publisherが0件、またはtopic自体が存在しない。
- `/cmd_vel`の送信元が、本日使用する操縦系1系統だけ。

### 操縦・停止確認

可能なら最初は車輪を床から浮かせる。既存のKobuki keyopまたは普段使用しているG923操縦系を起動し、次だけを短時間確認する。

1. 無入力で`/cmd_vel`が0。
2. 前進入力で`/odom.twist.twist.linear.x`が正。
3. 入力を離すかブレーキを踏むと0へ戻る。
4. 非常停止担当が即時停止できる。

この段階ではカメラ試験とhardware FFBを開始しない。

## 3. 青箱と停止線の配置

1. Kobukiを直進開始位置へ置き、steeringを中央にする。
2. カメラ正面中央、カメラから約1.30 mへ青箱を固定する。
3. カメラから約0.80 mの位置へ停止線を貼る。
4. GUIで青箱が`CAL`領域として安定検出されることを確認する。
5. 安全担当はKobuki側面に立ち、進路正面には入らない。

## 4. 第1段階：実走行dry-run

### 4.1 ハンコンPC adapter

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

pgrep -af collision_ffb_node

ros2 run oit collision_ffb_node --ros-args \
  -p output_mode:=dry_run \
  -p freshness_mode:=challenge \
  -p max_magnitude:=0.05 \
  -p challenge_max_age_sec:=0.1 \
  -p challenge_rate_hz:=50.0 \
  -p watchdog_timeout_sec:=0.1
```

`pgrep`で既存adapterが見つかった場合は、新しいadapterを起動せず、元のターミナルで安全に終了してからやり直す。起動ログが`mode=dry_run`であることを確認する。G923が振動した場合は設定違反として中止する。

### 4.2 両PCのbag

ハンコンPC：

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

mkdir -p ~/yopi_ws/ffb_recordings/2026-10-06
ros2 bag record \
  -o ~/yopi_ws/ffb_recordings/2026-10-06/phase5_v12_live_kobuki_dryrun_hsr_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /odom \
  /cmd_vel
```

Kobuki PC：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

mkdir -p ~/theta_ws/ffb_recordings/2026-10-06
ros2 bag record \
  -o ~/theta_ws/ffb_recordings/2026-10-06/phase5_v12_live_kobuki_dryrun_kobuki_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /odom \
  /cmd_vel
```

### 4.3 カメラとrelay

Kobuki PCの別ターミナル：

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
  --experiment-label phase5_v12_live_kobuki_dryrun_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /odom \
  --odom-timeout-sec 10
```

preflightがすべてPASSし、relayログに`stable=1.000s`、`stream_timeout=0.200s`、intent publish有効が表示されることを確認する。

### 4.4 走行

1. GUI録画を開始し、完全停止を約5秒記録する。
2. 安全担当が「進路よし、停止線よし」と確認する。
3. 操縦者はsteering中央で、約0.20 m/sを目安にゆっくり前進する。
4. GUIにWARNINGが表示されても、dry-runなのでG923は振動しない。
5. 操縦者はWARNING表示、停止線、または安全担当の停止指示のうち最も早い時点で停止する。
6. 停止後約5秒記録し、GUI録画を終了する。
7. camera、Kobuki PC bag、ハンコンPC bag、adapterの順に終了する。

停止線までにWARNINGが出なくても、それ以上接近しない。実速度が0.18 m/s未満の場合は停止線より前でTTC 4.6秒へ届かない可能性があるため、配置、ODOM速度、距離推定、TTCを解析してから再試験を判断する。

### 4.5 hardwareへ進む条件

次をすべて確認できた場合だけ第2段階へ進む。

- 実`/odom`が正方向で、最大速度0.25 m/s以下。
- 青箱が走行中に追跡され、WARNINGが成立する。
- active intent、command、statusが同じsequenceで対応する。
- statusが`output_mode=dry_run`、`action=apply`、`applied_magnitude<=0.05`。
- active欠落0、fault 0、最終inactive。
- 停止線を越えず、安全担当が即時停止できた。
- 実効FPS低下や通信断があっても、その事実を確認して原因を説明できる。

一つでも未確認ならhardwareへ進まず、dry-run記録を持ち帰って解析する。

## 5. 第2段階：実走行hardware

dry-runと同じ開始位置、青箱、停止線を使う。Kobuki PCのカメラ条件とbag topicも同じにし、ラベルと出力先だけ`hardware`へ変更する。

### 5.1 ハンコンPC adapter

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

`hardware backend armed`を確認する。別ターミナルでstatus publisherが1件であることも確認する。

```bash
ros2 topic info /collision/ffb_status -v
ros2 param get /collision_ffb_node output_mode
```

### 5.2 記録名

bagとカメラの起動コマンドはdry-runと同じで、次の名前へ変更する。

- ハンコンPC bag: `phase5_v12_live_kobuki_hardware_hsr_r01`
- Kobuki PC bag: `phase5_v12_live_kobuki_hardware_kobuki_r01`
- experiment label: `phase5_v12_live_kobuki_hardware_r01`

### 5.3 走行

1. 完全停止を約5秒録画する。
2. 操縦者はG923を軽く保持し、steering中央で前進する。
3. 3連FFBを感じたら直ちにアクセルを離して停止する。
4. FFBがなくても停止線で停止する。
5. 停止後、FFBが止まっていることを体感し、約5秒録画する。
6. 安全担当は停止距離と異常の有無を記録する。
7. 終了はcamera、両bag、adapterの順とし、adapterの`shutdown`を確認する。

初回hardware走行では1回だけ実施する。振動強度の引き上げ、CRITICALを狙った接近、遮蔽、旋回、連続反復は行わない。

## 6. 保存物

各段階について次を保存する。

- カメラ録画archive
- Kobuki PC rosbag archive
- ハンコンPC rosbag archive
- 操縦者の体感：振動回数、強さ、停止操作への影響
- 安全担当の記録：初期距離、停止線、推定最高速度、停止位置、異常の有無
- adapter起動・終了ログ

大容量archiveはGitへ追加せず、Google Driveの`raw/2026-10-06/`等へ保存する。解析結果は`Experimental_results/2026-10-06/`へ保存する。

## 7. 合格条件

実走行hardwareの合格条件は次のすべてである。

- カメラ録画3種とCSVのframe数が一致する。
- 実ODOMの速度方向が正で、最大0.25 m/s以下。
- 青箱追跡と有限TTCがWARNINGまで継続する。
- WARNING activeがintent→command→hardware statusへ欠落なく到達する。
- 体感が3連で、意図しない連続振動やUNKNOWN単発がない。
- applied magnitudeが0.05以下、fault 0。
- 停止後に`output_active=false`となり、終了時`shutdown`を確認する。
- 停止線を越えず、FFBが操縦・停止を妨げない。

FPS 30±1%は映像処理性能の正式基準として別に記録する。FPSだけが基準外の場合でもFFB経路の測定結果は破棄しないが、総合PASSと性能PASSを分けて記載する。
