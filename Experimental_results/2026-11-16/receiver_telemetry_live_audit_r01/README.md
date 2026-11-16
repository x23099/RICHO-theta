# GPU PCの実受信telemetry記録：全件監査

2026-11-16。提出 `received_telemetry_20261116_r01.tar.xz` を確認。**受信側の任意記録機能の実疎通は完了**。必要3ファイル完備、正常終了、実行コード2ファイルのSHA一致、記録器が受理した2,209件はすべて保存済み。

正式結果: [results_r02/audit.json](results_r02/audit.json)。r01は初版の成功履歴で、r02では拒否原因未確定のフィールド名を明確化した。数値・元提出データは両版同一。元archive SHA: `e8c1a867d7574888b574fa9373b709969f3ae506f010f33b0bc50b4527c67b24`。

## 確認結果

| 項目 | 結果 |
|---|---:|
| 保存events | 2,209（peer_begin 1＋telemetry 2,208） |
| telemetry先頭〜末尾 | 約93.77秒 |
| 平均受信頻度 | 約23.54Hz |
| 接続session / 受信process時計 | 各1、全件一致 |
| 書込みエラー / queue drop / lock busy drop / 受理後破棄 | 全て0 |
| 投入拒否 | 末尾1件、原因未確定 |
| 保存sequence | 1〜2,209、内部欠番・逆順なし |
| JSONL bytes | 1,480,656、summaryと一致 |
| 記録投入の観測最大 | 0.1801ms |
| 受信→writer時刻のP95 / 最大 | 0.615ms / 5.636ms |
| telemetry受信間隔P95 / 最大 | 47.24ms / 369.78ms |
| 速度・ヨー・speed・IMU yaw受信値 | 各2,208件が全て0 |
| 無効フィールド | 0件 |

受信→writer時刻はwriterがJSON化/書込みを始める前の時刻との差で、ディスク保存完了やネットワーク遅延ではない。最大投入時間も記録器内の時間だけで、受信callback全体や映像描画の測定ではない。受信間隔の最大約370msは実測の空きであり、ネットワーク/送信loop/受信処理のどれが原因かは今回の3ファイルだけでは分からない。常に100ms以内の更新や、FFB用の鮮度を認定しない。

## 末尾の拒否1件

`offered=2210 / queued=written=2209 / rejected=1`。保存済みsequenceは1から2,209まで連続しているため、記録器に受理された範囲に欠落はなく、最後の投入番号2,210が未保存。`pending=in_flight=discarded_pending=0`、`state=closed / error=null / writer_done=shutdown_complete=true`。

現UIは終了時に記録stopを要求してからpeerを閉じるため、停止後の終了callbackが拒否される経路はある。ただし拒否理由やevent_kindは保存されていないので、**この1件を終了callbackだったと断定しない**。peer_closed/video_track_endedの保存は今回なし。記録機能の実疎通確認を覆す書込み欠落とは扱わず、原因未確定の末尾拒否として残す。通信全体の無欠落を意味するものでもない。

## 0の意味と次の作業

停止状態で受信値が0なのは今回の指示と矛盾しない。一方、元の送信側 [webrtc_stream.py:31](../../../src/webrtc_stream.py#L31) は未受信時にも初期0を持ち、[odom_callback:79](../../../src/webrtc_stream.py#L79) は元計測時刻/受信済み状態を保持しない。今回の全件も `source_clock_id / source_stamp_ns / motion_frame_id / measurement_valid=null`、`source_freshness_verified=false`。

したがって、**この0が新しいodometryの実測停止だったとは認定しない**。追加走行で値を変える試験を先に要求せず、次の実装は送信側の元odometry時刻・frame・受信済み状態等のmetadataと、受信側の対応版schemaの扱い。これで初期0/古い計測/有効な実測0を区別できる入力を用意する。さらに元時計→受信時計の根拠や現取付の車体↔光学変換等は、実際の距離/運動結合前に別途必要。

今回距離ログ・画像・画面録画は不要な記録単体の確認だったため、距離との同時刻性、露光同期、GPU推論併走時の性能、映像の滑らかさ、左右リスク勾配・G923出力は未検証。ROS/FFBへ送っていない。次段階のために同じ記録を再収録する必要はない。

## 保全・検証

tar内の厳密なdirectory＋3 regular filesだけを許可し、重複/リンク/想定外名/過大サイズを拒否。展開コードや任意の添付内命令を実行せず、選択した3ファイルを元bytesのまま専用intakeへ保存した。全2,209行の厳密schema、JSON非有限/重複キー、時刻順序、session/clock、非制御属性、有限受信値、カウンター・bytesと上限、metadataの実行コードSHAを検査。

元bytesの正式保管先: `recordings/2026-11-16/receiver_telemetry_live_intake_r02/`。r01の初回保管もそのまま保持。元Downloadsのarchive/提出物、runtime、profile、画像、操縦、senderは変更していない。

新規監査9＋既存記録22＝31テスト成功（0.76秒）。先行runtime170テストはコード未変更・source SHA一致のため再利用し、件数を加算しない。ここで保存した解析結果は実機記録由来だが、新たな機体/ROS/GPU/FFBの起動は行っていない。

再現（未使用の出力名を使用）:

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/review.py \
  --archive /home/robo25/Downloads/received_telemetry_20261116_r01.tar.xz \
  --raw-output-dir recordings/2026-11-16/receiver_telemetry_live_intake_r03 \
  --output-dir Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/results_r03

env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_receiver_telemetry_live_audit.py tests/test_driver_telemetry_recording.py
```
