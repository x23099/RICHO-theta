# 録画一括解析CLI

## 目的

`src/analyze_field_recording.py`は、1個の`.tar.xz`録画に対する標準解析を1コマンドで実行する。
アーカイブ確認、安全な一時展開、セッション完全性、ライブ指標、処理時間、左右差、
生映像からの観測再計算、ゲート再生、Markdownレポート作成をまとめて行う。

## 基本操作

リポジトリ直下で実行する。

通常はルート直下のラッパーを使う。出力先を省略すると、実行日とアーカイブ名から
`Experimental_results/YYYY-MM-DD/<archive-name>_analysis`を自動作成する。標準解析に加えて
`virtual_ffb_replay.csv`も生成する。カメラ、ROS、Kobuki、ハンドル機器にはアクセスしない。

```bash
./start_recording_analysis.sh \
  /home/robo25/Downloads/recoding/202609031610.tar.xz
```

固定条件を指定する場合は、出力先に続けて従来の解析オプションを渡す。

```bash
./start_recording_analysis.sh \
  /home/robo25/Downloads/recoding/202609031610.tar.xz \
  Experimental_results/2026-09-03/ttc_v5_check \
  --config src/bird_eye_config_ttc_conservative_candidate_20260903.json \
  --requirements Experimental_results/2026-09-03/2026-09-03_ttc_conservative_v0p20_retry_requirements.csv \
  --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile_v5_candidate.json
```

正式な判定条件は録画内容ごとに異なるため、ラッパー内へ固定しない。既存出力を更新する場合は、
内容を確認してから末尾へ`--overwrite`を付ける。使用するPythonを明示する場合は、
`PYTHON_BIN=/path/to/python ./start_recording_analysis.sh ...`とする。

Python CLIを直接呼びたい場合は次の形式も引き続き利用できる。

```bash
python3 src/analyze_field_recording.py \
  --input /home/robo25/Downloads/recoding/202608261700.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --output-dir Experimental_results/2026-08-26/2026-08-26_1700_auto
```

遮蔽録画は、セッション名と区間を記録したラベルCSVも指定する。

```bash
python3 src/analyze_field_recording.py \
  --input /home/robo25/Downloads/recoding/202608261630.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --labels Experimental_results/2026-08-26/2026-08-26_1630_occlusion_labels.csv \
  --output-dir Experimental_results/2026-08-26/2026-08-26_1630_auto
```

動的TTC録画は、固定した評価プロファイルと録画完全性要件を両方指定する。

```bash
python3 src/analyze_field_recording.py \
  --input /path/to/recoding_08181740.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --requirements Experimental_results/p0c_v0p20_recording_requirements.csv \
  --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile.json \
  --output-dir Experimental_results/YYYY-MM-DD/example_dynamic_auto
```

`dynamic_ttc_evaluation_profile.json`は確定済みschema v1である。
`dynamic_ttc_evaluation_profile_v2_candidate.json`は走行中追跡率、方向応答時間、
定常方向精度を分離する開発候補であり、独立holdout確認までは本番判定に使わない。
`dynamic_ttc_evaluation_profile_v3_candidate.json`は9月2日に固定したdeadband 0.03 m/s・
WARNING 4.6秒候補であり、同様に新規独立holdout確認までは本番判定に使わない。
動的プロファイルに含まれるsessionの静的位置外れ値ゲートは診断結果へ残すが、
総合判定には加えない。静的sessionが混在する場合、その静的ゲート判定は従来どおり必須である。

既存の解析結果を意図して更新する場合だけ`--overwrite`を付ける。指定しなければ、同名成果物の
上書きを拒否する。展開データは一時ディレクトリに置き、解析後に自動削除する。

## 正式なPASS/FAILを出す場合

条件名、必要試行数、検出率などを定義した事前要件CSVを指定する。

```bash
python3 src/analyze_field_recording.py \
  --input /path/to/recording.tar.xz \
  --config src/bird_eye_config_raw_ground_distance.json \
  --requirements Experimental_results/p0b_live_trial_completeness_requirements.csv \
  --output-dir Experimental_results/YYYY-MM-DD/example_auto
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
| `dynamic_ttc_results.csv` | 固定した精度区間、TTC発火、警告成立・保持の条件別採否。`--dynamic-ttc-profile`指定時のみ |
| `analysis_report.md` | 主要指標と総合判定の人間向けレポート |

## 確認済み録画

- `202608261700.tar.xz`: 左右静止条件、2セッション。
- `202608261630.tar.xz`: 青箱なし2件、通常1件、遮蔽1件。遮蔽2/2回の失効と再捕捉を確認。

利用可能な全引数は`python3 src/analyze_field_recording.py --help`で確認できる。
# Kalman速度応答・TTCデッドバンド感度評価

録画時に採用済みの観測を固定し、Kalman process acceleration stdとTTC deadbandの候補を
一括比較する。入力は複数回指定でき、tar.xzを展開せずに直接読む。

```bash
python3 src/analyze_ttc_kalman_sensitivity.py \
  --input /path/to/202609011435.tar.xz \
  --input /path/to/recoding_08181725.tar.xz \
  --input /path/to/recoding_08181740.tar.xz \
  --input /path/to/202608261630.tar.xz \
  --output-dir Experimental_results/2026-09-02
```

既定候補はprocess acceleration std `0.75,1.5,3.0,6.0 m/s²`と、TTC deadband
`0.03,0.05,0.07 m/s`の12通り。要約CSV、試行別CSV、Markdown reportを出力する。
既存結果を更新する場合だけ`--overwrite`を指定する。
