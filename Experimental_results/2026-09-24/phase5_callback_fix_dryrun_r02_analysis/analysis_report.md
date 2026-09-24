# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- effective FPS is outside ±1%

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/phase5_callback_fix_dryrun_r02_20260924_172351_631.tar.xz` |
| SHA-256 | `51e21cd207f07fb8624ee6d1e7131561d090b7113edf59f8e0183106e5899b1e` |
| サイズ | 67,152,124 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v7_ffb_triple_challenge_dryrun_20260917.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_callback_fix_dryrun_r02_20260924_172351_631 | 897 | 897/897/897 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_callback_fix_dryrun_r02 | 897 | 29.286 | 100.00% | 100.00% | 100.00% | 78.26% | 34.76 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_callback_fix_dryrun_r02 | 696 | 1529 | 0.0192 / 0.0299 s | 100.00% | 0 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_callback_fix_dryrun_r02_20260924_172351_631 | 99.11% | 0.1530 | 0/0 | 0/0 | PASS |

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
