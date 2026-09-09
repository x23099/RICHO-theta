# 2026-09-10 日報用資料

## `raw_approach_center_v0p20_r02_v6holdout_20260908_163811_391_frame_000150.png`

- 内容: TTC WARNING開始時点付近の360度カメラ生画像
- 元録画: `/home/robo25/Downloads/recoding/202609081640.tar.xz`
- archive SHA-256: `7a38ec860b9bf5af3ef380332582ed154c4ca5dad4b12c44b4f38485e20facf7`
- member: `approach_center_v0p20_r02_v6holdout_20260908_163811_391/raw.avi`
- frame: 150（1始まり）
- 動画内時刻: 4.967秒
- 解像度: 1280x720
- 編集: なし。注釈、crop、resize、回転、色・明るさ補正を行っていない

## `ffb_cadence_dry_run.png`

- 内容: continuous、double、tripleの実送信command比較
- 元データ: `/home/robo25/theta_ws/RICHO-theta/Experimental_results/2026-09-10/ffb_cadence_dry_run_final`以下の`command_log.csv`
- 生成: `src/create_ffb_report_assets.py --cadence-root ...`

## `recorded_risk_ffb_dry_run.png`

- 内容: 録画済み衝突リスクの要求強度とdry-run adapter適用値
- 元データ: `/home/robo25/theta_ws/RICHO-theta/Experimental_results/2026-09-10/phase5_recorded_risk_dry_run/replay/replayed_commands.csv`
  および`/home/robo25/theta_ws/RICHO-theta/Experimental_results/2026-09-10/phase5_recorded_risk_dry_run/replay/adapter_status.csv`
- 生成: `src/create_ffb_report_assets.py --replay-root ...`
