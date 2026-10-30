# 同一フレーム証拠ログ（7.3 step 1）

HANDOFF 7.3 の1番「静止・実GPUで入力画像／選択bbox／支持点／床モデル／姿勢／鮮度の理由を同フレームで記録」のためのログ拡張。距離制御・姿勢推定・接地判定・FFBには使用しない。

## 現状

- 実装・合成テスト済み（カメラ／GPU／ソケット不要）。
- **実機の静止キャプチャは未実施。** 2026-10-30 時点の解析PC（`robo25-NUC11PAHi5`、`150.89.169.76`）には `/dev/video*` がなく、設定が要求するcheckpoint `3a6e124a...` も存在しない（`~/Downloads/cone.pt` は `39c94a4b...` で不一致）。GPU（RTX 3070）と `theta-yolo-env` は利用可能。
- 実機を行う場合は、カメラを接続したPCでcheckpointのSHA-256が設定値と一致していることを先に確認する。不一致なら`YoloConePredictor`が起動前に拒否する。

## 追加した記録

`--frame-evidence` を明示したときだけ、`distance_frames.jsonl`の各行へ`frame_evidence`を追加する。既定は無効で、既存の出力・判定は変わらない。

| 区分 | 記録内容 |
| --- | --- |
| 入力 | `session`、`frame`、`media_time_sec`、`received_time_sec`、1280×720。画素そのものはJSONへ埋め込まない |
| 選択bbox | 対象ROI・信頼度フィルタ後のbbox座標、confidence、class_id（最大`max_det`件） |
| 支持点 | 制御に使ったV30 union HSVの下包絡`point`と`support`全列、`colour_reason`、時間品質ゲートの採否 |
| 姿勢 | `initialized`、`pose_available`、`pose_reason`、`up_optical`、`scene_reason`、`scene_source_frame`、`scene_age_sec`、scene保留 |
| 床モデル | `paper7_ground_reference`、config／camera候補／floor候補のSHA-256。どの設定で投影したかをフレーム単位で固定 |
| 鮮度 | `frame_age_ms`、500 ms上限、`within_limit`、blockers、主理由 |

画像との対応は`session`と`frame`で行う。Sキーで保存するPNGはファイル名にsession digestと`f%06d`を含むため、同じフレームの無加工画像を後から照合できる。全フレームのPNG保存は行わない。

`frame_evidence`内も`physical_metric_verified=false`、`pose.physical_transform_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false`を維持する。要約側は、支持点が実際の`support`列に含まれること、bboxが画像内かつ単一クラスであること、証拠のframeが行と一致すること、鮮度判定が500 ms上限と一致することを検証し、違反行を拒否する。

## 変更ファイル

- `src/cone_distance_core.py`: `frame_evidence`引数と`frame_evidence`ブロック。`config_sha256`をengine初期化時に固定。
- `src/cone_distance_worker.py`: 引数の受け渡しのみ。
- `src/run_cone_distance_live.py`: `--frame-evidence`（既定OFF）と`live_summary.json`への有効化記録。
- `src/summarize_cone_distance_live.py`: 任意ブロックの検証と集計（`frame_evidence`）。
- `tests/test_frame_evidence_logging.py`: 11テスト。

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

結果: 新規11件、関連111件がPASS。既定engineの結果が証拠ブロック以外で一致すること、証拠追加が距離を変えないこと、不正なbbox・支持点・承認flagを要約が拒否することを確認した。

## 実機での実行（未実施）

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
