# 2026-09-02 動的TTC候補決定記録

## 結論

次回の独立holdout候補を次で固定する。現時点では開発候補であり、本番設定へは昇格しない。

| 項目 | 現行 | 固定候補 |
|---|---:|---:|
| Kalman process acceleration std | 1.5 m/s² | 1.5 m/s²（変更なし） |
| TTC velocity window | 0.3 s | 0.3 s（変更なし） |
| TTC deadband | 0.05 m/s | 0.03 m/s |
| WARNING TTC | 4.0 s | 4.6 s |
| WARNING exit TTC | 5.0 s | 5.6 s |
| WARNING確認 | 3 frame | 3 frame（変更なし） |

候補configは`src/bird_eye_config_ttc_candidate_20260902.json`、評価条件は
`src/dynamic_ttc_evaluation_profile_v3_candidate.json`、試行数・録画完全性条件は
`Experimental_results/2026-09-02/2026-09-02_ttc_candidate_requirements.csv`とする。

## 選定根拠

9月1日30 fps動的holdout、8月18日旧動的録画、8月26日静止録画に対し、録画時に採用された
観測点を固定して12候補を再生した。全23試行の最大値は次のとおりだった。

| 候補 | 0.10 m/s接近応答 | 0.20 m/s接近応答 | 接近速度MAE | 後退誤TTC | 静止誤TTC |
|---|---:|---:|---:|---:|---:|
| 現行`1.5 × 0.05` | 0.940 s | 0.599 s | 0.0524 m/s | 0% | 0% |
| 候補`1.5 × 0.03` | 0.527 s | 0.474 s | 0.0527 m/s | 0% | 0% |

process acceleration stdの変更よりdeadbandの変更が応答へ効いた。候補はKalmanを変更せず、
deadbandだけを下げる最小変更とした。感度評価の全結果は`ttc_kalman_sensitivity_report.md`、
試行別値は`ttc_kalman_sensitivity_details.csv`に保存した。

方向応答はODOMと推定速度が同時に5 frame連続する厳密な定義で評価した。候補の既知データ最大
0.527秒を包含しつつ独立holdoutで検証できるよう、方向応答上限は0.60秒で事前固定した。
TTC発火遅延は別指標であり、上限0.50秒を維持した。

4.6秒候補は9月1日録画の3 frame警告成立に必要な理論最小値4.422～4.542秒を、
安全側に0.1秒単位で切り上げた値である。既存録画を見た後の候補なので、効果の最終判定には
新しい独立録画が必要である。

## 次回独立holdout条件

候補config/profileをコミットした後にのみ録画する。

| 条件 | 試行数 | 時間 | ラベル |
|---|---:|---:|---|
| 青箱静止・Kobuki停止 | 3 | 各20秒 | `static_center_ttc_r01`～`r03` |
| 0.10 m/s接近 | 3 | 各20秒 | `approach_center_v0p10_r01`～`r03` |
| 0.10 m/s後退 | 3 | 各20秒 | `retreat_center_v0p10_r01`～`r03` |
| 0.20 m/s接近 | 3 | 各20秒 | `approach_center_v0p20_r01`～`r03` |

- MJPG 1280×720・30 fps、ODOM `/odom`。
- 青箱中央、開始距離約1.3 m、直進。
- 接近・後退後は停止状態を数秒記録してから録画を終了する。
- 同じ録画を見て候補値を再調整しない。FAIL時は原因診断用として保持する。

実験起動例:

```bash
python3 src/run_field_experiment.py \
  --record-dir recordings/2026-09-02_ttc_candidate \
  --experiment-label approach_center_v0p10_r01 \
  --config src/bird_eye_config_ttc_candidate_20260902.json \
  --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile_v3_candidate.json
```

preflightはconfigとprofileのTTC関連8項目を照合し、不一致時は録画アプリを起動しない。

録画後の一括解析では次を指定する。

```bash
python3 src/analyze_field_recording.py \
  --input /path/to/new_recording.tar.xz \
  --config src/bird_eye_config_ttc_candidate_20260902.json \
  --requirements Experimental_results/2026-09-02/2026-09-02_ttc_candidate_requirements.csv \
  --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile_v3_candidate.json \
  --output-dir Experimental_results/YYYY-MM-DD/ttc_candidate_holdout
```
