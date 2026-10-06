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
