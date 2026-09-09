# 2026-09-10 リモートFFB接続準備 結果

## 結論

実機へアクセスしない`dry_run`だけで、合成警告の送信、adapter応答の自動記録、
通知cadence比較、録画済み衝突riskのROS 2再生までを実施した。全試験の自動判定はPASSだった。
G923の知覚評価と走行状態での統合確認は含まない。

## 実施結果

### 合成警告cadence比較

| cadence | active command | coverage | 応答p95 [ms] | CLEAR停止 [ms] | fault | 判定 |
|---|---:|---:|---:|---:|---:|---|
| continuous | 15 | 1.000 | 1.700 | 0.917 | 0 | PASS |
| double | 8 | 1.000 | 1.224 | 0.796 | 0 | PASS |
| triple | 9 | 1.000 | 2.477 | 1.129 | 0 | PASS |

3条件ともROS 2通信、0.05上限制限、CLEAR停止は正常だった。この結果だけではG923上の
体感差は選べないため、次回は0.05を維持して停止状態で3条件を比較する。

- 集計: `ffb_cadence_dry_run_final/cadence_report.md`
- 数値: `ffb_cadence_dry_run_final/cadence_summary.csv`
- 条件別の送受信: 各cadence配下の`command_log.csv`、`status_log.csv`

### 録画済み衝突riskの接続準備

- 入力: `202609081640.tar.xz`
- session: `approach_center_v0p20_r02_v6holdout_20260908_163811_391`
- source row: 629
- command/status: 630/630（終了CLEARを含む）
- active command/status: 69/69
- 最大adapter適用強度: 0.05
- fault: 0
- 最終状態: inactive
- 自動判定: PASS

既存の`CollisionFfbPublisherBridge`を使用し、録画中の`collision_risk_level`から
`/collision/ffb_command`、dry-run adapter、`/collision/ffb_status`までを確認した。
映像認識の再計算とG923物理出力は行っていない。

- 報告: `phase5_recorded_risk_dry_run/replay/replay_report.md`
- command: `phase5_recorded_risk_dry_run/replay/replayed_commands.csv`
- status: `phase5_recorded_risk_dry_run/replay/adapter_status.csv`

## 実行手順

FFB側の合成cadence比較:

```bash
./start_collision_ffb_dry_run_suite.sh OUTPUT_DIR
```

RICHO-theta側の録画risk再生:

```bash
./start_phase5_ffb_replay_dry_run.sh \
  /path/to/recording.tar.xz \
  SESSION_NAME \
  Experimental_results/YYYY-MM-DD/phase5_recorded_risk_dry_run
```

どちらもadapterを`output_mode=dry_run`で固定して起動する。G923は開かない。

## 成果報告用画像

`report_assets/`へ次を保存した。

- `raw_approach_center_v0p20_r02_v6holdout_20260908_163811_391_frame_000150.png`:
  WARNING開始時付近の1280x720生画像。注釈、crop、resize、色補正なし。
- `ffb_cadence_dry_run.png`: 3種類の送信cadence比較。
- `recorded_risk_ffb_dry_run.png`: 録画risk由来の要求強度とadapter適用強度。

出典、元解像度、動画内時刻、SHA-256、変換履歴は
`report_assets/assets_manifest.json`に記録した。

## 次回の実機作業

1. Kobukiを停止し、他のFFB writerがいないことを確認する。
2. G923を固定し、0.05のcontinuous、double、tripleを各1回だけ体感比較する。
3. CLEAR、watchdog、Ctrl+Cで確実に停止することを各条件で確認する。
4. cadenceを決めた後、停止状態で録画risk再生をhardwareへ接続する。
5. 走行を伴う試験は、停止状態の接続確認が完了してから別段階で行う。

## 検証

- RICHO-theta: 166 tests passed
- FFB対象テスト: 82 tests passed
- FFB 2 package clean build: PASS
- 新規Python: flake8、pydocstyle PASS
- shell: `bash -n` PASS
- 差分: `git diff --check` PASS
