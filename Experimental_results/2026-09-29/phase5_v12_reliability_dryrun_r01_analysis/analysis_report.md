# 録画一括解析レポート

## 結論

自動判定: **DIAGNOSTIC**

- no predefined requirement CSV was supplied; component metrics only

`DIAGNOSTIC`は解析失敗ではない。条件別の事前要件CSVがないため、
この録画だけから正式な実験PASSを宣言していないことを表す。

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/rokuga_phase5_v12_reliability_dryrun_r01_20260929_162234_202.tar.xz` |
| SHA-256 | `91ebc108cf5834c7932fdd62dc6759578bddfc9644db5fe87f6044942eca7a9f` |
| サイズ | 119,067,696 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_v12_reliability_dryrun_r01_20260929_162234_202 | 1045 | 1045/1045/1045 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_v12_reliability_dryrun_r01 | 1045 | 29.950 | 86.51% | 96.02% | 85.07% | 87.46% | 29.93 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_v12_reliability_dryrun_r01 | 902 | ― | ― / ― s | 100.00% | 0 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_v12_reliability_dryrun_r01_20260929_162234_202 | 98.30% | 0.0363 | 0/0 | 0/0 | PASS |

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
