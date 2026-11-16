# 受信telemetryの任意記録機能

2026-11-16。ユーザーの明示依頼により、**受信処理へ既定OFFの受動記録を実装**。記録は比較・不具合解析の補助で、距離表示やG923接近通知の必須条件ではない。後続依頼でユーザーからGPU反映済みの申告を受領。開始時のローカルHEADはc9534a2（1116v3）、worktree clean。その後[GPUの実受信記録を全件監査](../receiver_telemetry_live_audit_r01/README.md)し、telemetry2,208件・約93.77秒・受理後の記録欠落なし・正常終了・runtime SHA一致を確認済み（末尾拒否1件は原因未確定）。以下の確認手順は実施済み。旧「未commit/未push」は実装完了時点の状態。

## GPU反映後の次の確認：記録だけを10〜20秒

今回の確認は記録の疎通だけで、測距推論・参照load・pin・新しい距離校正は起動しない。追加走行・コーン移動・画面録画は不要。通常受信で使っていたROS/Qt環境のGPU端末を使い、既存受信UIが開いていれば通常終了する。受信を二重起動しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
THETA_UI_NO_VENV=1 python3 src/webrtc_receive_ui.py \
  --cam-width 1280 --cam-height 720 \
  --telemetry-record-dir recordings/2026-11-16/received_telemetry_r01
```

これは受信UIだけを起動する完全なコマンド。`--motion-distance`を付けていないため距離欄が出ないのは正常。既存の測距/guardを改造・解除するのではなく、それらを起動しない独立した記録疎通の確認。通常のnative1280x720送信を接続し、映像を確認して10〜20秒待つ。送信側が前の受信終了で切れていれば、従来の送信コマンドで接続し直す。こちらからIPやdeviceを推測して別設定に変更しない。

機体は停止のまま、ハンドル/ペダル/WASDは操作しない。受信UIを×または受信端末のCtrl+Cで通常終了してから、同じGPUリポジトリの端末で確認・圧縮する。

```bash
python3 -m json.tool recordings/2026-11-16/received_telemetry_r01/telemetry_recording_summary.json
test ! -e /home/hsr/Downloads/received_telemetry_20261116_r01.tar.xz && tar -cJf /home/hsr/Downloads/received_telemetry_20261116_r01.tar.xz -C recordings/2026-11-16 received_telemetry_r01
```

生成したarchiveを提出する。summaryが正常でもtelemetry0件の場合は受信確認未完了なので、中身とsession/event_kindをこちらで確認する。受信値0を実測停止と認定したり、この試験を測距との同時刻性検証に数えたりしない。

既存directory/archive名がある場合は削除・上書きせず、上記全箇所のr01を新しいr02等へ統一する。起動失敗、summary不在、圧縮できない場合は、その端末出力を共有する。引数を追加しただけなので、この手順のための追加コード反映や旧patch適用は不要。

## 実装

- [driver_telemetry_recording.py](../../../src/driver_telemetry_recording.py): 固定スカラー抽出、有界queue、専用writer、上限/失敗/終了処理。
- [webrtc_receive_ui.py](../../../src/webrtc_receive_ui.py): opt-in CLI、接続session共有、JSON解析前のmonotonic受信時刻、callbackから観測器へ投入、起動/停止の接続。
- 送信側、操縦/ROS publish、距離計算、校正、表示採否、FFBコードは未変更。先行実測ログの計算/表示判定12ソースも全バイト不変。

受信callbackでは5個の既知スカラーだけをコピーして `put_nowait` する。JSON化・mkdir/open/flush等は別threadで行う。保存待ち・推論・画像保存をcallbackへ追加しない。queueが満杯、writerの短いlockと競合、上限到達なら記録が欠落/停止するが、UIへの元辞書通知と操縦channelは維持する。欠落はsummaryのcounterで見える。RTC側は単一producerを想定し、busy counterは診断情報で安全保証には使用しない。

## 保存内容と分からないこと

専用directoryへ次の3ファイルを新規作成する。

| ファイル | 内容 |
|---|---|
| `received_telemetry.jsonl` | peer開始/終了、接続session、受信順序、受信/保存時刻、速度・ヨー等の受信値 |
| `telemetry_recording_metadata.json` | process内受信時計ID、時計の意味、受信module/UIソースSHA、非制御属性 |
| `telemetry_recording_summary.json` | 正常/上限/エラー、保存件数、queue/lock/drop、破棄、bytes、終了状態 |

レコードschemaは `driver_received_telemetry_v1`。保存対象は `linear_x→linear_mps`、`angular_z→angular_radps`、`speed_mps`、`imu_yaw_rate→imu_yaw_rate_radps`、`timestamp→sender_wall_time_ms` のみ。SDP、IP、任意のmessage内容、画像、未知の辞書項目は保存しない。欠落はnull。bool/文字列/非有限/過大値等はnullと `invalid_fields` へ分類し、0へ補わない。受信した0もそのまま保存するが、それだけで「実測停止」と認定しない。

現senderには元計測metadataがないため、`source_kind=legacy_telemetry`、`source_clock_id / source_stamp_ns / motion_frame_id / measurement_valid=null`、`source_freshness_verified=false` を維持する。messageに同名の任意項目があっても対応版のschemaがないため信用しない。送信wall timestampを元ROS計測時刻に置き換えない。

接続sessionは同時稼働する測距tapと同じofferのUUID。再接続は別UUIDで、旧peer callbackの遅着も旧sessionのまま記録する。receiver_clock_idは**受信processの識別子**でOS boot IDや時刻同期証明ではない。映像の `source_time_sec` とtelemetryの `received_at_sec` は同じ受信process内 `time.monotonic()` だが、いずれも露光/元odometry時刻ではない。時刻付き実測の結合やG923への採用は、この記録追加だけでは完成しない。

先行 `offline_measured_motion_record_v1` と別schemaであり、既存オフラインjoinerやライブFFBへ自動変換していない。`usable_for_ffb=false / published_to_ros=false / controlling_distance=false` を保持。

## 上限と失敗時

既定はJSONL 16MiB・100,000レコード・queue128件。起動オプションで変更可能（MiB1〜1024、件数1〜1,000,000、queue1〜4096）。1行は16KiB以内。metadata/summaryの小さなJSONはJSONL容量上限とは別。directoryはこのリポジトリの `recordings/` 配下の**未使用名**に限定し、既存ファイル/実験directoryへの追記・上書きを拒否する。

writerエラー/容量上限はwriter側で警告して記録だけを停止する。UI終了はstop要求だけ、app終了のfinallyで最大2秒の有限待機。遅いディスクで完了しなければ `shutdown_complete=false` を返し警告する。強制killや機体停止指令は送らない。異常終了ではsummary未作成/ログ途中行もあり得るため、その状態を正常完了とみなさない。書込み失敗時はJSONLの最終行が部分書込みの可能性もある。

summaryの通常完了は `state=closed / error=null / writer_done=true / shutdown_complete=true`。欠落なく保存できたかは `queue_drops / busy_drops / discarded_pending` と、`queued=written+discarded_pending`（終了時pending/in_flightが0）も確認する。`offered` はlock取得できた投入呼出し数で、`busy_drops` は別計数。summaryファイルはwriter終了時点、停止後にcallbackが来た場合の後続rejected等は終了時snapshotと差が出ることがある。全接続期間の完全記録を無条件には保証しない。

## ローカル検証

根拠: [fake peerの記録結果](results_r01/audit.json)、[テスト記録](verification.json)。実サーバ/ROS/Qt/GPUを起動せず、受信classのASTをfake peerと接続して**実callbackの本体**を実行した。

| 検証 | 結果 |
|---|---:|
| 新規テスト | 記録22＋既存callbackの観測追加限定AST1 |
| 関連suite | 170成功、0失敗 |
| 合成telemetry UI通知と保存 | 25/25同一件数 |
| peer開始/終了を含む保存 | 29/29、drop0 |
| session | 2、旧peer遅着の付替えなし |
| 合成通常ログ | 19,418 bytes、正常close |
| 合成通常投入の観測最大時間 | 約0.166ms未満 |

投入時間は小規模な合成試験の観測で、実GPU/通信環境の性能保証ではない。別単体/統合試験では遅いwriterでqueueを溢れさせても100/100のUI通知を維持し、ディスクエラー・壊れた観測器・無効値・上限・thread開始失敗・有限close・既存結果の非上書き等を確認した。

旧telemetry callbackの固定AST hashは、新しい**受信時刻の取得と任意観測呼出しの正確な2箇所だけ**を除去すると元hashに一致。baseline hashの単なる更新ではない。操縦ROS/keyboard/control送信・senderの旧固定ASTも一致。先行170/168/127/82等のsuiteには重複があるので加算しない。

合成生ログは `recordings/2026-11-16/receiver_telemetry_recording_synthetic_r01/`（Git対象外）。本物の実機走行データではない。過去の正式監査に保存された旧UIのSHAは当時の版を指すため、今回の新UIで古いmanifestを書き換えない。

## GPU PCで使うとき

**この変更をGit等でGPUへ反映してから**使用する。現在は未commit/未pushなので、現状のPullだけでは新機能は届かない。sender側の変更や旧patchの再適用は不要。

カメラなしの構文確認（GPU PC用、実受信は起動しない）:

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 -m py_compile src/driver_telemetry_recording.py src/webrtc_receive_ui.py
```

次の通常受信時に、**既存の受信起動コマンドの末尾へ**次の引数を追加する。下記は単独実行するコマンドではない。既存のweights/profile/比較先/測距オプション等は維持する。shellの `--motion-distance` 分岐は追加引数をUIへ渡せるが、legacy分岐は追加引数を転送しないため、その場合はPython UI起動を使う。

```text
--telemetry-record-dir recordings/2026-11-16/received_telemetry_r01
```

同名directoryが既にあるなら削除せずr02等の新しい名前を使う。保存上限の指定は必要な場合だけ `--telemetry-record-max-mib` / `--telemetry-record-max-records` / `--telemetry-record-queue-size` を追加する。オプションを付けなければ記録なしの従来動作。

記録確認だけを目的に追加のコーン撮影・実測・走行・画面録画は要求しない。通常受信でtelemetryが届く短い区間を記録し、UIを正常終了してから確認する。測距表示も起動する場合の現session参照/pin手順は従来どおりで、古い参照を新sessionへ流用しない。

```bash
python3 -m json.tool recordings/2026-11-16/received_telemetry_r01/telemetry_recording_summary.json
```

3ファイルが提出物。終了済みdirectoryを指定して新しいarchive名で圧縮する例（既存archiveへの上書き防止付き）:

```bash
test ! -e /home/hsr/Downloads/received_telemetry_20261116_r01.tar.xz && tar -cJf /home/hsr/Downloads/received_telemetry_20261116_r01.tar.xz -C recordings/2026-11-16 received_telemetry_r01
```

実機での記録・負荷確認は未実施。記録のために実受信やROS/機体/G923をこちらから起動していない。元計測時刻が必要な運動同期は後続のsender metadata等の作業で、今回の受信記録と区別する。

## このPCで再現

未使用出力名にする。fake peerのみで実ネットワークは開かない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/receiver_telemetry_recording_r01/check.py \
  --output-dir Experimental_results/2026-11-16/receiver_telemetry_recording_r01/results_r02 \
  --raw-output-dir recordings/2026-11-16/receiver_telemetry_recording_synthetic_r02

env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_driver_telemetry_recording.py tests/test_driver_motion_integration.py \
  tests/test_driver_motion_shutdown.py tests/test_driver_motion_presentation.py \
  tests/test_driver_motion_time_join.py tests/test_driver_motion_handoff.py \
  tests/test_driver_motion_spatial.py tests/test_driver_body_display_guard.py \
  tests/test_driver_motion_bridge.py tests/test_body_display_range_audit.py
```
