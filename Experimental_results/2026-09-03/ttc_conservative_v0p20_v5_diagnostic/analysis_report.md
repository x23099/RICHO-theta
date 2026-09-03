# 録画一括解析レポート

## 結論

自動判定: **PASS**


## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/202609031610.tar.xz` |
| SHA-256 | `8d1b8e0bc59f4a07f47ccab715ac3c38aea573acd1a59b707664ce40c54310cf` |
| サイズ | 110,733,032 bytes |
| セッション | 3 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_conservative_candidate_20260903.json` |
| ゲート評価しきい値 | 2000 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p20_r01_20260903_160831_889 | 431 | 431/431/431 | PASS | PASS | PASS |
| approach_center_v0p20_r02_20260903_161123_582 | 317 | 317/317/317 | PASS | PASS | PASS |
| approach_center_v0p20_r03_20260903_161200_952 | 337 | 337/337/337 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p20_r01 | 431 | 30.007 | 100.00% | 67.05% | 68.91% | 100.00% | 24.33 ms |
| approach_center_v0p20_r02 | 317 | 30.008 | 100.00% | 64.98% | 68.45% | 100.00% | 31.98 ms |
| approach_center_v0p20_r03 | 337 | 30.023 | 100.00% | 63.20% | 66.47% | 100.00% | 29.20 ms |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_20260903_160831_889 | 99.60% | 0.1303 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_20260903_161123_582 | 100.00% | 0.1353 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_20260903_161200_952 | 100.00% | 0.1328 | 0/0 | 0/0 | FAIL |

動的TTC対象sessionのゲート再生は診断値として保存するが、静的位置外れ値判定を総合判定へは加えない。

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- v0p20_approach_warning: **PASS**

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile_v5_candidate.json`

| ラベル | 精度区間 | 追跡(全体/走行) | 方向(全体/定常) | 方向応答 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| approach_center_v0p20_r01_20260903_160831_889 | 81 | 68.91%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 26/5 | PASS |
| approach_center_v0p20_r02_20260903_161123_582 | 80 | 68.45%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 22/6 | PASS |
| approach_center_v0p20_r03_20260903_161200_952 | 79 | 66.47%/100.00% | 100.00%/100.00% | 0.000 s | 0.0000 m/s | 100.00% | 26/7 | PASS |

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
