# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- one or more fixed dynamic TTC conditions failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/202609031410.tar.xz` |
| SHA-256 | `ce7810a5947e22e376f169fc4c9085304c74f6e0a1e9fdb6d49bc283ed0ad7c7` |
| サイズ | 613,296,808 bytes |
| セッション | 12 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_candidate_20260902.json` |
| ゲート評価しきい値 | 2000 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p10_r01_20260903_140231_828 | 875 | 875/875/875 | PASS | PASS | PASS |
| approach_center_v0p10_r02_20260903_140318_833 | 621 | 621/621/621 | PASS | PASS | PASS |
| approach_center_v0p10_r03_20260903_140401_526 | 492 | 492/492/492 | PASS | PASS | PASS |
| approach_center_v0p20_r01_20260903_140715_416 | 377 | 377/377/377 | PASS | PASS | PASS |
| approach_center_v0p20_r02_20260903_140754_182 | 390 | 390/390/390 | PASS | PASS | PASS |
| approach_center_v0p20_r03_20260903_140831_916 | 365 | 365/365/365 | PASS | PASS | PASS |
| retreat_center_v0p10_r01_20260903_140445_028 | 447 | 447/447/447 | PASS | PASS | PASS |
| retreat_center_v0p10_r02_20260903_140557_257 | 404 | 404/404/404 | PASS | PASS | PASS |
| retreat_center_v0p10_r03_20260903_140638_925 | 395 | 395/395/395 | PASS | PASS | PASS |
| static_center_ttc_r01_20260903_140015_935 | 697 | 697/697/697 | PASS | PASS | PASS |
| static_center_ttc_r02_20260903_140049_936 | 674 | 674/674/674 | PASS | PASS | PASS |
| static_center_ttc_r03_20260903_140125_270 | 621 | 621/621/621 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p10_r01 | 875 | 29.995 | 100.00% | 100.00% | 100.00% | 100.00% | 28.24 ms |
| approach_center_v0p10_r02 | 621 | 30.004 | 100.00% | 100.00% | 100.00% | 100.00% | 28.93 ms |
| approach_center_v0p10_r03 | 492 | 29.971 | 100.00% | 100.00% | 100.00% | 100.00% | 28.09 ms |
| approach_center_v0p20_r01 | 377 | 29.993 | 100.00% | 100.00% | 100.00% | 100.00% | 26.99 ms |
| approach_center_v0p20_r02 | 390 | 30.017 | 100.00% | 100.00% | 100.00% | 100.00% | 27.98 ms |
| approach_center_v0p20_r03 | 365 | 29.995 | 100.00% | 100.00% | 100.00% | 100.00% | 29.45 ms |
| retreat_center_v0p10_r01 | 447 | 30.001 | 100.00% | 100.00% | 100.00% | 100.00% | 33.45 ms |
| retreat_center_v0p10_r02 | 404 | 29.993 | 100.00% | 100.00% | 100.00% | 100.00% | 31.72 ms |
| retreat_center_v0p10_r03 | 395 | 30.009 | 100.00% | 100.00% | 100.00% | 100.00% | 29.50 ms |
| static_center_ttc_r01 | 697 | 30.010 | 100.00% | 100.00% | 100.00% | 100.00% | 29.64 ms |
| static_center_ttc_r02 | 674 | 30.002 | 100.00% | 100.00% | 100.00% | 100.00% | 29.32 ms |
| static_center_ttc_r03 | 621 | 30.005 | 100.00% | 100.00% | 100.00% | 100.00% | 28.59 ms |

## 左右診断

- 左: `static_center_ttc_r01`
- 右: `approach_center_v0p10_r03`
- 正規化面積の左/右比: 1.066
- z²の左/右比: 1.534
- 生面積の左/右比: 0.696

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p10_r01_20260903_140231_828 | 100.00% | 0.0851 | 0/0 | 0/0 | FAIL |
| approach_center_v0p10_r02_20260903_140318_833 | 100.00% | 0.0902 | 0/0 | 0/0 | FAIL |
| approach_center_v0p10_r03_20260903_140401_526 | 100.00% | 0.0840 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r01_20260903_140715_416 | 100.00% | 0.1503 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_20260903_140754_182 | 100.00% | 0.1544 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_20260903_140831_916 | 100.00% | 0.1477 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r01_20260903_140445_028 | 100.00% | 0.0864 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r02_20260903_140557_257 | 100.00% | 0.0888 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r03_20260903_140638_925 | 100.00% | 0.0879 | 0/0 | 0/0 | FAIL |
| static_center_ttc_r01_20260903_140015_935 | 99.86% | 0.0073 | 0/0 | 0/0 | PASS |
| static_center_ttc_r02_20260903_140049_936 | 99.85% | 0.0112 | 0/0 | 0/0 | PASS |
| static_center_ttc_r03_20260903_140125_270 | 99.84% | 0.0093 | 0/0 | 0/0 | PASS |

動的TTC対象sessionのゲート再生は診断値として保存するが、静的位置外れ値判定を総合判定へは加えない。

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- static_no_false_ttc: **PASS**
- v0p10_approach_response: **PASS**
- v0p10_retreat_no_false_ttc: **PASS**
- v0p20_approach_warning: **PASS**

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile_v3_candidate.json`

| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | 方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| approach_center_v0p10_r01_20260903_140231_828 | 218 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0143 m/s | 100.00% | 0/0 | PASS |
| approach_center_v0p10_r02_20260903_140318_833 | 220 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0144 m/s | 100.00% | 0/0 | PASS |
| approach_center_v0p10_r03_20260903_140401_526 | 216 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0147 m/s | 100.00% | 0/0 | PASS |
| approach_center_v0p20_r01_20260903_140715_416 | 108 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0385 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r02_20260903_140754_182 | 110 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0384 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r03_20260903_140831_916 | 110 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0341 m/s | 100.00% | 0/0 | FAIL |
| retreat_center_v0p10_r01_20260903_140445_028 | 204 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0118 m/s | ― | 0/0 | PASS |
| retreat_center_v0p10_r02_20260903_140557_257 | 204 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0131 m/s | ― | 0/0 | PASS |
| retreat_center_v0p10_r03_20260903_140638_925 | 204 | 100.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0125 m/s | ― | 0/0 | PASS |

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
