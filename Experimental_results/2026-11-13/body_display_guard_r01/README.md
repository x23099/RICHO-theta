# 近接遮蔽時の主表示保留：明示opt-in実装・既存データ検証

## 到達点

**このPCで実装・検証済み。GPU PCへの反映・実カメラでの新表示は未確認。**
通常の起動コマンドは既定OFFのため、変更後のコードだけを置いても表示挙動は変わらない。
新オプション `--motion-body-display-guard` を明示した実行だけが対象。
日報・commit/pushは今回未依頼で行っていない。未pushなのでGPU PCのPullだけでは今回の変更は届かない。

台座が天板に隠れても主表示に約0.65mが残る課題に対し、**元主結果は維持し、表示だけを保留できるゲート**を追加した。
非同期比較の数値を流用・採用するのではなく、現在の主フレームの支持列を、同接続でpin/load照合済みの境界へ当てる。
主測距式・YOLO・ROI・閾値・profile・平滑化は変更しない。half-pixel救済を主表示へ導入しない。
操縦・ROS・FFB・既存送信処理は変更していない。自動停止や安全制御の採用ではない。

## 既存r02のオフライン再計算

元実験・録画照合は[前段の監査](../guarded_motion_live_audit_r02/README.md)。
録画前の試走を除いたframe44063〜45275の1,186件だけを使った。
元主JSONLのsupport_observationを再評価したもので、画像からYOLO・支持画素を再抽出した結果ではない。
実機の過去表示を書き換えたものでも、新機能が当時動いていた証拠でもない。

| 項目 | 結果 |
|---|---:|
| 対象の主処理結果 | 1,186件 |
| 変更前の主数値 | 1,178件 |
| 表示に残す数値 | 911件、元の値と完全同値 |
| 自己遮蔽で表示保留へ変更 | 267件 |
| 元からのROI端保留 | 8件を維持、救済0 |
| 近接停止14〜20秒 | 177/177件を保留 |
| 元ログの変更 | なし、SHA一致 |
| ローカルCPUのゲート単体service P50/P95/最大 | 約0.47/0.85/5.21ms |

根拠は[最終集計](results_r02/evaluation.json)・[1,186件のCSV](results_r02/evaluation.csv)。
results_r01は世代巻戻し棄却を追加する前の同条件検証として保持し、最終結果はresults_r02を使う。
ゲート時間はこのPCでの関数単体計測で、GPU PCの追加総負荷・ファイル書込み・IPC・表示の測定ではない。
旧実験で参照が有効だった区間と発行済み参照のバイト一致を条件に評価したが、実機のpin/witness寿命やload処理は再実行していない。

## 実装

| 対象 | 役割 |
|---|---|
| src/driver_body_display_guard.py | 表示レビューの厳密なスカラー検証と現在支持列の棄却のみ。UIでのimport時にモデルや幾何を読み込まない |
| src/cone_guarded_stream_comparison.py | 成功した既存pin/PNG検証後だけ参照コピーを単一ownerから公開 |
| src/driver_guarded_comparison.py | 比較数値ではなく小さい参照をnonblocking lockで渡す。失敗・要求変更・失効・終了時は使用不可 |
| src/driver_motion_process.py | 同フレームの元結果を残し、表示レビューを別ログと任意IPCフィールドへ出力 |
| src/driver_motion_bridge.py | 同session/frame/source時刻・元数値を検証して、元値を表示するかWITHHELDにする。新CLIを子へ渡す |

表示レビューが未到着・不正・別frame・古い・参照未読込み等の場合は、元数値へ黙って戻さずWITHHELD。
境界に支持列のどれかが触れる場合、範囲外で外挿が必要な場合も保留。
主入力の0.5秒超の空白等で旧generationを退役させ、新しい明示load世代なしに復活しない。
現在の入力がactivationより前のフレームなら使用しない。全権限フラグはfalseを維持。

元の `motion_distance_frames.jsonl` と比較ログはそのまま。新モードだけ次を追加する。

- 子出力の `motion_display_reviews.jsonl`：元の距離／表示可否／表示理由／参照世代／完了時刻。
- `motion_bridge_events.jsonl` の `display_review`：同じframeに対応する表示レビュー。
- engine/bridge summaryの `body_display_guard`：有効化・表示棄却専用・元主結果非変更・関連コードSHA等。

既存比較statusの `main_display_modified=false` は「その非同期比較が主表示を上書きしていない」という意味のまま。
別の表示ゲートON/OFFは上記body_display_guardで区別する。
bridgeのaccepted_current_session_and_ageは元結果の受理であり、表示レビューが数値を許可した件数とは区別する。
新IPCはflag ON同士でのみ使い、レビューのない旧worker応答は拒否する。画像・支持列をUIへ送らない。

## 検証内容

新19テストと関連を含む200テスト成功。合成画像・メモリpipe・実ローカル子プロセス／threadを使用し、
実カメラ・ROS・ネットワーク・実YOLO/CUDAを起動していない。

- 正常数値と元支持列／元ログの不変、支持列の端1点が境界へ触れた場合の棄却。
- pin/load前、参照失敗・失効・終了、nonblocking lock競合、session不一致・未来activation・範囲外。
- 入力gap後の旧参照generation棄却、新世代load後の復帰。
- IPCレビューの誤frame・数値変更・権限昇格・旧worker形式の拒否。
- 実ローカルpipeで保留→遮蔽保留→正常数値へ復帰し、元IPC数値を変更しないこと。
- 既定OFFの既存動作、比較・証拠保存・終了処理、操縦／ROS／キー処理の既存ASTハッシュ不変。

2つの既存「幾何モジュールを直接importしない」テストは、単なるファイル名の来歴文字列まで禁止する検査だったため、
ASTのImport/ImportFromを調べる検査へ精密化した。直接import禁止は維持している。
新pipeテストの初回にはTemporaryDirectory削除後の二重cleanupが失敗したが、寿命順序を修正後に全件成功した。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_driver_body_display_guard.py tests/test_driver_guarded_comparison.py \
  tests/test_driver_motion_bridge.py tests/test_driver_motion_integration.py \
  tests/test_driver_withheld_evidence.py tests/test_cone_guarded_stream_comparison.py \
  tests/test_driver_motion_shutdown.py tests/test_cone_self_body_shadow.py \
  tests/test_guarded_compact_compute.py tests/test_guarded_observation_reuse_runtime.py \
  tests/test_cone_guarded_lower_edge_shadow.py tests/test_report_driver_motion_logs.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/body_display_guard_r01/evaluate.py \
  --intake-dir recordings/2026-11-13/guarded_motion_full_intake_r02 \
  --output-dir Experimental_results/2026-11-13/body_display_guard_r01/results_r02
```

出力は新規パス必須。元r02の過去監査は変更前の記録コードSHA照合結果を保持しており、
新コードのSHAに書き換えない。今回のゲート評価では入力原本SHAと新実装SHAを別に記録した。

## 次の段階

GPU PCへ新規1＋変更4のsrcファイルと関連テストをまとめて反映し、まず[静止確認手順](live_check.md)へ。
まだ新オプションの実UI・現在pin/load・実GPU負荷は未確認。今は追加走行・追加録画を要求しない。
静止で未load時の保留→同接続の新pin/load→正常数値の復帰を確認してから、近接時の表示確認を検討する。
旧session参照の転用はしない。今回も物理距離精度・床接地・動的姿勢補償・取付再現性の認定ではない。
