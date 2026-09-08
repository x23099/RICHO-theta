# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- one or more fixed dynamic TTC conditions failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/202609081616.tar.xz` |
| SHA-256 | `a627753e7d546b5562e920253ce6f2c515854f9714627c1a3eebb23cbd8e6795` |
| サイズ | 176,945,252 bytes |
| セッション | 3 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v6_candidate_20260908.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p20_r01_v6holdout_20260908_161421_698 | 631 | 631/631/631 | PASS | PASS | PASS |
| approach_center_v0p20_r02_v6holdout_20260908_161505_491 | 624 | 624/624/624 | PASS | PASS | PASS |
| approach_center_v0p20_r03_v6holdout_20260908_161600_525 | 627 | 627/627/627 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p20_r01_v6holdout | 631 | 30.010 | 100.00% | 31.70% | 32.81% | 100.00% | 26.69 ms |
| approach_center_v0p20_r02_v6holdout | 624 | 29.995 | 100.00% | 33.97% | 35.10% | 100.00% | 28.65 ms |
| approach_center_v0p20_r03_v6holdout | 627 | 30.002 | 100.00% | 31.74% | 32.85% | 100.00% | 26.07 ms |

## 左右診断

- 左: `approach_center_v0p20_r01_v6holdout`
- 右: `approach_center_v0p20_r03_v6holdout`
- 正規化面積の左/右比: 0.955
- z²の左/右比: 1.071
- 生面積の左/右比: 0.744

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_v6holdout_20260908_161421_698 | 78.51% | 0.1180 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_v6holdout_20260908_161505_491 | 100.00% | 0.1145 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_v6holdout_20260908_161600_525 | 100.00% | 0.1343 | 0/0 | 0/0 | FAIL |

動的TTC対象sessionのゲート再生は診断値として保存するが、静的位置外れ値判定を総合判定へは加えない。

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- 要件CSV未指定。正式な条件別採否は未評価。

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile_v6_candidate.json`

| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | 方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_v6holdout_20260908_161421_698 | 66 | 32.81%/91.25% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r02_v6holdout_20260908_161505_491 | 62 | 35.10%/88.46% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r03_v6holdout_20260908_161600_525 | 45 | 32.85%/85.90% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 34/20 | FAIL |

## 成果物

- `archive_inventory.csv`
- `session_integrity.csv`
- `live_summary.csv`
- `processing_timing.csv`
- `lateral_summary.csv`
- `observation_replay.csv`
- `gate_regression.csv`
- `dynamic_ttc_results.csv`
