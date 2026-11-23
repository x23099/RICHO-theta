# G923でのFFB方針比較 r01（2026-11-24）

## 1. 目的

危険側へ操舵したとき、どの方針が「より危険」と感じられるかを、G923の実力覚で比較する。

| 条件 | 方向の決め方 | 大きさ |
|---|---|---|
| **M: 大きさのみ** | 方向なし（`direction_enabled=0`） | risk_levelの基礎値 |
| **A: 勾配方向** | 勾配の符号（現行Phase 2） | risk_levelの基礎値 |
| **B: 側ベース** | 障害物の左右（`left_m`の符号） | risk_levelの基礎値 |

- Bは、強い同側旋回で勾配が幾何的に逆転しても方向を変えない。
- 今回は**方向の比較**に絞る。大きさの勾配変調（`1+0.6|g|`）は次段階。

## 2. 範囲（重要）

対象は**既存のbird_eye FFB経路（青い障害物）**。コーン距離→FFBのpublishはまだ未接続で、コーンは**dry-runログのみ**（§5.5）。したがって、M/A/Bの操舵感の評定にコーンログを混ぜて解釈しない。青い障害物と黄色コーンは別の検出器・別の入力（bird_eyeはローカルカメラ、コーンは受信UIのWebRTC映像）である。

## 3. 前提

- G923接続、FFBバックエンドがhardwareモードで動作（`direction_enabled`を条件ごとに設定）。
- bird_eyeと衝突FFBパブリッシャ/リレーが動作。
- 操縦者以外の安全確認者。低速・広い場所・接触しない軌道。
- `constant_direction_sign`は事前に実機で校准（+1/-1）。方向が逆なら、この試験の意味が反転するため最初に確認する。

## 3.5 プリフライト

条件ごとに、configの実効設定を確認する。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-24/ffb_policy_comparison_r01/preflight.py \
  --config <bird_eyeのconfig> --expect side_direction
```

`--expect`は`magnitude_only` / `gradient_direction` / `side_direction`。警告が出たら条件が意図と違う。

**publish経路も検査対象**：`publish_enabled=1`でなければG923に力が出ないため不合格。`relay_enabled`と`publish_topic`を表示し、relay有効なら`/collision/ffb_intent`、直接なら`/collision/ffb_command`が設定されているか確認する。

コーンdry-runも同じ日に実施する場合は、新規ディレクトリと校正表も同時に検査する。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-24/ffb_policy_comparison_r01/preflight.py \
  --config <bird_eyeのconfig> --expect side_direction \
  --cone-intent-dir recordings/2026-11-24/cone_intent_live_r01 \
  --cone-calibration Experimental_results/2026-11-23/cone_intent_eval_r01/live_calibration_r01.json
```

`cone_intent.ok`がfalseなら、その日にコーンログを取らない（UI起動時にも同じ検査で失敗する）。既存ディレクトリ・校正なし・`recordings/`外は拒否される。

3条件をまとめて検査する例：

```bash
for spec in "M magnitude_only" "A gradient_direction" "B side_direction"; do
  set -- $spec
  /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-24/ffb_policy_comparison_r01/preflight.py \
    --config Experimental_results/2026-11-24/ffb_configs_r01/bird_eye_config_$1.json \
    --expect $2 || exit 1
done
```

**ホライズン注意**：`collision_ffb_gradient_prediction_time_sec=3.5`は、0.5 m/sで**1.75 m**しか経路が届かない。障害物が2.0 mにあるとコーン/障害物が経路外になり、CLEAR/PATHで力が出ない。2.0 mで評価するなら速度を上げる（0.7 m/s以上）か、ホライズンを延ばす。**場当たりの閾値変更はしない**。

## 4. 設定（bird_eyeのconfig）

`collision_ffb_direction_enabled`と`collision_ffb_mapping_policy`を条件ごとに変える。

| 条件 | `collision_ffb_direction_enabled` | `collision_ffb_mapping_policy` | FFB node `direction_enabled` |
|---|---:|---|---|
| M | 0 | （任意） | false |
| A | 1 | `gradient_direction` | true |
| B | 1 | `side_direction` | true |

Bの追加パラメータ：`"collision_ffb_side_deadband_m": 0.05`。

条件別configは、**その日のFFB有効config**から生成する。表示専用の`src/bird_eye_config.json`は`collision_ffb_publish_enabled=0`なので、生成器が拒否する（11/23実測）。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-24/ffb_policy_comparison_r01/make_condition_configs.py \
  --base <その日のFFB有効config> \
  --output-dir Experimental_results/2026-11-24/ffb_configs_r01
```

- `collision_ffb_publish_enabled=1`が必須。
- relay有効なら`collision_ffb_intent_topic`、直接なら`collision_ffb_command_topic`が必要。
- 生成されるのは`bird_eye_config_M/A/B.json`。**他のキーはbaseのまま**（risk閾値・cadence・ホライズンを勝手に変えない）。
- relay経路の候補は`src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`（publish=1、relay=1、intent topicあり）。ただし**当日の実運用configが正**であり、これを機械的に固定しない。
- 生成後、3条件すべてを§3.5で検査する。Mは`direction_enabled=0`なのでpolicy値は問わない。

- 未知のpolicyは`gradient_direction`へフォールバックする。設定後、ログの`mapping_policy`（gradient結果）で意図した値か確認する。
- 条件を変えたら**bird_eyeを再起動**する（パラメータは起動時読み込み）。

## 5. 走行・操作

1. 青い障害物を前方1.5〜2.0 mに置く。
2. 低速で前進し、**障害物の側へ短く操舵** → 戻す、を3回。
3. 各条件で同じ軌道・同じ速度を心がける。
4. 各条件の後に評定：
   - 「危険側へ切ったときの重さ」1（軽い）〜5（非常に重い）
   - 「逆側へ切ったときの重さ」1〜5
   - 方向が逆に感じた回数
   - 危険と感じて操作をやめた回数
5. 条件の順序は M → A → B、可能なら B → A → M の2順で（順序効果の確認）。

## 5.5 コーンintentのdry-run（同日・別セグメント）

**目的**：コーン距離→B案intentのライブ経路を、実機で**記録だけ**確認する。G923へは出力しない（`published_to_ros=false`、`control_authority=false`）。

**M/A/Bとの関係**：青い障害物の操舵感の評定とは別。コーンログの方向・大きさをM/A/Bの評定根拠にしない。同じ日に、安全な場所で黄色コーンをロボットのカメラに映す**別セグメント**として実施する。

```bash
export THETA_UI_PYTHON="$(command -v python3)"
export THETA_YELLOW_S_MIN=170
bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python <GPU python> --motion-weights <weights> \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir recordings/2026-11-24/cone_motion_live_r01 \
  --motion-target-roi 150 0 450 720 --motion-experimental-rigid-mount \
  --cone-ffb-intent-dir recordings/2026-11-24/cone_intent_live_r01 \
  --cone-ffb-calibration Experimental_results/2026-11-23/cone_intent_eval_r01/live_calibration_r01.json
```

- 1セグメントにつき**新規ディレクトリ**。既存を使い回さない。
- 画面の距離欄に`CONE INTENT (dry-run): dir=… mag=… LEVEL …`が出る。
- 確認すること：
  1. telemetryが流れ、`linear_x`/`angular_z`が0固定でない。
  2. 推論結果の更新間隔（4 Hz未満だと3連続が0.5 sに収まらず確定しない。**保留は設計どおり**）。
  3. 側を変えたとき、3件目の新しい結果で`CONFIRMED`になり、方向が側と一致する。
  4. `left`の推定が校正点（1.0/1.5/2.0 m、±0.25 m）と大きくずれない。
- 走行は低速・接触しない軌道。コーンへ向かって突っ込む試験はしない。
- UIを**通常終了**すると`cone_ffb_intent_summary.json`が書かれる。強制終了するとJSONLだけ残る。

## 6. 記録

- **評定シート**：[record_template.csv](record_template.csv)を埋める（危険側/逆側の重さ1〜5、方向逆の回数、中止回数、メモ）。条件ごとに2run。
- **bird_eyeの記録CSV**：Start Recordingで保存する。`collision_ffb_direction`、`requested_magnitude`、`risk_level`などが列に含まれる。条件ごとに別ファイル。
- 実際の操舵・速度（telemetry/odom）。
- 気づいた点（引っかかり、振動、遅れ）。

### 集計

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-24/ffb_policy_comparison_r01/analyse.py   --ratings <記入済みrecord.csv>   --log M=<Mの記録CSV> --log A=<Aの記録CSV> --log B=<Bの記録CSV>   --output-dir Experimental_results/2026-11-24/ffb_policy_comparison_r01/results_r01
```

評定の平均、方向逆の合計、ログの方向/大きさ/リスク段階の分布をまとめる。**1被験者・非盲検の探索**として扱い、統計的結論にはしない。

### コーンintentログの集計

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-24/ffb_policy_comparison_r01/analyse_cone_intent.py \
  --intent recordings/2026-11-24/cone_intent_live_r01/cone_ffb_intent.jsonl \
  --output-dir Experimental_results/2026-11-24/cone_intent_live_analysis_r01
```

- 記録数、異なるframe数、確定数、側エピソード数
- **確定までの遅延**（sideエピソード開始→最初の`confirmed`）。0.5 s超の空白はゲートと同じく別エピソードとして切る。
- 生の側の反転回数と、出力方向の反転回数
- 更新cadence（median/p90/max）
- 確定時の大きさ分布、`authority_free`
- 末尾の不完全行は`truncated_final_lines`として数え、途中の壊れた行はエラーにする。

**リプレイ検証（ライブではない）**：`driver_motion_yellow_r04.tar.xz`の距離あり・box 1個の2000 frameを新ロガーへ通し、解析器まで完走した。cadence中央33.5 ms / p90 40.6 ms、側エピソード2（12.8 sの空白で分割）、確定遅延70.3/87.7/105.2 ms、確定186件、`authority_free=true`。実機・G923・publishなし。この数値はロガー/解析器の経路検証であり、火曜のライブ結果ではない。

`authority_free=false`なら、そのログは解析に使わない（publish/authorityフラグが立っている）。

## 7. 判定（探索的）

- **Bで「危険側が重い」の評定がAより高いか。**
- Aで「方向が逆」「戻すと重い」と感じた場面があるか（幾何逆転の体感）。
- Mとの差（方向情報の有無が危険感に効くか）。
- 1被験者・非盲検の探索であり、統計的な結論にはしない。

## 8. 安全

- 接触しない軌道を最優先。速度は最低速。安全確認者が即停止できる状態。
- 方向が逆に出た、または予期しない力が出た場合は即中止し、`constant_direction_sign`とpolicyの設定を確認する。
- FFBの期限・強度上限・単一writerは変更しない。

## 9. 当日チェックリスト

**2026-11-23 21:44時点の実測**：`/dev/video*`なし、Logitech/G923のUSBなし。そのため実機実施は火曜へ延期。実行前に次を確認する。

```bash
date
ls -l /dev/video*                 # カメラ
lsusb | grep -iE 'logitech|wheel' # G923
pgrep -af 'collision_ffb_node|bird_eye|webrtc_receive_ui'
```

- [ ] G923がUSBで見え、`collision_ffb_node`が**dry_runではない**モードで動く（11/23は`output_mode:=dry_run`が動いていた）。
- [ ] `make_condition_configs.py`でM/A/Bを生成し、baseが`publish_enabled=1`。relay有効ならrelayノードも動作。
- [ ] `constant_direction_sign`を実機で確認（+1/-1）。
- [ ] telemetryの`linear_x`/`angular_z`が変化する（0固定でない）。
- [ ] **新規**の`--motion-output-dir`と`--cone-ffb-intent-dir`を用意（既存・`recordings/`外は拒否）。
- [ ] §3.5のプリフライトで、3条件すべて`ok: true`（`--expect`と`cone_intent.ok`、`publish_enabled=1`）。
- [ ] 操縦者以外の安全確認者、接触しない軌道、即停止できる状態。
- [ ] 各条件の前後で評定シートを記入。コーンdry-runは別セグメントとして記録。
- [ ] 終了後、`record.csv`・bird_eye CSV・`cone_ffb_intent.jsonl`/summaryを保存し、§6の2つの集計を実行。
