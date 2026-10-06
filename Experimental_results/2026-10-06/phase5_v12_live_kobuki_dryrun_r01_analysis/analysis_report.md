# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- raw_ground_distance observation gate failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/phase5_v12_live_kobuki_dryrun_r01_20261006_135700_661.tar.xz` |
| SHA-256 | `37d62dc8ea047b9a3bc352b7aa47505b9f39f1620020e898a2fe1141341449a7` |
| サイズ | 66,017,296 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_v12_live_kobuki_dryrun_r01_20261006_135700_661 | 572 | 572/572/572 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_v12_live_kobuki_dryrun_r01 | 572 | 29.891 | 100.00% | 53.50% | 53.50% | 100.00% | 30.90 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_v12_live_kobuki_dryrun_r01 | 960 | ― | ― / ― s | 100.00% | 0 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_v12_live_kobuki_dryrun_r01_20261006_135700_661 | 100.00% | 0.2412 | 0/0 | 0/0 | FAIL |

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
