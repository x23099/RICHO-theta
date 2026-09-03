# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- one or more fixed dynamic TTC conditions failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/202609031545.tar.xz` |
| SHA-256 | `f6acc155ca993fa7c1c3efa40ce25b2593fd0e2a4216de85917041748bec68dd` |
| サイズ | 255,103,600 bytes |
| セッション | 5 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_conservative_candidate_20260903.json` |
| ゲート評価しきい値 | 2000 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p20_r01_20260903_153413_843 | 499 | 499/499/499 | PASS | PASS | PASS |
| approach_center_v0p20_r02_20260903_154255_459 | 518 | 518/518/518 | PASS | PASS | PASS |
| approach_center_v0p20_r03_20260903_154331_538 | 501 | 501/501/501 | PASS | PASS | PASS |
| retreat_center_v0p10_r01_20260903_154413_782 | 599 | 599/599/599 | PASS | PASS | PASS |
| static_center_ttc_r01_20260903_153206_220 | 448 | 448/448/448 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p20_r01 | 499 | 29.995 | 100.00% | 100.00% | 100.00% | 100.00% | 25.40 ms |
| approach_center_v0p20_r02 | 518 | 30.041 | 100.00% | 100.00% | 100.00% | 100.00% | 32.75 ms |
| approach_center_v0p20_r03 | 501 | 30.012 | 100.00% | 100.00% | 100.00% | 100.00% | 30.69 ms |
| retreat_center_v0p10_r01 | 599 | 29.975 | 100.00% | 100.00% | 100.00% | 100.00% | 31.11 ms |
| static_center_ttc_r01 | 448 | 30.017 | 100.00% | 100.00% | 100.00% | 100.00% | 27.95 ms |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_20260903_153413_843 | 100.00% | 0.0863 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_20260903_154255_459 | 100.00% | 0.0809 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_20260903_154331_538 | 100.00% | 0.0783 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r01_20260903_154413_782 | 99.73% | 0.0855 | 0/0 | 0/0 | FAIL |
| static_center_ttc_r01_20260903_153206_220 | 99.78% | 0.0105 | 0/0 | 0/0 | PASS |

動的TTC対象sessionのゲート再生は診断値として保存するが、静的位置外れ値判定を総合判定へは加えない。

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- static_no_false_ttc: **PASS**
- v0p10_retreat_no_false_ttc: **PASS**
- v0p20_approach_warning: **PASS**

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile_v4_candidate.json`

| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | 方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_20260903_153413_843 | 222 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r02_20260903_154255_459 | 212 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r03_20260903_154331_538 | 216 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 0/0 | FAIL |
| retreat_center_v0p10_r01_20260903_154413_782 | 204 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0172 m/s | ― | 0/0 | PASS |

## 成果物

- `archive_inventory.csv`
- `session_integrity.csv`
- `live_summary.csv`
- `processing_timing.csv`
- `lateral_summary.csv`
- `observation_replay.csv`
- `gate_regression.csv`
- `requirements_results.csv`
- `dynamic_ttc_results.csv`
