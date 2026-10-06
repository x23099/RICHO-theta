# 2026-10-06 成果報告用画像

カメラの`raw.avi`から元解像度1280×720のフレームをPNGとして保存した。注釈、合成、切り抜き、リサイズ、色・明るさ補正は行っていない。

| ファイル | 録画 | frame | 録画経過 | 内容 |
|---|---|---:|---:|---|
| `phase5_v12_live_warning_raw_frame_0309.png` | `phase5_v12_live_kobuki_dryrun_r01_20261006_135700_661` | 309 | 10.285秒 | TTC WARNING成立およびtriple cadence開始時 |
| `phase5_v12_live_stop_raw_frame_0337.png` | 同上 | 337 | 11.297秒 | 停止完了直後、CLEAR復帰時 |
| `phase5_v12_live_hardware_warning_raw_frame_0372.png` | `phase5_v12_live_kobuki_hardware_r01_20261006_143236_125` | 372 | 12.390秒 | 実走行hardwareでTTC WARNINGと物理FFBが成立した時点 |
| `phase5_v12_live_hardware_stop_raw_frame_0396.png` | 同上 | 396 | 13.190秒 | hardware走行の停止完了直後、CLEAR状態 |
| `phase5_v12_live_hardware_r03_raw_frame_0206.png` | `phase5_v12_live_kobuki_hardware_r03_20261006_153755_541` | 206 | 6.856952秒 | 箱が見えているがライブ検出が途切れ、UNKNOWN単発通知が出た時点 |
| `phase5_v12_live_hardware_r03_raw_frame_0350.png` | 同上 | 350 | 11.648719秒 | 停止中も箱は見えるが、接地点のraw z推定が1.7018 mとなり測定不採用の時点 |
| `phase5_v12_live_hardware_r03_contact_jump_raw_frame_0306.png` | 同上 | 306 | 10.180110秒 | 動画再計算の接地点z=1.734918 m、選択点のIQRは4.47 mmだが次frameと大きく異なる時点 |
| `phase5_v12_live_hardware_r03_contact_jump_raw_frame_0307.png` | 同上 | 307 | 10.215805秒 | 動画接地点z=1.249292 m、前frameから48.6 cm変わる時点 |

定量判定は`../phase5_v12_live_kobuki_dryrun_r01_diagnosis.md`、`../phase5_v12_live_kobuki_hardware_r01_diagnosis.md`と各CSV/JSONを参照すること。

r03の2点は、床面変更後の認識・距離推定課題を説明するため追加した。診断は`../phase5_v12_live_kobuki_hardware_r03_diagnosis.md`、対応グラフは`../phase5_v12_live_kobuki_hardware_r03_analysis/live_distance_ttc_ffb_timeline.png`を参照する。グラフ・r03のPNGの再生成方法は同診断と`../phase5_v12_live_kobuki_hardware_r03_diagnostic_plots.py`に記載した。

原因切り分け用グラフを`../phase5_distance_instability_diagnosis/`へ保存した。`r03_detector_sensitivity.png`は輪郭設定の感度、`r03_reinitialization_sensitivity.png`は同じ測定からの速度・TTC推定の感度を示す。根拠CSVと生成用`plot_ablation.py`を同フォルダに保存しており、実機設定の変更後結果ではなくオフライン診断である。

視覚速度の根拠確認候補の比較図も`../velocity_confidence_candidate/`へ追加した。

- [r03の候補あり／なし比較](../velocity_confidence_candidate/r03_confidence_comparison.png): 衝突状態、視覚速度と距離傾向、仮想通知の比較。実機の変更後結果ではない。
- [人工高速接近の応答](../velocity_confidence_candidate/synthetic_critical_response.png): 通常窓成熟だけの方式と短時間確認を含む候補の遅れ。実物の録画ではない。

根拠と再生成方法は[候補評価結果](../velocity_confidence_candidate/README.md)に記載した。

保存動画から処理経路を再計算した比較図を`../raw_velocity_confidence_candidate/`へ追加した。

- [ライブ／動画の衝突状態](../raw_velocity_confidence_candidate/live_video_risk_comparison.png): r01～r03の記録状態、測定値再構築、動画候補なし／ありを比較。
- [ライブ／動画の距離測定](../raw_velocity_confidence_candidate/live_video_distance_comparison.png): 保存映像とライブ測定の違いを示す。距離の実測正解や改善後の画像ではない。

根拠CSV、生成用`plot_raw_replay.py`、解釈上の制約は[動画再計算結果](../raw_velocity_confidence_candidate/README.md)を参照。

輪郭・接地点の品質診断資料を追加した。

- [検出輪郭の品質比較](../ground_contact_quality_diagnosis/selected_contour_quality.png): r01～r03の形状、暗い青候補割合、接地点分布・選択割合の感度。
- [r03の品質・距離の時間変化](../ground_contact_quality_diagnosis/r03_contact_quality_timeline.png): 動画上の横長除外と接地点の不安定さ。

2枚の追加PNGは元動画の全画素を維持して保存・照合した。根拠、画像manifest、再生成用`create_quality_assets.py`、閾値を実機へ採用していない理由は[品質診断](../ground_contact_quality_diagnosis/README.md)を参照。

箱本体の領域分離・底部選択のオフライン比較を追加した。

- [r03の接地点候補比較](../box_contact_candidates/r03_contact_candidate_timeline.png): 6方式の距離、接地点pixel、ODOMとの隣接不整合。緑の点は粗い目視底部ラベルで、物理距離の実測値ではない。
- [少数画像の底部位置確認](../box_contact_candidates/coarse_base_label_comparison.png): 6枚の可視底部の目視位置と選択点との差。実機の変更後結果ではない。
- `phase5_v12_live_hardware_r02_contact_raw_frame_0350.png`: hardware r02 session `phase5_v12_live_kobuki_hardware_r02_20261006_150430_183`のframe 350。底部が車体で一部隠れるため、箱bboxの確認に使用し、底部位置の精度評価には使用しない。
- `phase5_v12_live_hardware_r03_contact_raw_frame_0100.png`: hardware r03 sessionのframe 100。前進前の箱本体・底部確認用。

追加2枚も1280×720の無加工PNGで、元動画の全画素と照合した。比較に再利用した既存5枚も照合済み。元動画・frame・PNG hashは`../box_contact_candidates/raw_assets_manifest.csv`、根拠CSV・候補条件・再現方法は[候補比較結果](../box_contact_candidates/README.md)を参照する。本番検出器やFFBの設定は変更していない。

固定した候補の左右・距離・遮蔽・接近検証資料を追加した。

- [左右4配置の位置誤差](../box_contact_validation/spatial_position_error.png): 全検出のX/Z平均絶対誤差。距離校正を合わせ直していない。
- [初期距離の偏りと警告時刻](../box_contact_validation/distance_bias_and_warning_timing.png): r02初期1.3 mとのゲート前の距離誤差と、過去接近録画のWARNING開始時刻差。物理振動遅延ではない。
- `box_validation_occluded_raw_frame_0431.png`: `x0.0mz1.2m_shahei_20260826_140829_186`のframe 431。既存ラベルは完全遮蔽だが、実画像では板の下に箱の一部が見える。候補がその部分を検出するが、面積ゲートで測定不採用となった場面。ラベルの制約を示す。
- `box_validation_right_0p9m_raw_frame_0350.png`: `x0.3mz0.9m_20260826_140106_996`のframe 350。右x=0.30 m、z=0.90 mの配置確認用。

追加PNGは元動画全画素と照合し、元解像度1280×720・無加工で保存した。session/frame/経過時刻とhashは`../box_contact_validation/raw_assets_manifest.csv`に記録。根拠CSV、再生成用`create_validation_assets.py`、候補の距離偏りと本番採用を保留する理由は[固定候補の回帰検証](../box_contact_validation/README.md)を参照。

接地点と校正を分けた診断図を追加した。

- [接地点による左右間隔の違い](../box_contact_calibration_diagnosis/lateral_span_decomposition.png): 同じ校正係数でも、選ぶ接地点により左右の名目配置との整合が変わる。名目値で係数を学習した結果ではない。
- [r02の固定pixelでの幾何感度](../box_contact_calibration_diagnosis/r02_fixed_pixel_geometry_sensitivity.png): pixel・pitch・高さを仮に変えた場合のraw Z変化。輪郭を含めた再生や推奨する校正値ではない。

根拠CSV・hash・再生成スクリプト`create_diagnosis_assets.py`と、ユーザー確認済みの初期距離の起点は[接地点・校正の分離診断](../box_contact_calibration_diagnosis/README.md)にまとめた。既存の生画像は編集していない。

旧完全遮蔽ラベルの全182 frameのレビュー資料を追加した。

- [全フレーム目視後の分類](../occlusion_label_review/full_review_label_coverage.png): 旧完全遮蔽3区間は全て部分遮蔽で、真の完全遮蔽性能の評価対象がないことを示す。検出の有無に関係なく全182 frameを確認した。
- `box_validation_partial_top_raw_frame_0800.png`: `x0.0mz1.2m_shahei_20260826_140829_186`のframe 800、第3遮蔽区間。板の上／左端に箱の上端・側面が見える状態。第2区間の既存frame 431とは別の隠し方の例。

追加PNGは1280×720、元動画全画角・全画素と照合済みで無加工。時刻・動画／PNG／画素hashは`../occlusion_label_review/full_review_raw_assets_manifest.csv`、集計と再現方法は[全区間レビュー](../occlusion_label_review/README.md)を参照。旧完全遮蔽ラベルと過去集計は上書きしていない。

過去UNKNOWN録画の追加目視レビューと固定候補比較を追加した。

- [107 frameの目視分類](../unknown_occlusion_validation/visual_review_coverage.png): 選定2区間の可視15、部分遮蔽53、完全遮蔽4、判定不能35 frame。完全遮蔽は約0.10秒で、長い遮蔽の性能を証明する図ではない。
- `unknown_review_v11_raw_frame_0963.png`: `phase5_v11_reliability_dryrun_r01_20260929_153520_912`のframe 963。完全遮蔽と確認した短い区間の先頭。
- `unknown_review_v11_raw_frame_1120.png`: 同sessionのframe 1120。板・手の境界の微小部分を断定できず、判定不能とした例。

2枚とも1280×720・無加工で元動画全画素と照合した。manifestと時刻・hashは`../unknown_occlusion_validation/raw_assets_manifest.csv`、107 frame×3方式の集計・再生成方法・未評価項目は[追加遮蔽レビュー](../unknown_occlusion_validation/README.md)を参照。

v12録画の追加探索・復帰比較を保存した。

- [v12の目視点分類](../v12_occlusion_screening/review_coverage.png): 72点の分類数。疎なサンプル間は未レビューで、分類数から遮蔽時間を推定しない。
- [連続42 frameの目視・測定復帰](../v12_occlusion_screening/continuous_window_recovery.png): dry-runの410～430、760～780の全frameと固定3方式の検出・採否。
- `v12_occlusion_dry_raw_frame_0763.png`: `phase5_v12_reliability_dryrun_r01_20260929_162234_202`のframe 763、25.480723秒。短い完全遮蔽の例だが、ODOM速度は既に0である。
- `v12_occlusion_hardware_raw_frame_0900.png`: `phase5_v12_hardware_unknown_r01_20260929_184546_956`のframe 900、30.523273秒。板の右側に箱の端が残る部分遮蔽の例。

2枚とも全画角1280×720の無加工PNGで元動画の全画素と照合した。manifestと根拠CSV、再生成スクリプト、長い完全遮蔽の未評価は[v12追加診断](../v12_occlusion_screening/README.md)を参照。
