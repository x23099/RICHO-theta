# 横長輪郭除外・処理時間計測の開発実装

## 実装状態

2026-08-26の独立holdout診断を開発データとして、次の2項目を実装した。

1. 生魚眼の青候補へ、設定可能な最大縦横比`幅/高さ`を追加した。
2. ライブ録画CSVへ、同一フレームの処理区間時間9列を追加した。

本番設定`src/bird_eye_config.json`には縦横比条件を追加していない。開発用
`src/bird_eye_config_raw_ground_distance.json`だけが
`blue_ground_contact_max_aspect_ratio=1.5`を使用する。

## 1. 横長輪郭除外

`detect_blue_ground_contact`は、面積条件を満たした輪郭についてbounding boxの
`width / height`を計算し、設定値を超える輪郭を最大候補の選択前に除外する。設定キーがない場合は
従来どおり縦横比を制限しないため、本番設定と既存利用者の動作は変わらない。

### 今回の6試行による全フレーム再処理

| 条件 | 検出フレーム | 検出率 |
|---|---:|---:|
| 箱なし | 0/818 | 0.00% |
| 左 `x=-0.3, z=0.9 m` | 639/639 | 100.00% |
| 右 `x=+0.3, z=0.9 m` | 729/729 | 100.00% |
| 左 `x=-0.3, z=1.2 m` | 652/652 | 100.00% |
| 右 `x=+0.3, z=1.2 m` | 659/659 | 100.00% |
| 中央 `z=1.2 m`遮蔽・visible | 698/698 | 100.00% |

前日別位置の箱なし録画も0/853となり、2環境でゴムマット誤検出を全除外した。

遮蔽試行では、完全遮蔽中の検出が125/182から8/182へ減り、横長の残留断片を除外できた。
`reappearing`の検出は53/59から36/59へ減ったが、除外された17件は安定した箱位置から0.15 mを
超える誤候補である。`raw_ground_distance + 2000 + NIS 9.21 + confirm 2`を再生すると、

- 静止4試行と遮蔽1試行の5/5がPASS。
- visible安定観測697/698採用、99.86%。
- 外れ値6/6棄却、100%。
- 最大`abs(vz)=0.1304 m/s`。
- 3/3イベントで追跡失効、3/3で再捕捉。
- 最大再捕捉遅延18フレーム。

となり、元の斜距離ゲート性能を維持した。

この再処理は閾値を得た録画を含むため、実装の開発回帰であって新しいholdout判定ではない。

## 2. 処理時間テレメトリ

新しい`detections.csv`には次の列を末尾へ追加した。単位はすべてmsで、時計は
`time.perf_counter`である。

| CSV列 | 測定範囲 |
|---|---|
| `processing_odom_poll_ms` | ODOM bridgeのpoll |
| `processing_capture_read_ms` | `VideoCapture.read` |
| `processing_bev_preprocess_ms` | 投影map更新、BEV remap、白線処理 |
| `processing_blue_pipeline_ms` | 青候補抽出、接地点、ゲート、追跡、TTC・領域更新 |
| `processing_ai_perception_ms` | 2画面のAI推論・3D box処理 |
| `processing_overlay_render_ms` | BEV、青箱、車体等のoverlay描画 |
| `processing_display_ms` | 2つのQt表示用画像変換・設定 |
| `processing_video_write_ms` | raw/BEV/detectionの3動画書込み |
| `processing_total_before_csv_ms` | callback開始から3動画書込み完了まで |

同一フレームの表示時間もCSVへ入れるため、処理順を「overlay → Qt表示 → 動画・CSV保存」へ変更した。
表示用画像と保存画像の内容は同じであり、録画フレーム数の扱いは変わらない。合計値は
`detections.csv`自体のシリアライズと録画状態ラベル更新を含まない。この測定終端はmetadataへ記録する。

`src/diagnose_recording_timing.py`も新列に対応し、各区間の中央値と、合計処理時間が
`1000 / requested_fps`を超えた割合を出力する。新列のない過去録画では区間値を空欄として扱い、
従来の実効FPS・フレーム間隔診断を継続できる。

## 3. 次回の実機確認

学校PCで更新後、preflightの`Experiment config`に`max_aspect=1.5`が表示されることを確認する。
その後、同じ起動条件で次を各10秒録画する。

1. 同じ黒ゴムマットで箱なし。
2. 青箱中央`z=1.2 m`。
3. 青箱中央`z=1.2 m`、遮蔽2回。

録画後は次を実行する。

```bash
python3 src/diagnose_recording_timing.py \
  --input recordings/2026-08-26_aspect_timing \
  --output Experimental_results/2026-08-26_live_processing_timing.csv
```

最初に`processing_total_before_csv_ms`の30 fps予算33.33 ms超過率を確認し、次に区間中央値を比較する。
特に`enable_ai=1`なので、`processing_ai_perception_ms`と`processing_video_write_ms`を別々に確認する。
実測値を得るまでは、非同期writerや保存動画削減へ進まず、主な超過区間を確定する。

## 成果物

- `Experimental_results/2026-08-26_aspect_filter_observation_replay.csv`
- `Experimental_results/2026-08-26_aspect_filter_gate_regression.csv`
- `src/frame_timing.py`
- `src/diagnose_recording_timing.py`
- `tests/test_frame_timing.py`
- `tests/test_recording_timing_integration.py`
