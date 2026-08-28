# 録画一括解析CLI

## 目的

`src/analyze_field_recording.py`は、1個の`.tar.xz`録画に対する標準解析を1コマンドで実行する。
アーカイブ確認、安全な一時展開、セッション完全性、ライブ指標、処理時間、左右差、
生映像からの観測再計算、ゲート再生、Markdownレポート作成をまとめて行う。

## 基本操作

リポジトリ直下で実行する。

```bash
python3 src/analyze_field_recording.py \
  --input /home/robo25/Downloads/recoding/202608261700.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --output-dir Experimental_results/2026-08-26_1700_auto
```

遮蔽録画は、セッション名と区間を記録したラベルCSVも指定する。

```bash
python3 src/analyze_field_recording.py \
  --input /home/robo25/Downloads/recoding/202608261630.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --labels Experimental_results/2026-08-26_1630_occlusion_labels.csv \
  --output-dir Experimental_results/2026-08-26_1630_auto
```

既存の解析結果を意図して更新する場合だけ`--overwrite`を付ける。指定しなければ、同名成果物の
上書きを拒否する。展開データは一時ディレクトリに置き、解析後に自動削除する。

## 正式なPASS/FAILを出す場合

条件名、必要試行数、検出率などを定義した事前要件CSVを指定する。

```bash
python3 src/analyze_field_recording.py \
  --input /path/to/recording.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --requirements Experimental_results/p0b_live_trial_completeness_requirements.csv \
  --output-dir Experimental_results/example_auto
```

自動判定の意味は次のとおり。

| 判定 | 意味 |
|---|---|
| `PASS` | アーカイブ、完全性、実効FPS、config選択中のゲート、事前要件がすべてPASS |
| `FAIL` | 上記の自動確認項目のいずれかが失敗 |
| `DIAGNOSTIC` | 解析は成功したが、事前要件CSVがないため正式PASSは宣言しない |

`FAIL`のときは終了コード1、`PASS`と`DIAGNOSTIC`のときは0を返す。遮蔽ラベル未指定の
0/0イベントは、遮蔽性能PASSとは扱わない。

## 出力

| ファイル | 内容 |
|---|---|
| `archive_inventory.csv` | SHA-256、サイズ、セッション数、構成完全性 |
| `session_integrity.csv` | CSV連番、時刻単調性、3映像とCSVのframe数一致 |
| `live_summary.csv` | 検出、採用、追跡、ODOM、実効FPSの要約 |
| `processing_timing.csv` | 処理区間ごとの時間統計 |
| `lateral_summary.csv` | 左右差診断用の面積・距離統計 |
| `observation_replay.csv` | 生映像から再計算したframe単位観測 |
| `gate_regression.csv` | 正規化方式ごとのゲート再生結果 |
| `requirements_results.csv` | 事前要件の条件別採否。`--requirements`指定時のみ |
| `analysis_report.md` | 主要指標と総合判定の人間向けレポート |

## 確認済み録画

- `202608261700.tar.xz`: 左右静止条件、2セッション。
- `202608261630.tar.xz`: 青箱なし2件、通常1件、遮蔽1件。遮蔽2/2回の失効と再捕捉を確認。

利用可能な全引数は`python3 src/analyze_field_recording.py --help`で確認できる。
