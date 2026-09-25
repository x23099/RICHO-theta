# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- effective FPS is outside ±1%

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/phase5_v9_camera_unknown_dryrun_r01_20260925_164955_362.tar.xz` |
| SHA-256 | `d2611d77fd7fa9b9236cb188be4a52d4bbe7a33ae766c9f694e1b30492dc8838` |
| サイズ | 111,790,268 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v9_ffb_challenge_recovery_20260925.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_v9_camera_unknown_dryrun_r01_20260925_164955_362 | 1483 | 1483/1483/1483 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_v9_camera_unknown_dryrun_r01 | 1483 | 29.309 | 55.90% | 99.76% | 56.24% | 51.65% | 29.70 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_v9_camera_unknown_dryrun_r01 | 739 | 2387 | 0.0266 / 0.2058 s | 92.99% | 104 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_v9_camera_unknown_dryrun_r01_20260925_164955_362 | 99.76% | 0.0942 | 0/0 | 0/0 | PASS |

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
