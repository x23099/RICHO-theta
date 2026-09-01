# 録画一括解析レポート

## 結論

自動判定: **FAIL**

- raw_ground_distance observation gate failed
- one or more predefined requirements failed
- one or more fixed dynamic TTC conditions failed

## 入力と来歴

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/202609011435.tar.xz` |
| SHA-256 | `b0ecb964f7f7178aa48e09ba6da70196b61b75d02944d80b9df4b34d0ecc5ce9` |
| サイズ | 521,780,244 bytes |
| セッション | 10 |
| config | `/home/robo25/theta_ws/RICHO-theta/src/bird_eye_config_raw_ground_distance.json` |
| ゲート評価しきい値 | 2000 |
| 遮蔽ラベル | なし |

## セッション完全性

| セッション | frame | raw/BEV/detection | 時刻 | 処理時間列 | 判定 |
|---|---:|---|---|---|---|
| approach_center_v0p10_r01_20260901_142324_230 | 615 | 615/615/615 | PASS | PASS | PASS |
| approach_center_v0p10_r02_20260901_142401_291 | 536 | 536/536/536 | PASS | PASS | PASS |
| approach_center_v0p10_r03_20260901_142434_429 | 517 | 517/517/517 | PASS | PASS | PASS |
| approach_center_v0p20_r01_20260901_143052_426 | 425 | 425/425/425 | PASS | PASS | PASS |
| approach_center_v0p20_r02_20260901_143130_004 | 416 | 416/416/416 | PASS | PASS | PASS |
| approach_center_v0p20_r03_20260901_143206_639 | 402 | 402/402/402 | PASS | PASS | PASS |
| approach_center_v0p20_r04_20260901_143249_502 | 358 | 358/358/358 | PASS | PASS | PASS |
| retreat_center_v0p10_r01_20260901_142527_026 | 574 | 574/574/574 | PASS | PASS | PASS |
| retreat_center_v0p10_r02_20260901_142605_934 | 687 | 687/687/687 | PASS | PASS | PASS |
| retreat_center_v0p10_r03_20260901_142643_149 | 641 | 641/641/641 | PASS | PASS | PASS |

## ライブ結果

| ラベル | frame | 実効FPS | 検出 | 採用 | 追跡 | ODOM | 有効処理p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| approach_center_v0p10_r01 | 615 | 30.008 | 100.00% | 97.24% | 98.54% | 100.00% | 32.63 ms |
| approach_center_v0p10_r02 | 536 | 29.997 | 100.00% | 95.15% | 100.00% | 100.00% | 31.12 ms |
| approach_center_v0p10_r03 | 517 | 29.994 | 100.00% | 78.72% | 83.17% | 100.00% | 30.37 ms |
| approach_center_v0p20_r01 | 425 | 30.017 | 100.00% | 59.76% | 61.41% | 100.00% | 31.05 ms |
| approach_center_v0p20_r02 | 416 | 30.019 | 100.00% | 57.21% | 59.86% | 100.00% | 31.37 ms |
| approach_center_v0p20_r03 | 402 | 29.985 | 100.00% | 56.47% | 57.96% | 100.00% | 31.26 ms |
| approach_center_v0p20_r04 | 358 | 29.991 | 100.00% | 63.97% | 67.88% | 100.00% | 31.54 ms |
| retreat_center_v0p10_r01 | 574 | 29.992 | 100.00% | 94.25% | 100.00% | 100.00% | 29.58 ms |
| retreat_center_v0p10_r02 | 687 | 30.007 | 100.00% | 96.94% | 100.00% | 100.00% | 31.41 ms |
| retreat_center_v0p10_r03 | 641 | 29.914 | 100.00% | 97.19% | 100.00% | 100.00% | 30.59 ms |

## 左右診断

- 左右ペアを自動選択できなかった。

## raw_ground_distanceゲート再生

| セッション | 安定採用率 | 最大abs(vz) | 遮蔽失効 | 再捕捉 | 判定 |
|---|---:|---:|---:|---:|---|
| approach_center_v0p10_r01_20260901_142324_230 | 100.00% | 0.3872 | 0/0 | 0/0 | FAIL |
| approach_center_v0p10_r02_20260901_142401_291 | 100.00% | 0.2144 | 0/0 | 0/0 | FAIL |
| approach_center_v0p10_r03_20260901_142434_429 | 100.00% | 0.6771 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r01_20260901_143052_426 | 100.00% | 0.1770 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r02_20260901_143130_004 | 100.00% | 0.1836 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r03_20260901_143206_639 | 100.00% | 0.1801 | 0/0 | 0/0 | FAIL |
| approach_center_v0p20_r04_20260901_143249_502 | 100.00% | 0.1883 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r01_20260901_142527_026 | 100.00% | 0.1456 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r02_20260901_142605_934 | 100.00% | 0.1241 | 0/0 | 0/0 | FAIL |
| retreat_center_v0p10_r03_20260901_142643_149 | 100.00% | 0.1343 | 0/0 | 0/0 | FAIL |

遮蔽ラベルがないため、失効・再捕捉0/0は遮蔽性能PASSを意味しない。

## 事前要件

- v0p10_approach_recording: **FAIL**: approach_center_v0p10_r03: track_rate=0.831721 < min_track_rate=0.950000
- v0p10_retreat_recording: **PASS**
- v0p20_approach_recording: **FAIL**: approach_center_v0p20_r01: track_rate=0.614118 < min_track_rate=0.950000; approach_center_v0p20_r02: track_rate=0.598558 < min_track_rate=0.950000; approach_center_v0p20_r04: track_rate=0.678771 < min_track_rate=0.950000

## 固定動的TTC条件

- profile: `/home/robo25/theta_ws/RICHO-theta/src/dynamic_ttc_evaluation_profile.json`

| ラベル | 精度区間 | 方向 | 速度MAE | TTC発火 | 警告/保持 | 判定 |
|---|---:|---:|---:|---:|---:|---|
| approach_center_v0p10_r01_20260901_142324_230 | 265 | 96.60% | 0.0138 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p10_r02_20260901_142401_291 | 279 | 93.55% | 0.0156 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p10_r03_20260901_142434_429 | 276 | 97.10% | 0.0176 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r01_20260901_143052_426 | 115 | 98.26% | 0.0268 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r02_20260901_143130_004 | 118 | 99.15% | 0.0245 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r03_20260901_143206_639 | 119 | 100.00% | 0.0236 m/s | 100.00% | 0/0 | FAIL |
| approach_center_v0p20_r04_20260901_143249_502 | 118 | 98.31% | 0.0284 m/s | 100.00% | 3/0 | FAIL |
| retreat_center_v0p10_r01_20260901_142527_026 | 274 | 89.42% | 0.0184 m/s | ― | 0/0 | FAIL |
| retreat_center_v0p10_r02_20260901_142605_934 | 299 | 94.65% | 0.0174 m/s | ― | 0/0 | FAIL |
| retreat_center_v0p10_r03_20260901_142643_149 | 265 | 94.34% | 0.0141 m/s | ― | 0/0 | FAIL |

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
