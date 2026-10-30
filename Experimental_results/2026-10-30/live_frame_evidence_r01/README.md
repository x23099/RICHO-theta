# 同一フレーム証拠ログ（7.3 step 1）

HANDOFF 7.3 の1番「静止・実GPUで入力画像／選択bbox／支持点／床モデル／姿勢／鮮度の理由を同フレームで記録」のためのログ拡張。距離制御・姿勢推定・接地判定・FFBには使用しない。

## 現状

- 実装・合成テスト済み（カメラ／GPU／ソケット不要）。
- **実機の静止キャプチャを2026-10-30に実施済み。** GPU PC（RTX 4070 Laptop）で60.02秒、1,656フレーム。全行に証拠ブロックが入り、`live_cuda_yolo`、checkpoint `3a6e124a...`一致、clean shutdownを確認した。
- 結果は[analysis_r01](analysis_r01/README.md)。基準支持点0/1,656、姿勢0/1,656、距離0/1,656。bboxは1個/全frame、中央値47.25×88.08 pxで静止。色輪郭のcrop端接触と背景平面不足をbbox付きで再現した。
- 返送archiveにSキーPNGとreportは含まれなかった。reportは解析PCで再生成した。
- **r02拡張を実装し、2026-10-30 18:53に再取得した。** `mask_diagnostics`としてcrop境界、マスク寸法、輪郭数・面積、選択輪郭bounds、接触辺を追加した。距離制御は変更していない。
- r02結果は[analysis_r02](analysis_r02/README.md)。1,689フレームで接触辺は左100%、右89%、下93%、上0%。保存PNGでは床のベージュがS≈81で黄色範囲に入り、赤コーンと連結していた。基準支持点・姿勢・距離は依然0。赤のみshadowは1,636点を持つが昇格しない。
- 解析中に`frame_evidence.freshness.age_ms`と行の`frame_age_ms`の0.02 ms不整合を見つけ、workerで再同期するよう修正した。取得済みログは1 ms許容で解析しており、再取得は不要。

## 追加した記録

`--frame-evidence` を明示したときだけ、`distance_frames.jsonl`の各行へ`frame_evidence`を追加する。既定は無効で、既存の出力・判定は変わらない。

| 区分 | 記録内容 |
| --- | --- |
| 入力 | `session`、`frame`、`media_time_sec`、`received_time_sec`、1280×720。画素そのものはJSONへ埋め込まない |
| 選択bbox | 対象ROI・信頼度フィルタ後のbbox座標、confidence、class_id（最大`max_det`件） |
| 支持点 | 制御に使ったV30 union HSVの下包絡`point`と`support`全列、`colour_reason`、時間品質ゲートの採否 |
| マスク診断 | `crop_bounds`（右下は排他）、`mask_shape`、輪郭数・面積、選択輪郭bounds（右下は包含）、`touches`、`touching_edges`。棄却理由の接触辺を特定する |
| 姿勢 | `initialized`、`pose_available`、`pose_reason`、`up_optical`、`scene_reason`、`scene_source_frame`、`scene_age_sec`、scene保留 |
| 床モデル | `paper7_ground_reference`、config／camera候補／floor候補のSHA-256。どの設定で投影したかをフレーム単位で固定 |
| 鮮度 | `frame_age_ms`、500 ms上限、`within_limit`、blockers、主理由 |

画像との対応は`session`と`frame`で行う。Sキーで保存するPNGはファイル名にsession digestと`f%06d`を含むため、同じフレームの無加工画像を後から照合できる。全フレームのPNG保存は行わない。

`frame_evidence`内も`physical_metric_verified=false`、`pose.physical_transform_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false`を維持する。要約側は、支持点が実際の`support`列に含まれること、bboxが画像内かつ単一クラスであること、証拠のframeが行と一致すること、鮮度判定が500 ms上限と一致することを検証し、違反行を拒否する。

## 変更ファイル

- `src/cone_distance_core.py`: `frame_evidence`引数と`frame_evidence`ブロック。`config_sha256`をengine初期化時に固定。`observe_support`／`support_from_colour_mask`の`evidence`引数でマスク診断を追加（既定は従来と同一）。
- `src/cone_distance_worker.py`: 引数の受け渡しのみ。
- `src/run_cone_distance_live.py`: `--frame-evidence`（既定OFF）と`live_summary.json`への有効化記録。
- `src/summarize_cone_distance_live.py`: 任意ブロックの検証と集計（`frame_evidence`）。
- `tests/test_frame_evidence_logging.py`: 16テスト。

## テスト

```bash
cd RICHO-theta
python3 -m unittest discover -s tests -p 'test_frame_evidence_logging.py' -v
for t in test_cone_distance_diagnostic test_cone_distance_worker_lifecycle \
         test_cone_distance_live_cleanup test_summarize_cone_distance_live \
         test_cone_completion_shadow_logging test_cone_colour_support_candidate; do
  python3 -m unittest discover -s tests -p "$t.py" || exit 1
done
```

結果: 新規16件、関連111件がPASS。既定engineの結果が証拠ブロック以外で一致すること、証拠追加が距離を変えないこと、不正なbbox・支持点・承認flagを要約が拒否することを確認した。

## 実機での実行（r02、実施済み）

r02は2026-10-30 18:53に実施済み。以下は再取得・再現時の手順。

GPU PC（HANDOFF記載の`hsr`）で、checkpointとカメラを確認してから実行する。解析PCから遠隔操作する前提は置かない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
sha256sum "$HOME/Downloads/cone_distance_v03.pt"   # 3a6e124a... と一致すること
HANDOFF_RUN_ID="$(date +%Y%m%d_%H%M%S)"
./start_cone_distance.sh receive \
  --weights "$HOME/Downloads/cone_distance_v03.pt" \
  --target-roi 270 0 350 720 \
  --colour-support-shadow --support-completion-shadow --frame-evidence \
  --duration-sec 60 \
  --output-dir "Experimental_results/2026-10-30/live_frame_evidence_${HANDOFF_RUN_ID}"
```

静止状態で60秒。必要に応じてSキーで無加工PNGを保存する。終了後に集計する。

```bash
./start_cone_distance.sh report \
  --input-dir "Experimental_results/2026-10-30/live_frame_evidence_${HANDOFF_RUN_ID}" \
  --output-dir "Experimental_results/2026-10-30/live_frame_evidence_report_${HANDOFF_RUN_ID}"
```

確認する項目:

1. `inference_source=live_cuda_yolo`（注入predictorでない）。
2. `frame_evidence.frames_with_one_selected_box`と`frames_with_support_point`。
3. `pose.pose_available`と`scene_reason`。10/30と同じ背景なら姿勢不成立が再現するはずで、これをログ拡張で隠さない。
4. `freshness.within_limit`と`frame_age_ms`分布。
5. 距離出力の有無。出力があっても条件付き診断であり、物理精度・接地の合格ではない。

## 返送後の解析（解析PC）

返送された`live_frame_evidence_*`に対し、`flatten_evidence.py`で1フレーム1行のCSVと集計を作る。

```bash
python3 Experimental_results/2026-10-30/live_frame_evidence_r01/flatten_evidence.py \
  --input-dir <返送された実行ディレクトリ> \
  --output-dir Experimental_results/2026-10-30/live_frame_evidence_r01/flatten_r01
```

`frame_evidence.csv`にbbox・支持点・姿勢・scene理由・鮮度・blockers、`counts.json`に理由別件数と`contains_injected_or_unverified_predictor`を保存する。予測器が`live_cuda_yolo`でないログは実GPU結果として扱わない。

## 明示しないこと

- このログ拡張だけで支持点が床接点であること
- bbox下端や支持点を接地の正解とすること
- 60秒の連続出力を距離精度のPASSとすること
- ライブ経路・ROS・FFBへの接続
