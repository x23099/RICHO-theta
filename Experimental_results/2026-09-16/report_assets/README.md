# 2026-09-16 成果報告用資料

## `raw_approach_center_v0p20_r02_v6holdout_20260908_163811_391_frame_000150.png`

- 内容: 録画済みWARNING開始時の360度カメラ生画像
- 元録画: `/home/robo25/Downloads/recoding/202609081640.tar.xz`
- session: `approach_center_v0p20_r02_v6holdout_20260908_163811_391`
- member: `approach_center_v0p20_r02_v6holdout_20260908_163811_391/raw.avi`
- frame: 150（1始まり）、動画内時刻4.967秒
- 解像度: 1280x720
- SHA-256: `71070b1fbd9beabd62db75a0290efbdb99bc62019e30162def701a5169111061`
- 編集: なし。9月10日に同じ元動画から取り出したPNGの同一バイト列を複製した

## `hardware_cadence_latency.png`

- 内容: continuous、double、triple実機試験のROS応答p95と最終CLEAR停止時間
- 元データ: `../hardware_cadence/hardware_cadence_summary.csv`
- 生成: `src/create_ffb_hardware_cadence_graph.py`
- 注意: G923の体感強度ではなく、ROS command/status間の計測値を示す

## `triple_recorded_risk_dry_run.png`

- 内容: 録画済みriskへtriple cadenceを適用したpublisher要求とdry-run adapter適用値
- 元データ: `../phase5_triple_dry_run/replay/replayed_commands.csv`および`adapter_status.csv`
- 生成関数: `src/create_ffb_report_assets.py::plot_replay`
- 注意: G923物理出力は行っていない
