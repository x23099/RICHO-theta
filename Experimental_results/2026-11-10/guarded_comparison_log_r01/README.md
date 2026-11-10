# 正式表示を変えず、保存画像から比較専用ログを作る

2026-11-10。**自動保存画像・判定JSON・元ログを読み取り、別フォルダへ比較JSONLを作る独立コマンドを追加した。** 提出済み8組で実行済みで、8組のbaselineを再現し、候補値は以前と同じ14922の1組だけに残った。

**これは録画後の再計算。リアルタイムの比較表示・距離の正式表示への反映ではない。** 受信UI／測距workerにimportやオプションを追加せず、カメラ・GPU推論・ROS・操縦・FFBを起動しない。録画中に起動して終了まで待つことはできるが、フレームごとの逐次比較ではない。

## 実装と使う入力

新コマンド: [run_guarded_recording_comparison.py](../../../src/run_guarded_recording_comparison.py)。既存の[統合候補](../guarded_lower_edge_shadow_r01/README.md)と保存検証器を利用する。

|入力|用途|
|---|---|
|`--input-dir`|同じ実行の`motion_distance_frames.jsonl`、`motion_profile_used.json`、`motion_engine_summary.json`|
|`--evidence-dir`|同じ実行の自動保存PNG／sidecar／index／status|
|`--reference`|同sessionの天板境界参照JSON|
|`--output-dir`|上2入力フォルダとは別の、新規出力先|

1. 自動保存writerの終了と `shutdown_complete=true` を待つ／確認する。
2. PNG・sidecar・全復号画素・元ログの完全行SHAと内容・session/frameを既存検証器で照合する。
3. **参照のsession/frame/PNG SHAが、今回のindexと元ログで検証された1組に対応すること**を要求。参照JSONのsessionを書き換えただけでは通らない。
4. source engineのprofile／config／metricを照合し、同じ画像・保存検出枠で元観測と元の距離判定を再現する。
5. 自己領域棄却＋下端半画素の候補を別に計算し、入力が途中で変わっていないことを再hashしてからログを公開する。

比較後の値をUI、IPC、ROS、速度指令へ返す経路は存在しない。重みファイルや新しいYOLO推論も不要。元画像のリサイズ・注釈・切抜き・色変換の保存は行わず、比較フォルダにはPNGを出力しない。

### 参照の無効化と失敗

- 参照画像が同じ保存indexにない、session/frame/hash不一致、profile/config不一致、baseline再現不一致ならjobを失敗にし、完成した比較JSONLを公開しない。
- 複数sessionが同じ保存フォルダに入っていても、参照と異なるsessionの行は比較距離なし・`withheld_reference_session_mismatch`とする。
- 新sessionへ過去の参照を自動転用しない。カメラ／天板の相対位置が実際に変わらなかったことをファイル対応だけで認定するわけでもない。
- 不完全なindex末尾・孤立ファイル・保存失敗・処理中の入力変更も拒否する。wait timeoutやCtrl+Cではjob失敗／未完了で、距離取得側を停止しない。
- 入力を上書きせず、既存出力フォルダも拒否する。ディスク障害では`.part`が残り得るため自動削除しない。`comparison_summary.json`が`state=complete`で、ログSHAと件数が対応する場合だけ完成結果として扱う。

## このPCで実行済みの結果

[実行summary](recorded_run_r01/comparison_summary.json)、[比較8行](recorded_run_r01/comparison_frames.jsonl)。ローカル元データは `recordings/2026-11-10/driver_motion_171250_intake_r01/`。

|検査|結果|
|---|---:|
|保存PNG／元ログ照合|8／8組|
|元の支持観測・距離判定の再現|8／8組|
|比較候補の数値|1組（frame14922、1.142471541888944 m）|
|手が写る6861、天板に隠れる5枚、複数方向の接触14604|全て比較でも保留|
|正式表示・操縦処理の変更|なし|
|元画像／元ログへの書込み|なし|

天板参照frame14604より前の6画像には `reference_used_posthoc=true` を記録した。後の参照で過去画像を再計算したもので、当時その参照を使ってリアルタイムに測れたという証拠にはしない。数値が出た14922は参照frameより後だが、今回の結果自体はやはり録画後の再計算。

この8組は保存間引き後のサンプルであり、全16,929行・全78保留の元画像を再計算したことにはならない。距離の実測誤差、床接地、姿勢補償は未認定。

## 実行方法

### 同じ提出物で再現する場合（このPC）

以下の実行は既に別出力`recorded_run_r01`で完了している。再実行する場合は未使用の出力先にする。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 src/run_guarded_recording_comparison.py \
  --input-dir recordings/2026-11-10/driver_motion_171250_intake_r01/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/driver_motion_171250_intake_r01/motion_withheld_20261110_171250 \
  --reference Experimental_results/2026-11-10/self_body_boundary_shadow_r01/reference.json \
  --output-dir Experimental_results/2026-11-10/guarded_comparison_log_r01/recorded_run_r02
```

### GPU PCで同じ17:12実行を使う場合

**追記：ユーザーによるGPU PCでの実行は完了し、[提出結果の一致を確認済み](../guarded_gpu_result_audit_r01/README.md)。** 同じ操作の繰返しは不要。以下は実行済み手順の保存であり、改良候補をリアルタイム表示へ反映したわけではない。

初回は先に同じリポジトリの更新が必要。新規の`run_guarded_recording_comparison.py`、`cone_guarded_lower_edge_shadow.py`、`cone_self_body_shadow.py`と、既存のbbox比較・幾何・保存検証の依存をまとめて揃える。単独スクリプトだけをコピーしない。

その後、元の保存先が残っているなら：

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"

"$THETA_DISTANCE_PYTHON" src/run_guarded_recording_comparison.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/motion_withheld_20261110_171250 \
  --reference Experimental_results/2026-11-10/self_body_boundary_shadow_r01/reference.json \
  --output-dir Experimental_results/2026-11-10/guarded_comparison_171250_r01
```

これは**同じ17:12実行専用の参照を使う例**。次回の新sessionへこの参照をそのまま使わない。新しい撮影状態に対応した参照が必要になった場合は、通常受信の自動保存画像から確認する準備を行う。今回、追加の校正撮影や寸法測定は要求しない。

### 録画中に起動し、終了後の比較まで待つ場合

参照がそのsessionに対応していることを前提に、同じコマンドへ例えば `--wait-sec 900 --poll-sec 1` を追加できる。最大15分待ち、writer終了を確認してから一度だけ全組を比較する。対象の保存status以外を繰り返し走査せず、実機や受信器を停止する機能はない。

走行実験の終了時は従来の方法で機体を停止してからUIを終了する。UI終了や比較コマンドの終了は、独立した機体停止の代替ではない。新しい参照がない場合は無理に過去参照を指定せず、比較値なし／job失敗を維持する。

## 出力の読み方

|ファイル|内容|
|---|---|
|`comparison_frames.jsonl`|元session/frame・元判定・比較判定／距離・対応SHA・参照scope・後処理flag|
|`comparison_summary.json`|job状態・件数・比較ログSHA・入力／依存実装SHA・保存検証結果|
|`.part`|失敗・中断時に残り得る未完了の自分の出力。完成データではない|

`original_*` は元の保留判定、`comparison_*` は今回の再計算。`result_kind=post_recording_recalculation_NOT_live_display` と、物理／制御flag=falseを全行に付ける。元記録の距離や撮影時表示を比較値に置き換えない。

source JSONLは最大512MiB、indexは最大256KiB・100組、PNGはnativeサイズに対応した上限、sidecarは約1MiB、比較行は各16KiB・合計2MiBまで。上限を超える入力を勝手に切り詰めない。hashはstreamingだが画像照合・再計算・ディスク読み込みの負荷は発生するので、同じPCの負荷がゼロという保証ではない。画像writer正常終了の確認と、bridge全体の子プロセス終了確認も別である。

## 検証

**新規24テスト成功、失敗・error・skip 0**：[正式summary](checks_r02/summary.json)、[テストログ](checks_r02/tests.log)、[CLI help](checks_r02/help.txt)。通常の比較、自己領域棄却、別session混在、参照／元ログ／設定不一致、baseline不一致、破損PNG、不完全保存、入力の途中変更、上書き・入力下への出力拒否、symlink、待機・中断、ディスク失敗、制御flag非付与、live非importを確認。

初回22テストの後、別sessionが同じ保存フォルダに入るケースと処理中の入力変更を追加し、24テストを正式記録r02とした。実データ8組の実行はコマンド実装が同一のr01を再利用した。既存のdriver80・時系列8・統合候補15テストは依存が変わっていないため再実行しない。

本作業でカメラ・GPUモデル・ROS・RTC待受け・機体は起動せず、正式表示や制御へ接続せず、Git commit/pushも行っていない。現在、ユーザーによる追加の撮影・実機操作は必要ない。
