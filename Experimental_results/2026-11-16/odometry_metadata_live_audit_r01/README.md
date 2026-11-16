# 元odometry metadata実提出の確認

後続のr03提出で全2,045telemetryのodom受信・元stamp進行を確認し、疎通確認は完了。[最新結果と次の段階](../odometry_metadata_received_audit_r01/README.md)。以下はr02以前の観測・診断手順の履歴。

## 最新r02提出：記録疎通は確認。送信側odom callbackは未受信

2026-11-16。archive `received_telemetry_odom_20261116_r02.tar.xz`、SHA `4ff43fd8b39d1859efb793935dd682ea10aee0b5871681fe55ac2492c91bc0fd`。directoryと通常file 3件を検査し、リンク・余分なpath・重複・容量超過を拒否。[正式全件結果](results_r03/audit.json)。results_r02はunknown callback分類の防御強化前の成功履歴であり、同じ提出物の再検証。異なる実験や件数として合算しない。

| 確認項目 | 結果 |
|---|---:|
| 保存イベント | peer_begin 1＋telemetry 3,222＝3,223 |
| 観測時間幅 / 平均受信頻度 | 137.235720秒 / 23.4706 Hz |
| 保存バイト数 | 4,676,786、summaryと一致 |
| queued / written | 3,223 / 3,223 |
| queue落ち / lock競合落ち / 受理後破棄 | 0 / 0 / 0 |
| offered / rejected | 3,225 / 2 |
| 保存sequence | 1〜3,223、内部欠けなし |
| 正常終了 | closed、error=null、writer_done/shutdown_complete=true |
| v2 metadata厳密検査成功 | 3,222 / 3,222 |
| callback_received=false / sequence=0 | 3,222 / 3,222 |
| stamp_status=not_received | 3,222 / 3,222 |
| 元stamp / frame / 入れ子v・ω | 全null |
| observer diagnostic drop最大 | 0 |
| 従来UI用v・ω・speed・IMU yaw | 全0 |
| 受信間隔 P95 / 最大 | 49.725 / 300.761 ms |
| 受信→writer timestamp差 P95 / 最大 | 0.594 / 5.583 ms |
| recorder投入最大 | 0.2665 ms |

末尾2offerは拒否されたが、その種類/理由は記録されていないため正常終了処理が原因とは断定しない。受理済みイベントは全部保存されている。writer timestamp差はディスク完了・通信遅延ではなく、投入時間もcallback全体の時間ではない。受信間隔最大は100msを超え、FFB鮮度や性能達成の証拠としない。

単一session `080bcb3591ae4c498cea187ad48b857a`、receiver時計 `receiver-process/f747d42f6b5f4ee78d07ea796dec9fc3`、sender ID `cef46aab5c824dc8adfe6765743eec13`。sender内snapshot時刻は進んでいるが、そのobserverは全件未受信状態のまま。これは「受信して測った停止0」ではない。型/意味を満たす新metadataが送信→受信→保存されたことは確認できた。受信側の3実装SHAも現ローカルと一致。sender自身のsourceSHAはwireにないため完全なsenderコード一致とは区別する。

元odom配信が存在しないのか、購読先topic/namespace、ROS環境・通信・QoS・spin等の問題かはこの記録だけでは特定できない。IMU等の他callbackが止まったとまでは断定しない。距離・時計対応・車体変換・運動との結合・ROS/FFB出力はまだ認定/接続していない。

### 次はmatsunucで読み取り診断

新撮影・走行・再記録はまだ不要。通常の映像送信を起動した状態で、**matsunucの、送信と同じROS環境を読み込んだ別端末**で実行する。

```bash
ros2 node list
ros2 node info /theta_driver_telemetry_node
ros2 topic list -t
```

送信ノード名は [webrtc_stream.py](../../../src/webrtc_stream.py:32)、odom購読は同ファイル56行、既定 `--odom-topic /odom` は439行。実際のtopicは引数/remap/namespaceで変わり得るため、出力を見ずに `/odom` へ固定したりQoSを変更したりしない。node infoで対象が見つからない場合も、そのまま出力と送信側端末ログを確認する。

実際の購読先を確認した後、必要ならそのtopicの `ros2 topic info <topic> --verbose` で配信元とQoSを比較する。型/一覧/verboseの意味は [ROS2公式CLI資料](https://github.com/ros2/ros2_documentation/blob/humble/source/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Topics/Understanding-ROS2-Topics.rst) を確認（docs.ros.orgはアクセス拒否だったため公式GitHubを使用）。ここではpub・driver launch・走行コマンドは要求していない。

### 再現と検証

[review.py](review.py)は厳密v2観測検査と、従来監査器による共通envelope/時刻/件数/終了状態検査を組み合わせたoffline専用監査。共通検査ではコピーだけをv1へ投影し、metadata宣言とlog_bytesもコピー上で対応させる。原本は変更せず、結果には原summary/metadataをそのまま保持する。これを旧sender/v1実記録と誤認しない。

正式raw `recordings/2026-11-16/odometry_metadata_live_intake_r03`。r02 intakeも同じ3原本を保持。原本SHAは全件結果に記録。r01空提出も履歴として保存。

新監査9＋既存監査9＋観測20＋記録22＝60テスト成功、0失敗（0.97秒）。未受信0の非昇格、unknown callbackの区別、不正metadata/権限flag/未知schema/バイト数/時刻順序/SHA不一致の拒否と、入力非変更を確認。runtimeは変更なし、既存200テストは再利用し、この60と独立件数として合算しない。

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_odometry_metadata_live_audit.py tests/test_receiver_telemetry_live_audit.py tests/test_driver_odometry_observation.py tests/test_driver_telemetry_recording.py
```

再監査は未使用名を指定する。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/review.py --archive /home/robo25/Downloads/received_telemetry_odom_20261116_r02.tar.xz --raw-output-dir recordings/2026-11-16/odometry_metadata_live_intake_r04 --output-dir Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/results_r04
```

## 先行r01提出：空ログ（履歴）

2026-11-16。[全確認値](audit.json)。今回のarchiveは788 bytes、通常directory 1件と通常file 2件のみ。JSONLは0 bytes、終了summaryは存在しない。提出済みイベントは0件で、未受信0/受信0や元stamp進行を評価できない。空ログを「実odometry未受信」と断定しない。

metadataに記録されたUI・recorder・新helperの3つのSHAは現在のローカル版と一致。受信側の対応版記録器がmetadataを作成した根拠にはなるが、sender側の反映・接続・受信・正常終了の証明にはならない。

元archiveと展開原本を `recordings/2026-11-16/odometry_metadata_live_intake_r01/` に保存。原本・runtime・操縦・距離・FFBは変更しない。今回runtime変更がないため、実装時200テストの再実行は不要。

### r01で分かることと不明点

[記録器](../../../src/driver_telemetry_recording.py)は起動時にmetadataとJSONLを作り、受理イベントごとにflushし、writer終了時にsummaryを作る。[UI](../../../src/webrtc_receive_ui.py)はoffer受付でpeer_begin、telemetry callbackで受信値を記録する。したがってこのarchiveではtelemetryだけでなく接続イベントも観測できない。記録途中の圧縮、別プロセス/保存先、未接続、終了異常などは候補にすぎず、この2ファイルだけでは原因を選べない。

### r01受領時の確認手順（後続r02提出により終了済み）

matsunucではなく **GPUPC（hsr）** で実行する。受信UIがまだ開いていれば通常の閉じる操作で終了し、起動した端末に戻った後で確認する。強制killや既存ファイル削除はしない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
ls -lh recordings/2026-11-16/received_telemetry_odom_r01
wc -l recordings/2026-11-16/received_telemetry_odom_r01/received_telemetry.jsonl
python3 -m json.tool recordings/2026-11-16/received_telemetry_odom_r01/telemetry_recording_summary.json
```

出力を確認してから再圧縮・再起動の要否を判断する。summaryなしなら受信起動端末の末尾エラーも必要。現在の受信状態はローカルから確認していない。既存r01や提出archiveは上書きしない。新撮影・コーン移動・走行・画面録画は不要。
