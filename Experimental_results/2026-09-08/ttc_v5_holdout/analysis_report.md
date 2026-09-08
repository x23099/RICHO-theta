# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- effective FPS is outside ±1%
- one or more predefined requirements failed
- one or more fixed dynamic TTC conditions failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/202609081440.tar.xz` |
| SHA-256 | `e4c5f776fe5bcad5d99becf3cce380cccc2bf662e3bcf7e80ddf68414fba710d` |
| サイズ | 705,592,044 bytes |
| セッション | 12 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_conservative_candidate_20260903.json` |
| ゲート評価しきい値 | 2000 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p10_r01_20260908_143110_750 | 605 | 605/605/605 | PASS | PASS | PASS |
| approach_center_v0p10_r02_20260908_143603_134 | 605 | 605/605/605 | PASS | PASS | PASS |
| approach_center_v0p10_r03_20260908_144024_286 | 622 | 622/622/622 | PASS | PASS | PASS |
| approach_center_v0p20_r01_20260908_143413_255 | 390 | 390/390/390 | PASS | PASS | PASS |
| approach_center_v0p20_r02_20260908_143837_964 | 621 | 621/621/621 | PASS | PASS | PASS |
| approach_center_v0p20_r03_20260908_144130_128 | 627 | 627/627/627 | PASS | PASS | PASS |
| retreat_center_v0p10_r01_20260908_143155_511 | 647 | 647/647/647 | PASS | PASS | PASS |
| retreat_center_v0p10_r02_20260908_143637_382 | 616 | 616/616/616 | PASS | PASS | PASS |
| retreat_center_v0p10_r03_20260908_144058_154 | 625 | 625/625/625 | PASS | PASS | PASS |
| static_center_ttc_r01_20260908_142731_596 | 622 | 622/622/622 | PASS | PASS | PASS |
| static_center_ttc_r02_20260908_143504_968 | 620 | 620/620/620 | PASS | PASS | PASS |
| static_center_ttc_r03_20260908_143951_028 | 624 | 624/624/624 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p10_r01 | 605 | 29.129 | 100.00% | 100.00% | 100.00% | 100.00% | 33.87 ms |
| approach_center_v0p10_r02 | 605 | 29.114 | 100.00% | 100.00% | 100.00% | 100.00% | 36.58 ms |
| approach_center_v0p10_r03 | 622 | 29.913 | 100.00% | 73.79% | 96.46% | 100.00% | 32.83 ms |
| approach_center_v0p20_r01 | 390 | 29.813 | 100.00% | 99.74% | 100.00% | 100.00% | 34.61 ms |
| approach_center_v0p20_r02 | 621 | 29.785 | 95.01% | 41.86% | 63.12% | 100.00% | 34.57 ms |
| approach_center_v0p20_r03 | 627 | 29.413 | 100.00% | 42.11% | 53.59% | 100.00% | 34.82 ms |
| retreat_center_v0p10_r01 | 647 | 29.773 | 100.00% | 100.00% | 100.00% | 100.00% | 32.68 ms |
| retreat_center_v0p10_r02 | 616 | 29.348 | 100.00% | 100.00% | 100.00% | 100.00% | 35.60 ms |
| retreat_center_v0p10_r03 | 625 | 29.888 | 100.00% | 86.72% | 100.00% | 100.00% | 34.06 ms |
| static_center_ttc_r01 | 622 | 29.479 | 100.00% | 100.00% | 100.00% | 100.00% | 32.17 ms |
| static_center_ttc_r02 | 620 | 29.808 | 100.00% | 100.00% | 100.00% | 100.00% | 34.82 ms |
| static_center_ttc_r03 | 624 | 30.006 | 100.00% | 100.00% | 100.00% | 100.00% | 32.31 ms |

## 左右診断

- 左: `static_center_ttc_r03`
- 右: `static_center_ttc_r01`
- 正規化面積の左/右比: 1.077
- z²の左/右比: 1.598
- 生面積の左/右比: 0.662

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p10_r01_20260908_143110_750 | 100.00% | 0.1010 | 0/0 | 0/0 | FAIL |
| approach_center_v0p10_r02_20260908_143603_134 | 100.00% | 0.1109 | 0/0 | 0/0 | FAIL |
| approach_center_v0p10_r03_20260908_144024_286 | 25.54% | 0.1410 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r01_20260908_143413_255 | 38.82% | 0.1773 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_20260908_143837_964 | 94.27% | 0.5442 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_20260908_144130_128 | 98.41% | 0.1787 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r01_20260908_143155_511 | 99.74% | 0.1033 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r02_20260908_143637_382 | 100.00% | 0.1223 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r03_20260908_144058_154 | 99.20% | 0.1540 | 0/0 | 0/0 | FAIL |
| static_center_ttc_r01_20260908_142731_596 | 99.84% | 0.0461 | 0/0 | 0/0 | PASS |
| static_center_ttc_r02_20260908_143504_968 | 99.84% | 0.0564 | 0/0 | 0/0 | PASS |
| static_center_ttc_r03_20260908_143951_028 | 99.84% | 0.0786 | 0/0 | 0/0 | PASS |

動的TTC対象sessionのゲート再生は診断値として保存するが、静的位置外れ値判定を総合判定へは加えない。

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- static_no_false_ttc: **PASS**
- v0p10_approach_response: **PASS**
- v0p10_retreat_no_false_ttc: **PASS**
- v0p20_approach_warning: **FAIL**: approach_center_v0p20_r02: detection_rate=0.950081 < min_detection_rate=0.980000

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile_v5_candidate.json`

| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | 方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| approach_center_v0p10_r01_20260908_143110_750 | 198 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0002 m/s | 100.00% | 0/0 | PASS |
| approach_center_v0p10_r02_20260908_143603_134 | 194 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0005 m/s | 100.00% | 0/0 | PASS |
| approach_center_v0p10_r03_20260908_144024_286 | 180 | 96.46%/100.00% | 100.00%/100.00% | 0.000 s | 0.0010 m/s | 100.00% | 0/0 | PASS |
| approach_center_v0p20_r01_20260908_143413_255 | 94 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 13/0 | FAIL |
| approach_center_v0p20_r02_20260908_143837_964 | 92 | 63.12%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 17/13 | FAIL |
| approach_center_v0p20_r03_20260908_144130_128 | 108 | 53.59%/100.00% | 100.00%/100.00% | 0.000 s | 0.0037 m/s | 100.00% | 11/4 | FAIL |
| retreat_center_v0p10_r01_20260908_143155_511 | 194 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0151 m/s | ― | 0/0 | PASS |
| retreat_center_v0p10_r02_20260908_143637_382 | 172 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0159 m/s | ― | 0/0 | PASS |
| retreat_center_v0p10_r03_20260908_144058_154 | 206 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0151 m/s | ― | 0/0 | PASS |

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
