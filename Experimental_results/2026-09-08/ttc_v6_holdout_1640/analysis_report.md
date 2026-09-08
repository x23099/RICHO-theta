# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- raw_ground_distance observation gate failed
- one or more fixed dynamic TTC conditions failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/202609081640.tar.xz` |
| SHA-256 | `7a38ec860b9bf5af3ef380332582ed154c4ca5dad4b12c44b4f38485e20facf7` |
| サイズ | 254,768,020 bytes |
| セッション | 4 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v6_candidate_20260908.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p20_r01_v6holdout_20260908_163553_528 | 625 | 625/625/625 | PASS | PASS | PASS |
| approach_center_v0p20_r02_v6holdout_20260908_163811_391 | 629 | 629/629/629 | PASS | PASS | PASS |
| approach_center_v0p20_r03_v6holdout_20260908_163856_015 | 626 | 626/626/626 | PASS | PASS | PASS |
| omake | 622 | 622/622/622 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p20_r01_v6holdout | 625 | 30.003 | 100.00% | 52.96% | 82.56% | 100.00% | 27.47 ms |
| approach_center_v0p20_r02_v6holdout | 629 | 29.996 | 36.41% | 94.76% | 38.00% | 100.00% | 31.62 ms |
| approach_center_v0p20_r03_v6holdout | 626 | 30.005 | 49.52% | 97.74% | 51.44% | 100.00% | 31.04 ms |
| approach_center_v0p20_r01_v6holdout | 622 | 29.989 | 100.00% | 99.68% | 100.00% | 100.00% | 27.71 ms |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_v6holdout_20260908_163553_528 | 0.00% | 0.1820 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_v6holdout_20260908_163811_391 | 98.61% | 0.2100 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_v6holdout_20260908_163856_015 | 99.55% | 0.1677 | 0/0 | 0/0 | FAIL |
| omake | 97.61% | 0.6909 | 0/0 | 0/0 | FAIL |

動的TTC対象sessionのゲート再生は診断値として保存するが、静的位置外れ値判定を総合判定へは加えない。

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- 要件CSV未指定。正式な条件別採否は未評価。

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile_v6_candidate.json`

| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | 方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_v6holdout_20260908_163553_528 | 83 | 82.56%/100.00% | 100.00%/100.00% | 0.000 s | 0.0068 m/s | 100.00% | 28/6 | PASS |
| approach_center_v0p20_r02_v6holdout_20260908_163811_391 | 30 | 38.00%/100.00% | 100.00%/100.00% | 0.000 s | 0.0009 m/s | 100.00% | 65/7 | FAIL |
| approach_center_v0p20_r03_v6holdout_20260908_163856_015 | 85 | 51.44%/100.00% | 100.00%/100.00% | 0.000 s | 0.0026 m/s | 100.00% | 19/0 | PASS |

## 成果物

- `archive_inventory.csv`
- `session_integrity.csv`
- `live_summary.csv`
- `processing_timing.csv`
- `lateral_summary.csv`
- `observation_replay.csv`
- `gate_regression.csv`
- `dynamic_ttc_results.csv`
