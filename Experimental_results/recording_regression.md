# 過去録画の回帰試験

## 目的

コードやconfigを変更したときに、Gitで管理していない過去録画を再解析し、
已知の正常結果が維持されるかを検査する。録画本体はGoogle Driveまたはローカルへ置き、
Gitには次の小さい定義ファイルだけを保存する。

- `recording_archive_manifest.csv`: ファイル名、サイズ、SHA-256。
- `recording_regression_suite.csv`: 使用config、ラベル、事前要件、期待判定。
- `*_regression_requirements.csv`: 条件別の検出率、追跡率、警告率などの許容値。

## 登録済み静的回帰

| dataset ID | 録画 | 条件 | 期待 |
|---|---|---|---|
| `aspect-timing-20260826-1630` | `202608261630.tar.xz` | 箱なし2床、中央、遮蔽2回 | PASS、4 session、gate 2/2、遮蔽失効・再捕捉2/2 |
| `lateral-static-20260826-1700` | `202608261700.tar.xz` | 左右静止 | PASS、2 session、gate 2/2、遮蔽0回 |
| `p0c-v0p10-20260818` | `recoding_08181725.tar.xz` | 0.10 m/s接近・後退 | 動的TTC 6/6 PASS、既知の収録品質によりアーカイブ総合FAIL |
| `p0c-v0p20-20260818` | `recoding_08181740.tar.xz` | 0.20 m/s接近・警告保持 | 動的TTC 3/3 PASS、既知の収録品質によりアーカイブ総合FAIL |

動的P0-Cは`dynamic_ttc_evaluation_profile.json`で精度区間と警告安全区間を分け、
動的条件のPASS数を独立して照合する。8月18日の録画は、要求30 fpsに対する実効25 fps、
旧CSVの`time_sec`/`monotonic_time_sec`差、静的外れ値ゲートの動的録画への非適用が残る。
そのためアーカイブ総合判定は既知の`FAIL`とし、動的TTC 9/9 PASSと分離して登録する。

## 実行

登録内容だけ確認する場合は、録画がローカルになくても実行できる。

```bash
python3 src/run_recording_regression.py --list
```

録画をダウンロードしたディレクトリを指定し、全登録データセットを検査する。

```bash
python3 src/run_recording_regression.py \
  --archive-dir /home/robo25/Downloads/recoding \
  --output-dir Experimental_results/regression_runs/2026-08-28
```

1件だけの確認は`--dataset-id`で選択する。

```bash
python3 src/run_recording_regression.py \
  --archive-dir /home/robo25/Downloads/recoding \
  --output-dir Experimental_results/regression_runs/2026-08-28-lateral \
  --dataset-id lateral-static-20260826-1700
```

実行時は、解析前にファイルサイズとSHA-256を台帳と照合する。不一致なら、
取り違えまたは破損として展開・解析しない。一致後は`analyze_field_recording.py`を呼び、
セッション数、録画完全性、実効FPS、選択中ゲート、条件別事前要件を確認する。
さらに、生映像再処理後のゲート対象session数、PASS数、遮蔽イベントの失効・再捕捉数を
台帳と照合する。これにより、将来の検出コード変更で箱なし映像が新たに誤検出された場合も
回帰FAILとなる。

既存の実行結果を更新する場合だけ`--overwrite`を付ける。
録画不足を黙って成功としないため、未発見は既定でFAILとなる。`--allow-missing`は、
複数PCの保有録画を棚卸しする際にSKIPを許す用途に限る。SKIPが1件でもある
レポートの総合判定は`INCOMPLETE`となり、全件回帰PASSとは区別する。

## 出力

`--output-dir`直下に次を作成する。

- `regression_summary.csv`: データセットごとのSHA-256、期待/実際判定、session数、gate数、動的TTC PASS数、差分理由。
- `recording_regression_report.md`: 回帰試験全体の要約。
- `<dataset ID>/`: 録画ごとの一括解析CSVと`analysis_report.md`。

## データセット追加時の手順

1. `register_recording_archive.py`でファイル全体のSHA-256とtar.xz構造を確認する。
2. `recording_archive_manifest.csv`に不変のdataset IDと録画情報を登録する。
3. 開発中に結果を見てしきい値を合わせず、事前に条件別要件CSVを作る。
4. `recording_regression_suite.csv`にconfig、ラベル、要件CSV、期待session数を登録する。動的録画はTTCプロファイルと期待PASS数も登録する。
5. 既存と新規データセットをまとめて実行し、台帳登録時点の期待値と一致することを確認する。
