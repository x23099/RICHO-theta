# 録画一括解析レポート

## 結論

自動判定: **DIAGNOSTIC**

- no predefined requirement CSV was supplied; component metrics only

`DIAGNOSTIC`は解析失敗ではない。条件別の事前要件CSVがないため、
この録画だけから正式な実験PASSを宣言していないことを表す。

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/202609171524.tar.xz` |
| SHA-256 | `52372786e82bdd3f7042fc6d26c3b8b39dae289be06f7f9d0101e0e24144e326` |
| サイズ | 77,540,796 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v7_ffb_triple_20260916.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_camera_mock_odom_dryrun_r02_20260917_145834_900 | 1035 | 1035/1035/1035 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_camera_mock_odom_dryrun_r02 | 1035 | 29.882 | 100.00% | 100.00% | 100.00% | 33.14% | 28.78 ms |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_camera_mock_odom_dryrun_r02_20260917_145834_900 | 99.90% | 0.0802 | 0/0 | 0/0 | PASS |

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
