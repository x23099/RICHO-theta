# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- effective FPS is outside ±1%

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/rokuga_phase5_v12_hardware_warning_r01_20260929_180756_604.tar.xz` |
| SHA-256 | `66e055c8140d30691011ab536f1b16e6913b1bd05f75831417e8398d0219ad9b` |
| サイズ | 138,438,756 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_v12_hardware_warning_r01_20260929_180756_604 | 1258 | 1258/1258/1258 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_v12_hardware_warning_r01 | 1258 | 28.670 | 100.00% | 100.00% | 100.00% | 86.49% | 39.14 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_v12_hardware_warning_r01 | 1125 | ― | ― / ― s | 100.00% | 0 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_v12_hardware_warning_r01_20260929_180756_604 | 99.92% | 0.0578 | 0/0 | 0/0 | PASS |

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
