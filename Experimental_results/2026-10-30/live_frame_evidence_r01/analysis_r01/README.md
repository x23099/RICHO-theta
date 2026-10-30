# 実機同一フレーム証拠ログ 20261030_181804 の解析

2026-10-30、GPU PC（RTX 4070 Laptop、torch 2.7.1+cu118）で取得した60秒静止ログ。HANDOFF 7.3 step 1の実機確認。

## 結論

- ログ拡張は機能した。1,656処理フレームすべてに選択bbox・支持点・姿勢・床モデル識別子・鮮度理由が同一行で記録された。
- 予測器は`live_cuda_yolo`、checkpoint SHA-256は設定値`3a6e124a...`と一致。注入predictorではない。
- しかし**基準支持点は0/1,656、姿勢取得も0/1,656、距離出力も0/1,656**。10/30の遮断要因（色輪郭のcrop端接触、背景平面不足）を、bbox座標付きで再現した。
- bboxは全フレームで1個、中央値47.25×88.08 px、中心`(292.2, 343.9)`、jitterは約1～2.7 px。静止条件は保たれている。
- `colour_support_shadow`は1,430点、`support_completion_shadow`は1,645点（追加取得215件）を持つが、**制御支持点ではない**。基準支持点0をshadowで埋めない。
- どのcrop辺に接触したかは、今回のログに輪郭境界・crop境界を記録していないため断定しない。bboxと4 px拡張の関係から、左・下を含む複数辺が候補になる。

## 入力

| 項目 | 値 |
| --- | --- |
| archive | `/home/robo25/Downloads/live_frame_evidence_20261030_181804.tar.xz` |
| archive SHA-256 | `fb7e79e07f806aa2876088773c04faad287c0b9809d0429ef525f9cc423c660a` |
| 展開先（Git外） | `recordings/2026-10-30/live_frame_evidence_20261030_181804/` |
| `distance_frames.jsonl` SHA-256 | `1651b1fe4eda2bf92cc76c388e24dac78da8e572a2fd554937402ec6881687e6` |
| `live_summary.json` SHA-256 | `06d3317e5aa68654b4039db8cc7b5db4898f0a4bab535d50e32aa448c4225d7c` |
| session | `b041fd4f2da148eeb2c7afcb442305bf` |
| 実行時間 | 60.02 s、`runtime_status=STOPPED`、cleanup errorなし |
| GPU / weights | RTX 4070 Laptop / `3a6e124a...`（設定と一致） |
| target ROI | `[270, 0, 350, 720]` |
| 有効フラグ | `frame_evidence=true`、colour shadow / completion shadow=true |

返送archiveには`live_frame_evidence_*`のみが入り、`live_frame_evidence_report_*`とSキーPNGは含まれていなかった。集計は解析PCで再生成した（`report/`）。

## 定量結果

| 項目 | 結果 |
| --- | ---: |
| 処理フレーム | 1,656 |
| session数 | 1 |
| frame gap合計 | 31 |
| 選択bbox 1個のフレーム | 1,656 / 1,656 |
| 選択bbox 0個 | 0 |
| 基準支持点あり | 0 |
| 姿勢利用可能 | 0 |
| 距離出力 | 0 |
| 鮮度500 ms以内 | 1,655（初回のみ976.5 ms） |
| frame age 中央値 / p95 / 最大 | 13.95 / 19.65 / 976.47 ms |
| 推論時間 中央値 / p95 | 6.74 / 8.26 ms |
| 支持幾何 中央値 / p95 | 3.55 / 8.73 ms |
| 受信後処理 中央値 / p95 | 10.43 / 15.68 ms |

### bbox

| 項目 | 最小 | 中央値 | 最大 | 変動幅 |
| --- | ---: | ---: | ---: | ---: |
| x1 | 268.27 | 268.58 | 270.25 | 1.98 |
| y1 | 299.02 | 299.91 | 301.73 | 2.71 |
| x2 | 315.59 | 315.83 | 316.58 | 0.99 |
| y2 | 387.39 | 387.99 | 389.14 | 1.75 |
| width | 45.94 | 47.25 | 47.61 | 1.67 |
| height | 86.52 | 88.08 | 89.12 | 2.60 |
| confidence | 0.95 | 0.96 | 0.97 | 0.02 |

bbox中心は`(292.06, 343.51)`～`(293.41, 345.28)`で、指定ROI `x=270..350`の内側。カメラ・対象は実質静止している。

### 保留理由

| 理由 | フレーム数 |
| --- | ---: |
| `colour_contour_reaches_roi_edge`（主理由） | 1,655 |
| `frame_processing_too_old`（初回のみ） | 1 |
| blocker: `unavailable_support:colour_contour_reaches_roi_edge` | 1,656 |
| blocker: `latest_scene_image_rejected` | 1,656 |
| blocker: `colour_contour_reaches_roi_edge` | 1,656 |
| blocker: `newer_scene_processing_pending` | 124 |
| scene: `fewer_than_six_distinct_planes` | 1,656 |
| pose: `latest_scene_image_rejected` | 1,656 |

基準支持点は、bboxを4 px拡張したcrop内の赤・黄・混合マスク主輪郭がcrop端に接するため、全フレームで棄却された。bboxは`x1≈268.6`、crop左端は約`264`、crop下端は約`392`であり、輪郭がbbox外へ数px広がっていれば左・下の接触が成立する。ただし今回のログは輪郭境界そのものを保存していないため、接触辺を確定しない。

### shadow（制御に未使用）

| shadow | 画像候補点あり | 内訳 |
| --- | ---: | --- |
| colour support | 1,430 / 1,656 | red 1,646、withheld 10。`unverified_visible_colour_support` 1,430、端接触216、曖昧10 |
| lateral completion | 1,645 / 1,656 | 既存shadow点1,430、追加取得215、not eligible 10、bbox外1 |

shadowは基準支持点0の穴を埋めるために使わない。`controlling_distance=false`、`usable_for_ffb=false`を維持する。

## 解析中に見つけた記録不整合

初回実装では、`frame_evidence.freshness.age_ms`をengine内の処理完了時刻で記録し、その後workerが行の`frame_age_ms`を最終時刻で上書きしていた。差は約0.017～0.02 msで、順序・鮮度判定は変わらないが、同一行内で値が一致しない。

- workerで最終`frame_age_ms`・`within_limit`・`blockers`・`reason`へ再同期するよう修正した。
- 検証側は、修正前ログを再取得せず解析できるよう、age差1 ms以内を許容する。1 msは500 ms上限に対して無視できる。
- このログの差は最大でも0.06 ms程度で、全行が許容内。再取得は不要。

## 成果物

- `flatten/frame_evidence.csv`: 1,656行のフレーム単位証拠
- `flatten/counts.json`: 理由別件数、bbox数、支持点、姿勢、鮮度、床モデルhash
- `report/report.md`, `report/summary.json`, `report/processed_frames.csv`, `report/processing_diagnostics.png`: 既存集計
- 生成: `flatten_evidence.py`、`src/summarize_cone_distance_live.py`

```bash
cd RICHO-theta
IN=/home/robo25/theta_ws/recordings/2026-10-30/live_frame_evidence_20261030_181804
python3 Experimental_results/2026-10-30/live_frame_evidence_r01/flatten_evidence.py \
  --input-dir "$IN" \
  --output-dir Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r01/flatten_r02
python3 src/summarize_cone_distance_live.py --input-dir "$IN" \
  --output-dir Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r01/report_r02
```

出力先は新規ディレクトリ必須。`analysis_r01`は今回の固定結果。

## 次に必要な判断

1. **接触辺を特定するログ拡張（r02で実施済み）**: `mask_diagnostics`へcrop境界、マスク寸法、輪郭数・面積、選択輪郭bounds、接触辺を追加し、60秒再取得した。結果は[analysis_r02](../analysis_r02/README.md)。
2. **画像を残す**: 次回はSキーで無加工PNGを1枚以上保存する。今回のarchiveにはPNGがない。
3. **姿勢側の設計**: 背景は`fewer_than_six_distinct_planes`のまま。支持点が取れても姿勢が無ければ距離は出ない。6平面条件の緩和や別録画姿勢の流用はしない。

いずれも実装・再取得は別判断。今回はログ拡張の成立と遮断要因の再現までとし、距離精度・接地・FFBへ進めない。

## 明示しないこと

- 支持点が床接点であること
- shadow点を基準支持点の代替とすること
- bbox下端を接地点とすること
- 0/1,656を「測距失敗の原因が支持点だけ」と断定すること
- 60秒のログを距離精度のPASSとすること
