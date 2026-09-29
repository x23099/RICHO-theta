# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- raw_ground_distance observation gate failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/rokuga_phase5_v11_reliability_dryrun_r01_20260929_153520_912.tar.xz` |
| SHA-256 | `240ac6566fb4fdd1172ce7ab8c2f020129cc2d50c869b1f48b04e970004ec668` |
| サイズ | 285,896,664 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v11_ffb_reliability_20260925.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_v11_reliability_dryrun_r01_20260929_153520_912 | 2412 | 2412/2412/2412 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_v11_reliability_dryrun_r01 | 2412 | 29.765 | 92.50% | 98.39% | 92.16% | 62.94% | 30.37 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_v11_reliability_dryrun_r01 | 1511 | ― | ― / ― s | 100.00% | 0 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_v11_reliability_dryrun_r01_20260929_153520_912 | 99.50% | 0.5100 | 0/0 | 0/0 | FAIL |

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- 要件CSV未指定。正式な条件別採否は未評価。

## 固定動的TTC条件

- 動的TTCプロファイル未指定。

## 成果物

- `archive_inventory.csv`
- `session_integrity.csv`
- `live_summary.csv`
- `processing_timing.csv`
- `lateral_summary.csv`
- `observation_replay.csv`
- `gate_regression.csv`
