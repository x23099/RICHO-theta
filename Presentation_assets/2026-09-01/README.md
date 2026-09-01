# 2026-09-01 成果報告用図版

## 新規図版

- `dynamic_approach_camera_sequence.svg/png`: 9月1日の実カメラ映像による接近3時点。
- `dynamic_approach_detection_sequence.svg/png`: 同じ3時点の検出・距離・TTC画面。
- `static_pipeline_actual.svg/png`: 8月26日の実画像による入力・BEV・検出結果。
- `dynamic_approach_raw_and_detection.mp4`: 9月1日接近試験の実映像と検出画面の同期動画。
- `project_progress.svg/png`: FFBデモと文書上のFSD風環境地図の2つのスコープで現在地を示す。
- `ffb_integration_gap.svg/png`: 現在の青箱経路、既存YOLO経路、未実装の2つの接続を示す。
- `recent_results_0826_0901.svg/png`: 8月26日から9月1日までの実装・実験・診断の推移を示す。

## 数値の出典

- 静的検出、遮蔽、処理時間: `Daily_reports/2026-08-26_daily_report.md`
- 再解析・回帰試験・評価条件固定: `Daily_reports/2026-08-28_daily_report.md`
- 動的TTC v1/v2: `Daily_reports/2026-09-01_daily_report.md`

## 併用すると分かりやすい既存図版

- `../2026-08-28/system_flow.svg`: 360度映像からTTCまでの処理フロー。
- `../2026-08-28/experiment_setup.svg`: 青箱の配置と録画条件。
- `../2026-08-28/experiment_raw_left.jpg`, `experiment_bev_left.jpg`,
  `experiment_detection_left.jpg`: 同一試行の入力・俯瞰・検出結果。

公開資料では、`experiment_raw_left.jpg`に写る人物の使用許可またはぼかしを確認する。
SVGはGoogle SlidesやPowerPointへ直接挿入すると文字が鮮明に保たれる。
