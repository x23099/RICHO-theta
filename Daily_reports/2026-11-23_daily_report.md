# 2026-11-23 日報：コーンFFB intentのB案・横位置校正・ライブdry-run配線・火曜実験準備

## 1. 到達点

1. **B案（障害物の側で方向、勾配は大きさ）を実装**し、80評価でA案の「側と方向の不一致」6/80を**0/80**にした。強い同側旋回で勾配が幾何的に逆転しても、方向は障害物の側のまま。
2. **3連続一致が実距離系列の方向反転を完全に除去**した。生の反転は最大19（150L）だったが、確定後は全系列で**0**。ライブr04（2,113 frame）も生7→確定0。
3. **横位置の経験的校正**を試作。共通係数のleave-one-outは最大32.2 mm/RMS 20.2 mm、左右別係数はin-sampleで最大9.4 mm/RMS 4.4 mm。側の符号は**7/7正解**。
4. **コーンintent（B案＋3連続SideGate）を実測グリッドで評価**。評価可能5点で**方向不一致0**、側のある3点は左→−1・右→+1で確定。
5. **コーンintentのライブdry-run配線**を実装。motion結果のbox中心をUIへ通し、`(session, frame)`が変わったときだけゲートへ投入。**publishなし・G923なし**。
6. **火曜のM/A/B＋コーンdry-runの準備**を完了。条件別config生成、preflight、ログ解析、当日チェックリストを用意。既定configが`publish_enabled=0`で「力が出ない」罠を検出した。
7. 実機・カメラがないため、**M/A/Bとコーンdry-runの実機実行は火曜へ延期**。

## 2. 作業条件・Git状態

- 作業日は2026-11-23。**自宅・カメラなし・G923なしのオフライン作業**。
- 21:44時点の実測：`/dev/video*`なし、Logitech/G923のUSBなし、`collision_ffb_node`は`output_mode:=dry_run`で稼働。
- 11/23の作業開始時点で当日commitなし。直近commitは`b74a5f4`（11/21）。
- 本日分は日報作成後に1 commitへまとめる。pushはしない。
- 本日の解析・配線は**ROSへpublishせず、FFB/G923を駆動しない**。

## 3. 実施内容

### 3.1 静止系列と時間一致

- [静止9位置](2026-11-21_daily_report.md)の距離系列を、最長の連続数値区間で再集計。[結果](../Experimental_results/2026-11-23/static_series_analysis_r01/results_r01/static_series.json)
- 5 Hzへ再サンプルし、合成yaw（±0.15/±0.3）・速度0.2/0.4で勾配を計算。`DirectionConsistency`（3連続一致）を適用。[結果](../Experimental_results/2026-11-23/gradient_series_r01/results_r01/gradient_series.json)
- 空白後の古い票と交互入力の反転を防ぐため、**3連続一致＋票の個別失効**を維持。

### 3.2 Δ・予測時間の感度と連続リスク

- 8位置×速度2×yaw5＝80評価/条件で、Δ（0.05/0.10/0.15）と予測時間（1.5/3.5 s）を比較。[結果](../Experimental_results/2026-11-23/delta_horizon_sensitivity_r01/results_r01/sensitivity.json)
- 同側yawの符号反転について、corridor二値のせいか検証するため4方式を比較。[結果](../Experimental_results/2026-11-23/continuous_risk_r01/results_r01/comparison.json)
- **結論：符号反転はモデルの誤りではなく、強い同側旋回で予測経路がコーンの外側を回り込む幾何的な結果**。連続化・経路打ち切りでは消えない。

### 3.3 横位置の経験的校正

- 広ROIグリッド10枚（中央・左右25 cm、1.0/1.5/2.0 m）から、`left ≈ k(d)·(cx_ref(d) − cx)`を最小二乗で校正。[結果](../Experimental_results/2026-11-23/lateral_estimate_r01/results_r01/calibration.json)
- 共通係数と左右別係数を、leave-one-outとcross-distanceで検証。[結果](../Experimental_results/2026-11-23/lateral_estimate_r01/validation_r01/validation.json)
- ライブ用の校正表：[live_calibration_r01.json](../Experimental_results/2026-11-23/cone_intent_eval_r01/live_calibration_r01.json)。

### 3.4 B案とコーンintent

- [driver_ffb_side_mapping.py](../src/driver_ffb_side_mapping.py)：方向は`left`の符号、大きさは`risk_level`基礎値×`(1+0.6|g|)`。±0.05 mの中央デッドバンド。
- [driver_cone_ffb_intent.py](../src/driver_cone_ffb_intent.py)：距離・box中心・速度・yawから`left`→勾配→B案→3連続SideGate。予測ホライズンは`max(3.5,(forward+0.5)/max(|v|,0.1))`。
- [グリッド評価](../Experimental_results/2026-11-23/cone_intent_eval_r01/README.md)：10枚、各3回提示。

### 3.5 ライブdry-run配線

- [driver_motion_protocol.py](../src/driver_motion_protocol.py)：`compact_result`/`checked_result`が`selected_detector_boxes`と`support_pixel`をUIへ通す。`checked_boxes`は6つの数値fieldを必須、`image`/`prediction_index`は任意。画像・support配列は越えさせない。
- [driver_cone_ffb_intent_log.py](../src/driver_cone_ffb_intent_log.py)：`motion.snapshot()`の距離・box中心と`odom_node.linear_x/angular_z`からintentを計算し、JSONLとsummaryへ記録。
- [webrtc_receive_ui.py](../src/webrtc_receive_ui.py)：`--cone-ffb-intent-dir`（新規・`recordings/`配下）と`--cone-ffb-calibration`を追加。画面に`CONE INTENT (dry-run)`を併記。
- **同じ`(session, frame)`は1回しかゲートへ入れない**。UIの24 Hz更新で同じ推論結果を3連続扱いにする誤確定を防ぐ。`motion_tap_busy`だけは保留、他の利用不可は1回記録してリセット。

### 3.6 火曜の準備

- [手順書](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/README.md)を更新（§3.5プリフライト、§4 config生成、§5.5コーンdry-run、§6解析、§9当日チェックリスト）。
- [make_condition_configs.py](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/make_condition_configs.py)：当日のFFB有効configからM/A/Bを生成。`publish_enabled=1`とrelay/直接経路のtopicを必須化。
- [preflight.py](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/preflight.py)：publish/relay/topic、条件一致、コーンintentのディレクトリ・校正表を検査。
- [analyse_cone_intent.py](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/analyse_cone_intent.py)：確定遅延・側/出力反転・cadence・大きさ分布・`authority_free`を集計。

## 4. 定量結果

### 4.1 静止9位置（最長連続区間）

| 位置 | 数値率 | run frame | 中央値 m | stdev mm | 全幅 mm | 連続差p95 mm | gate遷移 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 100C | 96.6% | 742 | 1.0298 | 4.43 | 27.6 | 1.64 | 1 |
| 100L | 96.4% | 1,012 | 1.0800 | 13.96 | 34.3 | 2.36 | 1 |
| 100R | 97.7% | 866 | 1.0791 | 13.43 | 30.9 | 1.26 | 1 |
| 150C | 99.8% | 932 | 1.5904 | 10.60 | 58.5 | 5.39 | 3 |
| 150L | 87.4% | 853 | 1.6426 | 8.89 | 53.3 | 4.68 | 13 |
| 150R | 97.7% | 1,300 | 1.6131 | 0.73 | 4.8 | 0.86 | 9 |
| 200C | 99.1% | 868 | 2.1235 | 4.67 | 13.4 | 8.74 | 5 |
| 200L | 97.9% | 1,166 | 2.1766 | 23.47 | 105.9 | 5.62 | 1 |
| 200R | 99.4% | 546 | 2.1782 | 5.42 | 93.2 | 0.00 | 7 |

- フレーム間の揺れは小さい（連続差p95で0.9〜8.7 mm）。
- run全体では最大106 mmのゆっくりしたドリフト（200L）。設置・架台の微小移動を含む可能性があり、**原因は未確認**。

### 4.2 勾配系列と3連続一致

| 系列 | 確定率 | 生の方向反転（最大） | 確定後の方向反転 |
|---|---:|---:|---:|
| 100C/L/R | 98.2〜98.7% | 0 | **0** |
| 150C | 98.8% | 0 | **0** |
| 150L | 76.7〜96.2% | **19** | **0** |
| 150R | 98.6〜98.9% | 1 | **0** |
| 200C | 96.7〜97.8% | 1 | **0** |
| 200L/R | 98.4〜98.9% | 0 | **0** |
| ライブr04 | 98.5〜99.0% | 7 | **0** |

- 実系列では3連続一致が方向反転をすべて除去。代償は1〜3%の保留（150Lは23%）。

### 4.3 Δ・予測時間の感度（80評価/条件）

| Δ rad/s | デッドバンド内 | 側と符号逆 | ±1 cmで方向変化 |
|---:|---:|---:|---:|
| **0.05** | 66（82.5%） | **3** | **0** |
| 0.10 | 62（77.5%） | 6 | 0 |
| 0.15 | 55（68.8%） | 7 | 4 |

- 予測時間1.5 sと3.5 sで結果は同一。この条件ではホライズンが効いていない。
- Δ=0.05は安定だがデッドバンド内が増える。**Δの調整だけでは符号反転を解消しない**。

### 4.4 連続リスクの比較（同側yawの符号反転）

| 方式 | デッドバンド内 | 側と符号逆 | ±1 cmで方向変化 |
|---|---:|---:|---:|
| 既存（corridor二値＋eta） | 62/80 | 6 | 0 |
| 連続clearance | 56/80 | 8 | 1 |
| 経路打ち切り（二値） | 62/80 | 6 | 0 |
| 打ち切り＋連続 | 56/80 | 8 | 1 |

- 1.0 m左25 cm・0.4 m/sで、yaw 0.15/0.30/0.45のclearanceは**−0.154/+0.014/+0.182 m**。
- 強い左旋回では予測経路がコーンの左側を回り込む。したがって「さらに左へ切る方が安全」という勾配は**幾何的に正しい**。corridor二値のアーティファクトではない。

### 4.5 横位置校正の検証

| 検証 | 件数 | 絶対最大 | RMS |
|---|---:|---:|---:|
| 共通kのin-sample | 7 | 22.7 mm | 11.9 mm |
| 共通kのleave-one-out | 7 | **32.2 mm** | **20.2 mm** |
| 距離を抜いて予測（cross-distance） | 7 | **39.6 mm** | **24.1 mm** |
| 左右別k（in-sample） | 7 | 9.4 mm | 4.4 mm |
| 側の符号（±0.25 mの7点） | 7 | — | **7/7 正解** |

- 一般化誤差は2〜3 cm。**側の判定には使えるが、勾配の`left`値は±2〜3 cmの誤差**。
- 左右別kはin-sampleでは良いが、点が少なく過拟合の可能性。out-of-sampleは未確認。

### 4.6 B案とA案の比較（80評価）

| 指標 | A（勾配方向） | B（側ベース） |
|---|---:|---:|
| 障害物の側と方向が不一致 | **6/80** | **0/80** |
| 方向の内訳（左/なし/右） | 9/62/9 | 4/74/2 |
| 大きさの範囲 | — | 0〜0.40 |

- Aの不一致6件はすべてBで解消。Bの方向0が多いのは、中央配置とCLEAR/PATH（非活動）を含むため。

### 4.7 コーンintentのグリッド評価

| 指標 | 値 |
|---|---:|
| 画像 | 10 |
| 評価可能（活動リスク＋距離あり） | **5** |
| 非活動または距離なし | 5 |
| **方向の不一致** | **0/5** |
| 確定（3連続） | 3（側のある3点） |
| 大きさ範囲 | 0〜0.40 |

- 左右別係数により、1.5 m右が共通係数のCLEARからWARNINGへ改善。**横位置2〜3 cmの差がリスク段階を変える**実例。
- 2.0 mは0.5 m/sでTTC≈4.3 s→PATH（非活動）。方向の誤りではない。

### 4.8 ライブ配線のリプレイ検証（ライブではない）

`driver_motion_yellow_r04.tar.xz`の距離あり・box 1個の2,000 frameを新ロガーへ通し、解析器まで完走。

| 指標 | 値 |
|---|---:|
| 記録/書込 | 2,000 / 2,000 |
| cadence 中央 / p90 / 最大 | 33.5 ms / 40.6 ms / 12.797 s |
| 側エピソード | 2（12.8 sの空白で分割） |
| 確定遅延 最小/中央/最大 | 70.3 / 87.7 / 105.2 ms |
| 確定件数 | 186 |
| `authority_free` | true |

- 実機・G923・publishなし。**ロガー/解析器の経路検証であり、火曜のライブ結果ではない**。

### 4.9 テスト・プリフライト

| 検証 | 結果 |
|---|---:|
| driver全体（`tests/test_driver_*.py`） | **487 passed** |
| 関連スイート（intent・B mapping・consistency・bird_eye・cone・FFB） | **135 passed** |
| protocol/body display | **47 passed** |
| 比較ツール＋intent log | **26 passed** |
| v12 relay config由来のM/A/Bプリフライト | **3/3 ok** |
| 既定config（publish=0） | 生成拒否・不合格 |
| ドキュメントのリンク切れ | 0 |

## 5. 判断

1. **B案を採用**。方向は障害物の側、勾配は大きさのみ。幾何的な符号反転を方向に出さない。
2. **時間方向一致は3連続**（2-of-3多数決ではない）＋票の個別失効。追加遅延は遷移時最大0.4 s。
3. **黄色コーンのS下限は170**。既定80は不変、実験用に上書き可能。
4. **ライブのゲートは異なるmotion結果だけで数える**。UI更新や同一frameの再投入では確定しない。
5. **横位置は側判定用**。勾配の値は参考値。校正点の追加（±0.15/±0.35、1.2/1.8 m）が必要。
6. **コーン→FFBのpublishはまだ接続しない**。火曜の方向比較を終えるまで経路を変えない。
7. **2.0 mのPATHは設計どおり**。TTC閾値4 sに対する速度0.5 m/sの結果で、方向の問題ではない。
8. **v12 relay configは最有力候補**。v10/v11/v12のFFB transportは同一で、v12はv11のstream/rearm問題を修正し、9/29にG923実機でWARNING/UNKNOWNを確認済み。公式preflightのconfig検査も0エラー。ただしrisk閾値は既定configと異なる（warning 4.6 s vs 4.0 s、exit 5.6 s vs 5.0 s、conservative vs visual、area 1450 vs 2503）。M/A/Bで同一baseを使い、方向比較のために閾値を変えない。
9. **A/Bの比較は1.5 m**。2.0 mでは3.5 s×0.5 m/s＝1.75 mでAの勾配が経路外になる一方、BはTTCと側で発火し得るため、方向方針の比較条件にならない。

## 6. 未実施・課題

- **火曜の実機**：M/A/B（bird_eye、青障害物）とコーンdry-run。今日はカメラ・G923がないため未実施。
- **base configの確定**：当日のG923経路で使うconfigを指定する必要がある。候補はv12 relay configだが固定しない。
- **publish配線と調停**：コーンintentを既存の`/collision/ffb_command`へ直接混ぜず、別トピック／単一ownerの設計が必要。実機駆動前に承認。
- **大きさ変調**：方向比較の後の条件。`base×(1+0.6|g|)`はintent側に実装済み、publisher配線が未実施。
- **校正点の追加**：cross-distanceの信頼性向上。火曜以降に撮影。
- **150Lの`ambiguous_front_cones` 134件**と**200Lの106 mmドリフト**：原因未確認。設置・架台・背景の影響を切り分ける。
- **カメラ画像の代表資料**：今日はオフラインでカメラ画像を生成していない。report_assetsはJSONのみ。

## 7. 火曜の実験手順書

**場所**：[Experimental_results/2026-11-24/ffb_policy_comparison_r01/README.md](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/README.md)

含まれる内容：

- §3.5 プリフライト（M/A/B＋コーン設定）
- §4 条件別configの生成（`make_condition_configs.py`、`publish_enabled=1`必須）
- §5 M/A/Bの走行・評定
- §5.5 コーンintent dry-run（**別セグメント**、publishなし）
- §6 評定・bird_eyeログ・コーンログの集計
- §9 当日チェックリスト（G923、FFBモード、telemetry、新規ディレクトリ、安全）

**adapterの注意**：Phase 4 hardwareの安全上限は`max_magnitude=0.05`。`0.40`は起動時に拒否される（11/24実測: `ValueError: Phase 4 hardware mode requires max_magnitude <= 0.05`）。WARNING 0.25/CRITICAL 0.40は0.05にクリップされるため、方向の比較を主とし、大きさの評定は参考扱い。上限は変更しない。

実行順：base config確認（v12 relayが最有力候補）→ M/A/B生成 → 3条件＋コーン設定のpreflight → 公式runnerで起動 → 実機確認 → M/A/B（**A/Bは1.5 m**）→ コーンdry-run → 2つの集計。

## 8. 成果物

### 実装

- [driver_ffb_side_mapping.py](../src/driver_ffb_side_mapping.py)
- [driver_cone_ffb_intent.py](../src/driver_cone_ffb_intent.py)
- [driver_cone_ffb_intent_log.py](../src/driver_cone_ffb_intent_log.py)
- [driver_motion_protocol.py](../src/driver_motion_protocol.py)
- [webrtc_receive_ui.py](../src/webrtc_receive_ui.py)
- [bird_eye.py](../src/bird_eye.py)（`collision_ffb_mapping_policy`）

### 実験・解析

- [2026-11-23 オフライン解析の索引](../Experimental_results/2026-11-23/README.md)
- [コーンintentグリッド評価](../Experimental_results/2026-11-23/cone_intent_eval_r01/README.md)
- [横位置校正と検証](../Experimental_results/2026-11-23/lateral_estimate_r01/README.md)
- [コーン→FFB接続設計](../Experimental_results/2026-11-23/cone_ffb_integration_r01/README.md)
- [火曜の手順・config生成・preflight・解析](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/README.md)
- [代表資料](../Experimental_results/2026-11-23/report_assets/README.md)（JSON 3点）

### テスト

- [test_driver_ffb_side_mapping.py](../tests/test_driver_ffb_side_mapping.py)
- [test_driver_cone_ffb_intent.py](../tests/test_driver_cone_ffb_intent.py)
- [test_driver_cone_ffb_intent_log.py](../tests/test_driver_cone_ffb_intent_log.py)
- [test_ffb_policy_comparison_tools.py](../tests/test_ffb_policy_comparison_tools.py)

## 9. 測定と推測の区別

**測定（今日の結果JSON・テスト・実測）**

- 静止9位置の数値率・中央値・揺れ・ドリフト。
- 3連続一致後の方向反転0、生の反転数。
- Δ感度、連続リスクの比較、側マッピングのA/B不一致数。
- 横位置校正の残差、側符号7/7。
- グリッドintentの方向不一致0/5。
- 2,000 frameリプレイのcadence・確定遅延。
- テスト通過数、preflightの合否。
- 21:44時点のカメラ/G923/FFBモードの不在。

**推測・未確認**

- 150Lの複数候補混入（人・椅子など）と200Lのドリフト原因。
- 左右別係数のout-of-sample性能（点が少なく過拟合の可能性）。
- 火曜の実機でB案が「危険側が重い」と感じられるか。1被験者・非盲検の探索であり、統計的結論にはしない。
- 当日のbase configがv12であること（候補にすぎない）。
