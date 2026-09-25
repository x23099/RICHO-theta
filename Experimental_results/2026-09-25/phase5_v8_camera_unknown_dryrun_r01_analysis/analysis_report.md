# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- effective FPS is outside ±1%
- raw_ground_distance observation gate failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310.tar.xz` |
| SHA-256 | `dfc8fee1182bcce184186fa883590b5a602129fa674bf352635b41424f62deed` |
| サイズ | 94,559,304 bytes |
| セッション | 1 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_ttc_v8_ffb_distinct_unknown_challenge_20260925.json` |
| ゲート評価しきい値 | 1450 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310 | 1264 | 1264/1264/1264 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase5_v8_camera_unknown_dryrun_r01 | 1264 | 29.325 | 78.80% | 82.23% | 77.37% | 48.81% | 26.09 ms |

## ROS/FFB callback診断

| ラベル | ODOM受信増分 | challenge受信増分 | challenge age p95/max | FFB送信成功 | challenge見送り |
|---|---:|---:|---:|---:|---:|
| phase5_v8_camera_unknown_dryrun_r01 | 585 | 2002 | 0.0334 / 0.2509 s | 98.10% | 24 |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310 | 85.88% | 0.4762 | 0/0 | 0/0 | FAIL |

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
