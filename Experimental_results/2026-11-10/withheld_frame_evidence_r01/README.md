# 保留frameの未展開画像保存（既定OFF）

2026-11-10。**次回の通常走行で、輪郭境界による保留frameの元画素と判定JSONを同じ組で保存できるようにした。** 追加の校正撮影や手動Sキー保存を前提にしない。機能は既定OFFで、明示的な保存先指定が必要。

このPCで実装・オフライン検証済み。**GPU PCへのコード反映、実カメラでの有効化、実走行の追加負荷確認はまだ行っていない。** Git commit/pushも今回の依頼には含まれず未実施。下記コマンドは、今回のコードをGPU PCへ反映した後に使うための手順。

## 何を保存するか

- 対象は `distance_available=false` かつ `reason=colour_contour_reaches_roi_edge` の測距結果。今回調べている左端・下端切れに限定する。`no_candidate`、曖昧な複数物体、初期化遅延等は保存しない。
- 判定に実際に使った1280×720・dual fisheyeの復号BGR画像をPNGで保存。元画角・画素を維持し、展開、注釈、切抜き、リサイズ、鏡像化、色・明るさ補正をしない。PNGの圧縮は可逆。センサの無圧縮RAWや、運転UIのスクリーンショットではない。
- 同じsession/frame、受信・media時刻、完全な測距結果、元ログ行SHA、PNG SHA、復号画素SHAをJSONへ記録する。
- 保存は**worker側の保留**であり、その結果が画面に表示された証明ではない。表示採用の対応には既存の`motion_bridge_events.jsonl`を使う。

## 有効化の手順（GPU PC、コード反映後）

普段の運転UIを動かしているROS環境を使う。既存の受信器と二重起動せず、機体を従来の手段で停止してから、普段の終了・再接続手順で切り替える。今回の機能をこちらから実機で起動してはいない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"

RUN_TAG="$(date +%Y%m%d_%H%M%S)"
MOTION_OUT="Experimental_results/2026-11-10/driver_motion_live_${RUN_TAG}"
EVIDENCE_DIR="recordings/2026-11-10/motion_withheld_${RUN_TAG}"

bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python "$THETA_DISTANCE_PYTHON" \
  --motion-weights "$HOME/Downloads/cone_distance_v03.pt" \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir "$MOTION_OUT" \
  --motion-experimental-rigid-mount \
  --motion-withheld-evidence-dir "$EVIDENCE_DIR"
```

追加したのは最後の `--motion-withheld-evidence-dir`。外せば従来どおりPNGを保存しない。送信側は現在の `--motion-native` コマンドのまま変更不要。L／S等の追加操作も不要で、運転用のキーを測距操作として押す必要はない。

今回はruntime側の `src/driver_motion_bridge.py`・`src/driver_motion_process.py`・新規 `src/driver_withheld_evidence.py` を一緒に反映する必要がある。オフライン検証コマンドには新規 `src/verify_driver_withheld_evidence.py` と既存の今回追加済み `src/report_driver_motion_logs.py` も必要。部分的なコピーで新しいimport先を欠かさない。

## 上限・取りこぼし

|設定|既定値|指定できる範囲|
|---|---:|---|
|`--motion-withheld-evidence-max-frames`|40組|1～100組|
|`--motion-withheld-evidence-max-mib`|128MiB|1～256MiB（PNG＋sidecar JSONの合計）|
|`--motion-withheld-evidence-interval-sec`|1秒|0.1～60秒（採択したsource時刻の間隔）|

画像・sidecarのほか、完了索引と状態JSONに小さい固定上限内のmetadata領域を使う。状態更新は一時ファイル＋置換なので短時間の一時領域も必要。元の測距JSONLの容量はこの画像保存上限には含まれない。

保存中1枚＋待ち1枚まで。待ち満杯・間隔・件数上限では即dropする。容量はPNG化後に確認し、上限を超える組はファイルへ出力しない。最大40組は保存保証数ではなく上限で、件数枠はキューへの採択時に消費する。

最初に来た対象frameから選ぶため、静止した保留が長く続くと、その区間で上限に達することがある。全保留の網羅や走行区間への自動選別はしない。上限に達しても距離推定・操縦は停止しない。別の撮影状態を記録したい場合は、次の通常実行で新しい日時のフォルダを指定する。既存フォルダは上書きしない。

## 保存物と後で持ってくるもの

画像は `recordings/.../motion_withheld_日時/`、従来の2つの測距ログは `Experimental_results/.../driver_motion_live_日時/` に分ける。画像の自動Git追加や自動アップロードはしない。

|ファイル|内容|
|---|---|
|`decoded_SESSION_fNNNNNN.png`|無加工1280×720の元frame|
|同じ名前の`.json`|元の判定全体、時刻、PNG／画素／ログ行のSHA|
|`evidence_index.jsonl`|PNG＋JSONの保存完了索引。ここにある組だけが証拠|
|`evidence_status.json`|保存・drop・容量・error・終了状態|

従来の `motion_distance_frames.jsonl` と `motion_bridge_events.jsonl` は引き続きMOTION_OUT側に保存する。終了summaryの `image_files_written` は保存ON時にはUI側で確認できないため`null`とし、実際の保存件数を偽らない。保存側statusとindexを確認する。

実験が終わったら、従来の方法で機体を停止してからUIを終了する。Q／ウィンドウを閉じることは独立した機体停止の代わりにはしない。

同じターミナルであれば、保存済みの2フォルダをまとめて渡せる：

```bash
tar -cJf "recordings/2026-11-10/motion_evidence_${RUN_TAG}.tar.xz" \
  "$EVIDENCE_DIR" "$MOTION_OUT"
```

これは手順例で、今回こちらでは圧縮・転送していない。別ターミナルでは変数が保持されないため、実際のフォルダ名へ置き換える。PNGだけでなくsidecar・index・2ログが同じ実行の組として必要。

## 保存結果の検証

機体停止・UI終了後、同じターミナルなら：

```bash
"$THETA_DISTANCE_PYTHON" src/verify_driver_withheld_evidence.py \
  --input-dir "$EVIDENCE_DIR" \
  --source-log "$MOTION_OUT/motion_distance_frames.jsonl"
```

PNGとsidecarのSHA、復号後の全BGR画素SHA、寸法、session/frame、保留理由、元ログの完全な行SHAとJSON内容を検査する。sidecarに書かれた絶対パスを勝手に開かず、`--source-log`で明示した既存ファイルだけを照合する。転送後にPCのパスが変わっても、キーとhashで対応できる。

- `verified_pairs`：検証できた組数。0組は検証成功例ではなく未収集。
- `source_log_checked=true`、`source_log_matched_pairs`：指定ログと対応した組数。
- `capture_shutdown_complete=true`：保存側の終了情報と件数・容量が合い、未完了の索引末尾や孤立ファイルもない状態。

強制終了やディスク失敗で`.part`・索引外のファイルが残ることがある。自動削除せず、検証済みの組とは区別する。索引の最後の途中行は完了に数えない。statusが更新できないディスク障害では古い状態が残り得るため、フォルダができたことだけを保存成功とは扱わない。

## 非同期化と障害隔離

測距結果を既存pipeへ返してから、保存対象をnon-blockingで渡す。画像参照と不変の元ログ文字列を渡し、PNG化・コピー・hash・JSON化・ファイルI/Oは専用保存スレッドで行う。RTC受信／運転UIでは実行しない。

保存初期化・encoder・ファイル書込みの失敗は保存機能だけを止め、測距結果を変更・再送しない。保存有効時の子SIGTERMでは0.25秒まで終了待ちを試み、停止通知の重複を終了中は無視する。保存I/Oが止まらない場合は未完了として扱い、距離／操縦を待たせない。PNG＋JSONの両方ができて索引へflushされた組だけを完了として数える。fsyncや電断耐久性は保証していない。

CPU・メモリ帯域・ディスクはGPU PCで共有するため、非同期化しても**実機の負荷・操縦／映像遅延が増えない保証ではない**。今回の検証ではその実測はしていない。速度指令・ブレーキ・FFBへの距離接続も行っていない。

## 検証結果

正式な[72テスト・起動help／shell構文](checks_r01/summary.json)、[テストログ](checks_r01/tests.log)、[実子プロセスでの保存枠再生](verification_r02/summary.json)を参照。

|検査|結果|限界|
|---|---|---|
|新規保存・検証・CLI・障害・終了テスト|24成功|合成画素／偽predictor、実機ではない|
|既存driver関連回帰|48成功、合計72、失敗・error・skip 0|全プロジェクト・実機安全の認定ではない|
|既存の操縦／ROS／DataChannel主要処理のAST、旧shell本体|既存の固定hashと一致|負荷による遅延の測定ではない|
|保存OFF|従来の測距ログのみ、PNGなし|ソフトウェア検査|
|PNGの全復号BGR画素、同じframeの判定全体と元ログ行|一致|接地や距離の正解ではない|
|遅い保存／満杯／上限／encoder・ディスク・初期化失敗|drop／保存だけ停止、結果返却維持|実ディスク枯渇を起こしてはいない|
|過去10画像＋保存YOLO枠、実際のworker main・pipeで保存ON|距離／保留理由10/10一致、数値3件|新しいYOLO推論や走行ではない|
|同再生の保留7件|PNG＋JSON7組、全て元ログと照合、終了完了|過去画像を再保存したもの|
|child終了|exitcode 0、writer／IO thread終了|テスト環境の正常終了|

初回`verification_r01`では重複SIGTERMが保存終了を中断した。7組の内容自体は照合できたが、capture終了は未完了だったため合格とはしなかった。終了中SIGTERMの扱いを修正し、専用テストを追加した後のr02を正式結果とする。途中資料は保持し、成功結果に書き換えていない。

再生で作ったPNGは`recordings/2026-11-10/withheld_evidence_offline_r02/`にローカル保存。新しい撮影画像ではなく、`verification_r02/replay_identity.json`で元session/frameと再生用session/frameを区別する。raw画像と大容量の元録画はGitへ追加しない。

## 再現

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-10/withheld_frame_evidence_r01/check_tests.py \
  --output-dir Experimental_results/2026-11-10/withheld_frame_evidence_r01/checks_r02

/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-10/withheld_frame_evidence_r01/verify.py \
  --output-dir Experimental_results/2026-11-10/withheld_frame_evidence_r01/verification_r03 \
  --evidence-dir recordings/2026-11-10/withheld_evidence_offline_r03
```

未使用の出力先が必要。cached workerへのpredictor差替えはこの明示的な検証スクリプト内だけで、運転コマンドへCPU／保存枠fallbackを追加していない。
