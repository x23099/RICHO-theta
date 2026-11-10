# 17:12実行ログ＋保留元画像8組の解析

2026-11-10。画面録画なしで、同じ実行の測距ログと自動保存画像を受領した。**保存8組は全て元ログと一致し、保存側の正常終了を確認できた。** 追加撮影は今回の照合・再計算の前提ではない。

## 入力と来歴

- `driver_motion_live_20261110_171250.tar.xz` SHA256: `ae67d265588280e686671585d6c702c8dd750f16f8a8923ee674bad63be82fda`
- 追加提出 `motion_withheld_20261110_171250.tar.xz` SHA256: `22f981b9e2429ec3ee7c0268ed5a72b88c57dfaa5ad38f09b7b6b61667ffb7ff`
- 展開先: `recordings/2026-11-10/driver_motion_171250_intake_r01/`。各archiveの同名フォルダを保持。リンク・特殊ファイル・絶対／親参照パスがないことと展開容量を確認した。元画像は未加工・1280×720。生ログ／画像をGitへ追加しない。
- session: `4c34c8c3d6d44949afb2e921e819e563`。
- 実行metadata: RTX 4070 Laptop GPU、torch 2.7.1+cu118、全16,929件が `live_cuda_yolo`。校正profile SHA `17a287159fcec644c373141cdbef893aa19dfced782dcf32d20b5f12dc91954e`。以前と同じprofile／configで、録画間の新しいfitや寸法調整はしていない。
- 画面録画・走行区間ラベル・独立した実測距離は今回未提出。車体走行の速度、画面の採用・点滅時間、物理誤差、操縦遅延はこの入力だけで確定しない。

## ログ集計

詳細は [全ログ集計](full_run_report/summary.json)、[frame CSV](full_run_report/frames.csv)、[追加画像を含めた正式監査r02](audit_r02.json)。`audit_r01.json` は画像archive追加提出前の中間記録で、画像未提出という記載は当時の状態。

|検査|結果|
|---|---:|
|処理結果|16,929件|
|最初～最後の処理完了の時間差|567.595秒（約9分28秒）|
|処理結果間隔からの平均更新率|29.824件/秒|
|数値出力|9,514件|
|出力距離の範囲|0.6227～1.1745 m（正解距離ではない）|
|受信後～計算終了のP50／P95|13.73／21.24 ms|
|初回1件を除いた最大同経過時間|105.10 ms|
|初回の遅延保留|frame 2、948.38 ms（YOLO 941.51 ms）|
|bridge対応|16,929件全て対応、16,928件採用、初回1件retire|
|worker_error|`null`|

全区間の保留は7,415件: `no_candidate` 6,775、複数候補552、輪郭境界78、上部色曖昧9、初回遅延1。開始後約228.66秒までは数値がなく、最初の数値frame 6862以降は10,156件中9,514件が数値。これは後から選んだ「最初の数値～終了」区間で、走行／静止や実物が常に画面内にいたことを示す区間ではない。全体の保留率43.8%を、そのまま走行時の失敗率や検出漏れ率と呼ばない。

輪郭境界78件の最初の抽出領域への接触は、左のみ74件、左＋上3件、右＋下1件。左のみ74件では拡張先で輪郭が閉じても、候補点が元のfloat bbox外となって保留している。処理済みrecordを連続として数えた保留列は17列、最大26件・先頭末尾の計算完了差839.24 ms。画面での保留時間ではない。

## 自動保存は実機で動作した

[保存検証](evidence_replay_r01/verification.json)でPNG SHA・全復号BGR画素SHA・sidecar SHA・session/frame・元ログの完全行SHAとJSON内容を照合した。

|検査|結果|
|---|---:|
|PNG＋判定JSONの検証完了|8組／8組|
|元測距ログとの対応|8組／8組|
|PNG＋sidecar合計|6,927,189 bytes|
|1秒間隔で保存対象外|70件|
|queue満杯／容量・件数上限／保存エラー|いずれも0／なし|
|保存writer終了・shutdown_complete|true|
|未完了index末尾・索引外ファイル|なし|

78対象＝8保存＋70間隔skip。設定どおりの間引きで、保存漏れと同一視しない。40組・128MiB上限には未到達。画面録画は、この照合には不要だった。

一方、bridge側summaryは `sent=16930, returned=16929, child_exitcode=null, io_thread_stopped=false, child_stopped=false`。**画像writerの正常終了は確認できるが、bridgeの記録時点で全子プロセス／I/O停止が確認済みだったとは言えない。** worker_errorはなく、保存側statusは完了なので「保存失敗」や「推論中にクラッシュ」とは断定しない。終了待ち／summary取得タイミングは別の残課題。

## 元画像で境界候補を再計算

[再計算summary](evidence_replay_r01/summary.json)、[全観測と計算値](evidence_replay_r01/comparisons.json)。新しいYOLO推論はせず、当時の検出枠を同frameの元画像へ適用した。元profileを使用し、画像／枠／校正を調整しない。計算時刻は合成で、速度測定ではない。

既存 `cone_bbox_boundary_shadow.py` のオフライン候補2種類だけを比較した。8枚全てでliveの支持観測全体と距離／保留理由／modelが完全一致した。live側は変更していない。

|frame|元画像の目視所見（接地正解ラベルではない）|現行|半画素重なり候補|外向き整数化候補|
|---:|---|---|---|---|
|6861|人の手が前面を横切る。遮蔽・色領域混入の可能性|保留|保留|保留|
|14203|コーン台座の手前側が天板に隠れる|保留|0.6230 m|0.6230 m|
|14267|同上|保留|0.6236 m|0.6236 m|
|14297|同上|保留|保留|0.6233 m|
|14329|同上|保留|0.6236 m|0.6236 m|
|14382|同上|保留|0.6230 m|0.6230 m|
|14604|台座が見えるが元抽出領域の左＋上に接触|保留|保留|保留|
|14922|台座が見える。別の機体が隣接して写る|保留|1.1425 m|1.1425 m|

候補の数値出力は半画素5枚、外向き整数化6枚。しかし**5枚では候補点のy=459が天板の遮蔽境界付近に並んでおり、真の台座手前辺や床との接点を読み取れたとは言えない**。隠れた床上の点を、見えている赤領域の下端で代用して距離を出す懸念がある。丸め方だけでこれらを通すlive変更は採用しない。

14922は台座の見える境界例として別扱いできるが、実測距離がないため1.1425 mの正しさは未認定。画像8枚以外の70対象frameは保存間引きされており、見た8枚の遮蔽所見を残り全frameへ一般化しない。

## 次に進める作業

追加撮影・再校正を要求せず、今回の8画像と保存ログを使う。

1. **近距離での自己遮蔽と、元bboxの画素座標境界を分ける。** 天板境界を床の点として拾わないことを、保留条件を緩める前の回帰条件にする。画像を加工せず元座標上で判定する。
2. 台座が見える14922／14604と、遮蔽5枚・手遮蔽6861を固定したオフライン比較集合にする。未測量画像から誤差改善や接地の正解を作らない。
3. 保存writer完了とは独立に、bridge終了summaryの取得タイミングをコード／模擬プロセスで点検する。ROSや実機を起動して確認することを最初の条件にしない。

カメラからの水平距離を表示する現在の実験用途は維持する。機体中心距離・接触距離・姿勢変動補償・制御／FFBへの接続を認定した結果ではない。処理の継続は確認できるが、保存ONによる遅延増分を同条件ON/OFF実験で測ったわけではない。

## 再現

上記2archiveを同じintake先へ安全に展開してある場合。未使用出力先が必要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
PYTHON=/home/robo25/theta-env/bin/python3
SOURCE=recordings/2026-11-10/driver_motion_171250_intake_r01/driver_motion_live_20261110_171250
EVIDENCE=recordings/2026-11-10/driver_motion_171250_intake_r01/motion_withheld_20261110_171250
RESULT=Experimental_results/2026-11-10/driver_motion_171250_review_r01

"$PYTHON" src/report_driver_motion_logs.py --input-dir "$SOURCE" --output-dir "$RESULT/full_run_report_r02"
"$PYTHON" "$RESULT/audit.py" --input-dir "$SOURCE" --report-dir "$RESULT/full_run_report_r02" \
  --evidence-dir "$EVIDENCE" --output "$RESULT/audit_r03.json"
"$PYTHON" "$RESULT/analyze_evidence.py" --input-dir "$SOURCE" --evidence-dir "$EVIDENCE" \
  --output-dir "$RESULT/evidence_replay_r02"
```

今回の検証は既存のlog/evidence validator、全件の整合性検査、8枚の完全なbaseline再現、元ファイル／画素SHA不変確認。既存の成功済み72テストは再実行せず利用した。本作業でruntimeコード・距離判定・操縦を変更せず、実機を起動せず、commit/pushも行っていない。
