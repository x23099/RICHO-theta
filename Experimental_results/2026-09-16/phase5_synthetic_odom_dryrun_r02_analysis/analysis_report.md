# 録画一括解析レポート

## 結論

自動判定: **DIAGNOSTIC**

- no predefined requirement CSV was supplied; component metrics only

`DIAGNOSTIC`は解析失敗ではない。条件別の事前要件CSVがないため、
この録画だけから正式な実験PASSを宣言していないことを表す。

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/202609161835.tar.xz` |
| SHA-256 | `da9f790bc896a363c0a3fd07cf0600e74a525ee45a4d1aeb693005b5d75f2c75` |
| サイズ | 41,950,180 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v7_ffb_triple_20260916.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_camera_synthetic_odom_dryrun_r02_20260916_183117_154 | 402 | 402/402/402 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_camera_synthetic_odom_dryrun_r02 | 402 | 29.997 | 100.00% | 100.00% | 100.00% | 69.65% | 29.80 ms |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_camera_synthetic_odom_dryrun_r02_20260916_183117_154 | 99.75% | 0.0005 | 0/0 | 0/0 | PASS |

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
