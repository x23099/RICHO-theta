# 固定床モデルの比較ログ接続（既定OFF）

作業日: 2026-10-30。既存の[固定床候補](../floor_pose_fixed_mode_r01/README.md)を、カメラ距離診断の**比較ログだけ**へ接続した。カメラ・通信・GPU・ROS/TF・FFBは起動していない。元の距離表示・床姿勢ゲート・校正・HSVは変更しない。

## できるようになったこと

- `receive`に`--fixed-floor-models PATH`を追加。未指定は従来どおりで、新しい処理を起動しない。
- 比較点の出所は`--fixed-floor-support-source baseline|colour_support_shadow|support_completion_shadow`で明示。既定は補完shadow。対応するshadowも明示的に有効化する必要があり、別候補への自動fallbackはしない。
- sessionを拘束したモデルbundle、各モデルの明示入力・非承認flag、既存configと同じheading referenceのpath/hashをGPU/通信起動前に検査。
- 同じフレームの`fixed_floor_shadow`へ、モデルbundle/hash、支持点、画像品質、保留理由、モデルごとの**カメラ鉛直足元からの条件付き水平距離**を記録する。
- 3モデルは全て保持。概算1.5 mに近いモデルや最小誤差モデルを選ばない。車体前方成分やbase_link距離として表示しない。
- 別の画像支持品質ゲートで連続3フレームを確認する。元のゲートを置換しない。session変更で状態をリセット、モデルsessionと異なる画像には幾何計算自体を行わない。
- 元と同じ受信後500 ms上限を適用。worker最終時刻でも遅延した数値を消し、あとから有効へ戻さない。処理例外も比較側の保留へ記録し、元の検出失敗にすり替えない。
- 標準`report`は従来距離件数と別に、比較出力/保留理由とbundle・モデル別の距離統計を集計する。session不一致、古いframe、支持点不一致、物理承認を名乗るログを拒否する。

`physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false`、`controlling_distance=false`を維持。新しい条件付き距離をGUIの元の距離へ重ねたり、TTC/FFBへ渡したりはしない。

## 実装

| ファイル | 内容 |
| --- | --- |
| `src/cone_fixed_floor_shadow.py` | bundle検査、session/支持品質/鮮度、複数モデルの比較観測 |
| `src/cone_distance_core.py` | 明示時だけ別項目へ接続。元の距離判定は元の入力のまま |
| `src/cone_distance_worker.py` | フラグ受渡し・最終鮮度で比較値を無効化 |
| `src/run_cone_distance_live.py` | CLI、GPU起動前の入力検査、summaryへの有効化記録 |
| `src/summarize_cone_distance_live.py` | 比較ログの検査・分離集計 |

既存`cone_fixed_floor_candidate.py`の計算内容は変更していない。以前は隔離モジュールのみ、現在は明示時の比較adapterを介する間接呼出しも可能、という更新である。以前の報告の「未接続」は当時の状態として残す。

## 検証結果

[正式検証JSON](verification_r02/verification.json)、[271テスト一覧](verification_r02/tests.csv)、[実行ログ](verification_r02/tests.log)。関連271件PASS、失敗0・エラー0・skip0。今回新規16件を含み、既存の固定床12件や色/支持点/通信/終了/レポート等を再確認した。プロジェクト全体の試験数ではない。

- 新機能未指定の既定動作、および明示指定時に比較項目を除いた元の判定を、直前の凍結engineと比較。
- 合成画像の3回確認後に3モデルの比較距離が出ても、元のsceneは初期化せず、元の距離は保留のまま。
- session不一致では`measure_support`を呼ばない。参照hash違い・混在session・重複モデル名・物理承認・未有効のsupport sourceを拒否。
- 支持点なしでは0 mや前回値を出さない。比較側の例外を記録して既存判定を維持。
- 遅いengine/worker完了時に数値を取り消す。古い比較値をreportが承認しない。
- 校正・固定床数学・色候補・姿勢・支持品質・映像通信など14ファイルは、基準commit`9392487`と同じ。
- 意図して変更した4ソースは、変更前の全量を`source_snapshot/`に保存。検証器は可変HEADではなく固定commitを参照するので、今回のcommit後も旧版との対応を保持する。

### 保存済み最新実機r02の全行

[evaluation_r02/summary.json](evaluation_r02/summary.json)。元JSONLの1,689行に比較adapterを適用。画素再推論・距離用姿勢の再fitはしない。

| 確認 | 結果 |
| --- | ---: |
| 記録行 | 1,689 |
| 元の判定フィールドが完全一致 | 1,689 |
| 比較モデルの数値出力 | 0 |
| model_session_mismatch | 1,688 |
| 初回鮮度超過 | 1 |

床板モデルはsession `15ae673c24484d119952ae391df611aa`専用だが、最新実機r02は`f860e50d1c4e485a98cbc1a2f6138cdf`。**別sessionの古いモデルから数値を出さないことが期待結果**であり、測距成功とは扱わない。

派生JSONLは`derived_recording/`へ保存し、推論出所を録画ログ再計算と明記。元のlive_summaryを偽造コピーせず、標準集計は`INCOMPLETE_CAPTURE`。元実機の正常終了を否定したのではなく、この派生ログを新しい実機試験へ見せないためである。時間は元ログの受信時刻・ageを再利用し、新しい実処理速度を計測した結果ではない。

### 同じ床sessionの保存画像2枚

frame1259/1655を各々独立した1画像としてengineへ入力し、正しいモデルsession・実際の保存bbox・候補点が比較経路へ入ることを確認した。ただし連続3画像がないため、両方とも`image_support_quality_not_confirmed`で距離保留。**同じ静止画を3回複製して確認済みとする処理はしていない。**

数値が出る統合経路は合成画像で確認した。以前の同session2枚の1.40～1.53 mは別途保存された単発数学診断であり、新しいライブ経路で連続出力できた結果へ読み替えない。

## 次回の作業

1. 現在のカメラ条件に対して、床モデルをどう計測・保持・無効化するかを決める。紙の法線、レンズ高さ、session、キャプチャ幾何の対応を明示する。
2. 現在session用の根拠がないまま、古いJSONのsession文字列だけを変えて使わない。将来sessionを跨いでモデルを使うなら、単なる文字列変更ではなく、物理的な取り付け状態に対応する校正ID/失効条件を別設計する。
3. 真の台座基準点と実測距離の情報を必要最小限に絞る。新しい録画を反射的に繰り返さず、既存証拠から取れない不足だけを相談する。
4. その後、静止実GPUで比較距離の継続出力・欠測・外れ値を確認する。物理精度を確かめるまで距離本判定・走行・FFBへ昇格しない。

## コマンド

既存データでの再現（解析PC、出力先は未使用名へ変更）:

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/evaluate_logging.py --output-dir Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/evaluation_r03
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/verify.py --evaluation-dir Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/evaluation_r03 --output-dir Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/verification_r03
```

後日、モデルと受信sessionの対応根拠を用意できた場合に限り、GPU PCの従来`receive`へ次の引数を追加する:

```text
--support-completion-shadow
--fixed-floor-models /実際に用意した/session_matched_models.json
--fixed-floor-support-source support_completion_shadow
```

既存の`explicit_floor_models.json`を新しい受信へそのまま付けても、session不一致で保留となる。上記は今すぐ距離が出る実験コマンドではない。既定の画面・FFBは変えない。集計は従来どおり`./start_cone_distance.sh report --input-dir 実際のログフォルダ --output-dir 未使用の集計先`。

`evaluation_r01/`は集計形式の拡張前、正式版はr02。今回の実装・検証は追加録画・実機駆動・外部依存追加を含まない。別作業の`red_only_support_eval_r01`とそのテストはcommit/push対象外。
