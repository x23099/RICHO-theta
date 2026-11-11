# 比較専用workerを接続し、実カメラ前の検証を完了

2026-11-11。**前日の参照管理を、既定OFFの非同期workerとして運転用主測距の後段へ接続した。** 関連198テストと、保存8画像の実子プロセス／pipe再生を確認した。次はGPU PCへの反映と、現在のカメラ接続でのnative画像1枚の明示保存。追加の校正撮影・床マーカー・距離実測は今回の開始条件ではない。

**主測距の画面は現行のまま。改良候補は比較JSONL／状態ファイルだけに出し、運転画面・主測距IPC・ROS・FFBへ返さない。** 新しい比較GUIは未実装であり、主画面の距離が改良候補に切り替わると期待しない。

## 実装

|ファイル|役割|
|---|---|
|[driver_guarded_comparison.py](../../../src/driver_guarded_comparison.py)|容量1の最新slot、専用daemon、参照イベント・比較・PNG・ログの所有者|
|[manage_guarded_comparison.py](../../../src/manage_guarded_comparison.py)|端末からのpin／load／invalidate要求、鮮度を確認するstatus読取り|
|[cone_guarded_stream_comparison.py](../../../src/cone_guarded_stream_comparison.py)|前日の同接続照合・失効。今回はload完了前に受信済みの待ちframeも数値に使わないよう、受信時刻条件を追加|
|[driver_motion_process.py](../../../src/driver_motion_process.py)|主結果のpipe送信後に元frame＋不変のJSONL文字列をnon-blockingで渡す|
|[driver_motion_bridge.py](../../../src/driver_motion_bridge.py)|`--motion-comparison-dir`をGPU子へ転送。既定は比較なし|

RTC／操縦threadに比較・PNG処理・ファイル読込みを入れていない。GPU子内の別threadで動くためCPU／GIL／メモリ帯域は共有し、実GPUでの追加負荷は未確認。YOLOの再推論や別のカメラ取得を増やさず、同じ画像と保存済みの主検出枠を利用する。

比較例外・保存失敗・上限到達は比較側だけを無効化する。既存の主結果・保留判定を書き換えない。終了待ちは最大0.25秒で未停止を明示し、比較終了が機体停止の代替になる設計ではない。

## 参照の順序と失効

1. 明示pin要求後の処理対象1枚を、無加工1280×720 PNG＋同名JSONとして保存し、その元画素digestを同じworkerで保持する。
2. その画像から読んだ天板境界を`reference.json`へ用意し、明示loadを要求する。
3. 同session/frameのPNG SHAと復号画素がpinに一致することを検査する。旧sessionのファイルを指定したりsessionだけを書き換えても、対応するpinがなければ使えない。
4. load完了より後に受信したframeだけ比較する。参照を過去画像へ遡及適用しない。
5. 入力間隔・鮮度が0.5秒超、再接続、不正・比較失敗、明示invalidateで参照／数値を失効する。再pin／loadが必要になる場合があり、旧値を保持しない。

受信器を再起動するとsessionが変わる。**pin画像を提出した後、loadするまで同じ接続を維持する。** 過去frame14604の参照を、今回の実カメラsessionへ転用しない。

## 出力と上限

`--motion-comparison-dir`は新規のrepository `recordings/`配下を指定し、主出力・保留画像保存先とは別にする。

|出力|内容|
|---|---|
|`comparison_frames.jsonl`|比較処理したframeの元判定・比較値・世代・元session/frame・未承認flag|
|`comparison_status.json`|状態、最新の有効な比較行、要求結果、drop／保存／容量／終了情報、依存コードSHA|
|`decoded_SESSION_fNNNNNN.png`と同名JSON|明示pin時だけ保存するnative画素と来歴|
|`request.json`|端末コマンドが発行するローカル要求。単調増加IDで同じ要求を繰り返さない|
|`reference.json`|現在sessionのpin画像から明示作成する天板境界参照|

比較ログ64MiB、1行16KiB、明示snapshot最大8枚、要求最大128回。最大1処理中＋最新待ち1枚で、上書きした待ちframeはdropとして記録する。全受信frameの網羅や保存保証数ではない。status更新は約0.1秒間隔（処理／I/O中は遅れる）。消費側も時刻を確認し、古い数値を現在値として示さない。電断耐久性やディスクI/O完了の絶対期限は保証していない。

`physical_metric_verified`、`floor_contact_verified`、`controlling_distance`、`usable_for_ffb`、`published_to_ros`はfalseを維持。天板境界から離れていることは床接地の証明ではなく、固定取付・局所平面床・姿勢補償なしという制約も従来どおり。

## 検証結果

[正式テストsummary](checks_r02/summary.json)、[テストログ](checks_r02/tests.log)、[実pipe再生summary](pipe_replay_r02/summary.json)。r01は状態失効表示・追加3試験より前の記録で保持した。

|検査|結果|
|---|---:|
|関連テスト|198成功、失敗・error・skip 0|
|今回のworker／CLI専用テスト|23件|
|参照管理テスト|26件（前日25＋受信済み待ちframeの拒否1）|
|比較OFF/ONでの主測距の実pipe再生|保存8画像全てで距離・保留理由・主modelが一致|
|比較数値|後続の14922対応画像だけ、1.142471541888944 m、[312,407]|
|参照前／load当該frameへの数値|0件|
|別sessionのload|拒否し旧比較値もなし|
|明示pin画像|1枚、元の復号画素と完全一致|
|OFF/ON両子・I/O／ON比較writer終了|確認済み|
|元入力|解析前後でSHA不変|

遅い比較中の最新slotはframe1→4と処理し、2・3を蓄積しない。比較の例外、ログ／画像／要求上限、ディスク失敗、切断・古い結果、symlink参照、主数値の維持、旧操縦／shell回帰を含む。CLI helpと受信shell構文も成功。

実pipe再生は、8枚の元画素と同frameの保存枠を検証専用predictorへ渡したもの。**新規YOLO推論、カメラ、ROS、RTC待受け、実機操作をしていない。** 再生用session/frameは新しく、原session/frameとの対応をsummaryへ残した。frame14604と同一画素の再生snapshotから、再生専用の新しい参照を作ったのであって、新しい実機sessionへの幾何転用を承認したものではない。実GPU負荷・カメラから画面までの遅延や物理誤差の保証には使わない。

## 再現とGPU PCへの反映

[実カメラの静止確認手順](live_procedure.md)。本日の変更は未commit／未push。Gitを勝手に公開更新せず、[反映パッチ生成](make_patch.py)を用意した。別作業collision_risk.py／test_collision_gradient.py、raw、重み、venvは含めない。GPU PCに直接接続・配布・起動してはいない。

このPCで再現する場合は未使用出力先へ：

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-11/guarded_async_comparison_r01/check.py \
  --output-dir Experimental_results/2026-11-11/guarded_async_comparison_r01/checks_r03

/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-11/guarded_async_comparison_r01/replay.py \
  --input-dir recordings/2026-11-10/driver_motion_171250_intake_r01/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/driver_motion_171250_intake_r01/motion_withheld_20261110_171250 \
  --comparison-dir recordings/2026-11-11/guarded_async_replay_r03 \
  --output-dir Experimental_results/2026-11-11/guarded_async_comparison_r01/pipe_replay_r03
```

rawの比較側画像／ログは`recordings/2026-11-11/guarded_async_replay_r02/`。Git対象外。次のカメラ確認では、現在の取付状態と対応した参照1枚、実YOLO込みの負荷・更新・保留を確認する。ここへ到達するまでの追加撮影は要求していない。
