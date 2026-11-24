# 火曜の実行コマンド集（2026-11-24）

**実行するのはこのファイルだけ。** 上から順に進める。背景・判定・理由は [README.md](README.md) を読む。

## 0. PCの役割

| PC | 動かすもの | このファイルの節 |
|---|---|---|
| **カメラPC** | 青障害物カメラ、`bird_eye`、`relay` | §1〜§5 |
| **ハンコンPC** | G923、`collision_ffb_node`/adapter、受信UI | §6 |
| **送信PC** | ロボットのカメラ送信（コーンdry-runのみ） | §6 |

- G923の`collision_ffb_node`/adapterは、**通常のhardwareモードで別途起動しておく**。このファイルでは起動しない。
- **adapterの`max_magnitude`**：[9/30手順 §5.1](../../2026-09-30/phase5_v12_low_speed_live_kobuki_procedure.md)のhardware起動をそのまま使うと`0.05`で、WARNING 0.25/CRITICAL 0.40がほとんど感じられない。今回の比較では**`max_magnitude:=0.40`以上**にする。`output_mode:=hardware`、`freshness_mode:=challenge`、`challenge_max_age_sec:=0.1`、`challenge_rate_hz:=50.0`、`watchdog_timeout_sec:=0.1`は9/30と同じ。`0.05`は初回hardware試験用のcapであり、システムの安全上限を変えるものではない。
- カメラPCとハンコンPCが同じ場合は、同じPCで該当節を実行する。

## 1. 変数を決める（カメラPC）

リポジトリrootは、`src/`と`Experimental_results/`があるディレクトリ。このマシンでは`~/theta_ws`。

```bash
cd ~/theta_ws
pwd
ls src/run_field_experiment.py

export PY=~/theta_ws/theta-env/bin/python3   # PySide6/ultralyticsが入っているenv
export DATE=2026-11-24
export RUN=ffb_policy_r01          # 再実行するときは別名にする
export ROOT=recordings/$DATE/$RUN
export BASE=src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json
export CAM=0                       # カメラ番号
export ODOM=/odom
```

`PY`とrepo rootを確認する。

```bash
ls -l "$PY"
"$PY" -c "import PySide6, ultralytics; print('env ok')"
```

`env ok`が出ない場合は、`find ~ -maxdepth 4 -path '*/bin/python3'`で候補を探し、`PY`をそのパスに変える。`src/run_field_experiment.py`が無ければrepo rootが違う。

```bash
mkdir -p "$ROOT"
cp Experimental_results/2026-11-24/ffb_policy_comparison_r01/record_template.csv "$ROOT/record.csv"
```

- `BASE`は**当日のG923経路のconfig**。v12は最有力候補だが、実運用が違えばそのパスに変える。
- `$ROOT`は新規名にする。既存名だと後の生成が失敗する（意図した安全側の失敗）。

## 2. M/A/Bのconfigを作る（カメラPC）

```bash
"$PY" Experimental_results/2026-11-24/ffb_policy_comparison_r01/make_condition_configs.py \
  --base "$BASE" \
  --output-dir "$ROOT/configs"
```

**確認する表示**：

```text
publish_enabled: 1
relay_enabled: 1
publish_topic: /collision/ffb_intent
```

`publish_enabled`が0なら**中止**。そのbaseではG923に力が出ない。

## 3. 事前検査（カメラPC、ハードウェア不要）

```bash
for spec in "M magnitude_only" "A gradient_direction" "B side_direction"; do
  set -- $spec
  "$PY" Experimental_results/2026-11-24/ffb_policy_comparison_r01/preflight.py \
    --config "$ROOT/configs/bird_eye_config_$1.json" --expect $2 || exit 1
done
```

3回とも `"ok": true` になること。`publish_enabled: 1`、`relay_enabled: 1`、`publish_topic: /collision/ffb_intent`も確認する。

続けてコーン設定を1回だけ検査する。

```bash
"$PY" Experimental_results/2026-11-24/ffb_policy_comparison_r01/preflight.py \
  --config "$ROOT/configs/bird_eye_config_B.json" --expect side_direction \
  --cone-intent-dir "$ROOT/cone_intent_live" \
  --cone-calibration Experimental_results/2026-11-23/cone_intent_eval_r01/live_calibration_r01.json
```

`cone_intent.ok: true` になること。`cone_intent_live`はまだ作らない（UIが起動時に作る）。

**別PC構成の場合**：このコーン検査は、受信UIを動かすハンコンPCで実行する。`$ROOT/configs/bird_eye_config_B.json`は`recordings/`配下でGit同期されないため、同じ相対パスへコピーしてから実行する。

## 4. ハードウェア確認（カメラPCとハンコンPC）

```bash
ls -l /dev/video*
lsusb | grep -iE 'logitech|wheel'
pgrep -af 'collision_ffb_node|bird_eye|webrtc_receive_ui'
```

- G923が見える。
- `collision_ffb_node`が**dry_runではない**モード。
- `constant_direction_sign`が実機で+1/-1のどちらか確認済み。
- telemetryの`linear_x`/`angular_z`が0固定でない。
- 操縦者以外の安全確認者がいる。

ハンコンPCでadapterの実効値を確認する。

```bash
ros2 param get /collision_ffb_node output_mode
ros2 param get /collision_ffb_node max_magnitude
ros2 topic info /collision/ffb_status -v
```

- `output_mode = hardware`
- `max_magnitude >= 0.40`（0.05のままならWARNING/CRITICALが弱すぎる）
- `/collision/ffb_status`のpublisherが1つ

## 5. M/A/Bを実施（カメラPC）

### 5.1 まずドライランでコマンド確認

```bash
"$PY" src/run_field_experiment.py \
  --config "$ROOT/configs/bird_eye_config_B.json" \
  --record-dir "$ROOT/bird_eye_B" \
  --experiment-label ffb_B_r01 \
  --camera-device "$CAM" --odom-topic "$ODOM" \
  --dry-run
```

表示される`FFB relay:`の行に、次の2つがあること。

```text
--challenge-stable-sec 1.0
--challenge-stream-timeout-sec 0.2
```

`Decision: DRY-RUN`ならOK。ここでは何も起動しない。

### 5.2 1条件ずつ本番

条件ごとに、**runner起動 → GUIで録画 → 2run → runner停止**を繰り返す。

```bash
# M
"$PY" src/run_field_experiment.py \
  --config "$ROOT/configs/bird_eye_config_M.json" \
  --record-dir "$ROOT/bird_eye_M" \
  --experiment-label ffb_M_r01 \
  --camera-device "$CAM" --odom-topic "$ODOM"
```

1. preflightがPASSし、bird_eyeのGUIが開く。
2. 青い障害物を**1.5 m**に置く（**A/Bで2.0 mは使わない**）。
3. GUIの**Start Recording** → 低速前進 → 障害物の側へ短く操舵 → 戻す、を3回 → **Stop Recording**。
4. `$ROOT/record.csv`のM, run=1に評定を記入。
5. 同じconfigのまま、もう1回 Start/Stop → run=2に記入。
6. runnerを`Ctrl-C`で停止する。

同じ手順でA、Bを実施する。

```bash
# A
"$PY" src/run_field_experiment.py \
  --config "$ROOT/configs/bird_eye_config_A.json" \
  --record-dir "$ROOT/bird_eye_A" \
  --experiment-label ffb_A_r01 \
  --camera-device "$CAM" --odom-topic "$ODOM"

# B
"$PY" src/run_field_experiment.py \
  --config "$ROOT/configs/bird_eye_config_B.json" \
  --record-dir "$ROOT/bird_eye_B" \
  --experiment-label ffb_B_r01 \
  --camera-device "$CAM" --odom-topic "$ODOM"
```

- `record.csv`の評定は、危険側/逆側の重さ1〜5、方向が逆に感じた回数、中止回数。
- **M/A/Bでrisk閾値を変えない。** 変えるのはconfig生成器が設定する方向の3項目だけ。

## 6. コーンintent dry-run（ハンコンPC、別セグメント）

**M/A/Bとは別**。青障害物の評定が終わってから、黄色コーンで実施する。G923へは出力しない。

- 別PC構成なら、先に§3のコーン検査をこのPCで済ませる。
- `cone_motion_live_r01`と`cone_intent_live_r01`は**新規**にする。既存なら`_r02`などに変える。

送信PCで通常のnative送信を起動しておく（前回と同じ）。

```bash
bash src/start_theta_stream_rtc.sh --motion-native --receiver-ip <RECEIVER_IP>
```

ハンコンPCで受信UIを起動する。`<GPU_PY>`と`<WEIGHTS>`は前回のr04と同じパス。

```bash
cd ~/theta_ws                      # このマシンのrepo root

export THETA_UI_PYTHON="$(command -v python3)"
export THETA_YELLOW_S_MIN=170

bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python <GPU_PY> \
  --motion-weights <WEIGHTS> \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir recordings/2026-11-24/cone_motion_live_r01 \
  --motion-target-roi 150 0 450 720 \
  --motion-experimental-rigid-mount \
  --cone-ffb-intent-dir recordings/2026-11-24/cone_intent_live_r01 \
  --cone-ffb-calibration Experimental_results/2026-11-23/cone_intent_eval_r01/live_calibration_r01.json
```

- 画面の距離欄に`CONE INTENT (dry-run): dir=… mag=… LEVEL …`が出る。
- telemetryが0固定でないことを先に確認する。
- 黄色コーンを映し、低速で短く走行する。コーンへ突っ込まない。
- 終了は**通常終了**（ウィンドウを閉じる）。`cone_ffb_intent_summary.json`が書かれる。
- 推論が4 Hz未満だと3連続が0.5 sに収まらず確定しない。**保留は設計どおり**。

## 7. 集計

### 7.1 評定＋bird_eyeログ

bird_eyeのCSVを探す。条件ごとに**run 1の代表1本**を自動で選ぶ（run 2は保管）。

```bash
LOG_M=$(find "$ROOT/bird_eye_M" -name detections.csv | sort | head -1)
LOG_A=$(find "$ROOT/bird_eye_A" -name detections.csv | sort | head -1)
LOG_B=$(find "$ROOT/bird_eye_B" -name detections.csv | sort | head -1)
printf 'M=%s\nA=%s\nB=%s\n' "$LOG_M" "$LOG_A" "$LOG_B"
```

3行とも空でないことを確認してから集計する。run 2を見る場合は`head -1`を`tail -1`に変える。

```bash
"$PY" Experimental_results/2026-11-24/ffb_policy_comparison_r01/analyse.py \
  --ratings "$ROOT/record.csv" \
  --log M="$LOG_M" --log A="$LOG_A" --log B="$LOG_B" \
  --output-dir Experimental_results/2026-11-24/ffb_policy_results_r01
```

`ffb_policy_results_r01`は**新規**であること。

### 7.2 コーンintentログ

```bash
"$PY" Experimental_results/2026-11-24/ffb_policy_comparison_r01/analyse_cone_intent.py \
  --intent recordings/2026-11-24/cone_intent_live_r01/cone_ffb_intent.jsonl \
  --output-dir Experimental_results/2026-11-24/cone_intent_live_analysis_r01
```

`authority_free: true`を確認する。falseなら解析に使わない。

## 8. 失敗したとき

| 表示 | 意味 | 対応 |
|---|---|---|
| `base config rejected: ... publish_enabled must be 1` | 表示専用configをbaseにした | 当日のFFB有効config（v12候補）を指定 |
| `expected side_direction: policy=...` | 条件とconfigが違う | **走行しない**。configと`--expect`を直す |
| `cone-intent directory must be NEW` | 前回のディレクトリが残っている | `RUN`を変える |
| runnerのpreflightがFAIL | カメラ/odom/空き容量/git dirty | 表示された項目を直す。`--allow-dirty-git`は意図があるときだけ |
| 受信UIに`CONE INTENT`が出ない | motion/telemetryが来ていない | `--motion-distance`、送信の`--motion-native`、GPUプロセスを確認 |
| Aで力が出ずBだけ出る | 2.0 mでAの勾配が経路外 | 1.5 mでやり直す。2.0 mはA/B比較に使わない |

## 9. やらないこと

- コーンintentをG923へpublishしない（今回の範囲外）。
- M/A/Bでrisk閾値・ホライズン・deadbandを変えない。
- 2.0 mでA/Bを比較しない。
- 既存の`recordings/`ディレクトリを上書きしない。
