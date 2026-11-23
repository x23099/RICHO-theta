# コーンFFB intentのグリッド評価 r01（2026-11-23）

## 1. 目的

[driver_cone_ffb_intent.py](../../../src/driver_cone_ffb_intent.py)（B案：側で方向、勾配で大きさ、3連続一致）を、実測グリッドで評価する。

入力：距離、box中心x、校正表、速度・ヨー。出力：left、勾配、risk_level、direction、magnitude、confirmed。

## 2. 条件

- 広ROIグリッド10枚（中央・左右25 cm、1.0/1.5/2.0 m）。
- 速度0.5 m/s、yaw0。各画像を3回提示（3連続一致のため）。
- 校正：`cx_ref=[306.5,308.2,305.7]`、左右別`k_L=[0.004158,0.005945,0.007732]`、`k_R=[0.003924,0.005341,0.006758]`。距離は校正端へクランプ。

## 3. 結果

[結果JSON](results_r01/evaluation.json) / [CSV](results_r01/cases.csv)

| 指標 | 値 |
|---|---:|
| 画像 | 10 |
| 評価可能（活動リスク＋距離あり） | **5** |
| 非活動または距離なし | 5 |
| **方向の不一致** | **0 / 5** |
| 確定（3連続） | 3（側のある3点） |
| 大きさ範囲 | 0〜0.40 |

評価可能5点の内訳：1.0 m中央/左、1.5 m中央/左/右。側のある3点はいずれも正しい方向で確定（左→−1、右→+1）。

## 4. 分かったこと

1. **左右別係数で1.5 m右の判定が改善**。共通係数ではleftが−0.29（corridor外）になりCLEARへ落ちたが、右用係数で−0.27（corridor内）となりWARNINGで方向+1が出た。**横位置の2〜3 cm誤差がリスク段階を変える**例。
2. **予測ホライズンが距離に届かない**。3.5 s×0.5 m/s＝1.75 mでは2.0 mのコーンが経路外。意図モジュールでは`horizon = max(3.5, (forward+0.5)/max(|v|,0.1))`に延長した。
3. ただし2.0 mは速度0.5 m/sでTTC≈4.3 sとなり、計画のWARNING閾値4 sを超えるため**PATH（非活動）**。方向の問題ではなく、リスク段階の設計どおり。
4. 1.0 m右は距離が保留（`colour_contour_reaches_roi_edge`）で評価不能。データ欠測として分離した。

## 5. 次の課題

- 2.0 mでの活動には、速度を上げる（0.6 m/s以上）か、WARNING閾値を距離に応じて見直す必要。**閾値の場当たり変更はしない**。
- 横位置の校正点追加（±0.15/±0.35、1.2/1.8 m）で、リスク段階の取り違えを減らす。
- ライブ接続では、`horizon`と校正表をconfigとして持つ。
- 3連続一致の遅延（0.4 s）と、側のフリップ時の保留を実機で確認。

## 6. 注意

- 実カメラ・GPU・ROS・FFBは未使用。`usable_for_ffb=false`。
- 入力のbox中心はログ済み（`selected_detector_boxes`）なので、ライブでも同じ計算が可能。
- 校正は取付依存。カメラを動かしたら再校正。

## 7. ライブdry-runの配線（実装済み）

受信UIの`--motion-distance`に、意図ログをopt-inで追加した。

- [driver_cone_ffb_intent_log.py](../../../src/driver_cone_ffb_intent_log.py)：`ConeFfbIntent`のドライバ。
- 校正表：[live_calibration_r01.json](live_calibration_r01.json)。

```bash
bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python <GPU python> --motion-weights <weights> \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir <新規> --motion-target-roi 150 0 450 720 \
  --cone-ffb-intent-dir recordings/2026-11-24/cone_intent_live_r01 \
  --cone-ffb-calibration Experimental_results/2026-11-23/cone_intent_eval_r01/live_calibration_r01.json
```

出力は`cone_ffb_intent.jsonl`と`cone_ffb_intent_summary.json`のみ。**ROS publish・G923出力はしない**（全行`published_to_ros=false`、`control_authority=false`）。

設計上の要点：

1. **ゲートはUI更新ではなく、異なるmotion結果だけで数える**。`motion.snapshot()`は24 Hzで呼ばれるが、同じ`(session, frame)`は1回しか`offer`しない。これがないと、同じ推論結果の3回繰り返しで誤確定する。
2. `motion_tap_busy`（一過性のロック競合）はゲートを破棄しない。それ以外の利用不可（stale/stopped/failed/session変更）は距離なしとして1回だけ記録し、ゲートをリセットする。
3. `box`が1個のときだけ中心を使う。複数・ゼロは`box_center_x=null`で保留。
4. `at_sec`は受信クロックの`source_time_sec`。3連続の最大経過は0.5 s。

画面の距離欄に`CONE INTENT (dry-run): dir=… mag=… LEVEL …`を併記する。ディレクトリは**新規**かつ`recordings/`配下のみ。既存ディレクトリ・校正なしの起動は拒否する。

**推論 cadence の前提**：ゲートは3件が0.5 s以内に揃う必要があるため、motion結果が**4 Hz未満**だと確定しない（保留のまま）。r04の実測は約28 Hz。火曜はUIのframe ageと結果更新間隔を確認し、4 Hzを下回る場合は確定しないことを「異常」ではなく設計どおり保留として扱う。`max_age_sec`は場当たりに変えない。
