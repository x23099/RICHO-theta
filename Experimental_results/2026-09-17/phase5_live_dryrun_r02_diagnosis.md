# 2026-09-17 Phase 5 実カメラ・模擬ODOM・PC間 dry-run 再試験 r02 診断

## 結論

**カメラからハンコン接続PCまでのFFB指令伝送は確認できたが、adapterの受理はFAIL。** カメラ側のWARNING active指令８件は、rosbag側でも同一sequenceの８件として記録された。さらに各指令に対応するstatusも記録されたため、前回r01の「警告区間をbagが取り逃がした」という未判定は解消した。一方、８件のstatusはすべて`invalid_request:future_message`、`action=stop`、`command_active=false`、`output_active=false`であり、FFBは適用されていない。

加えて、bagのstatus全3,322件が`output_mode=disabled`だった。今回意図した`dry_run`としては記録されていない。どの起動コマンドまたは別プロセスが原因かはbagだけでは特定できず、ハンコン接続PCの起動ログと実行中プロセスの確認が必要。**時計差とadapter modeの２点を解消するまでhardware試験に進まない。**

## 入力と方法

| 入力 | 内容 | SHA-256 |
|---|---|---|
| `/home/robo25/Downloads/202609171524.tar.xz` | Kobuki PCのr02カメラ録画、CSV、３動画 | `52372786e82bdd3f7042fc6d26c3b8b39dae289be06f7f9d0101e0e24144e326` |
| `/home/robo25/Downloads/202609171501.tar.xz` | ハンコン接続PCのrosbag。内部名は`phase5_live_dryrun_r0`だが、時刻とsequenceがr02録画に一致 | `0cf56d4201387bc4d0ca16afc30e25319ea5c62301b0e5bf89c52d2f83b405af` |

カメラ録画にはリポジトリの[`analyze_field_recording.py`](../../src/analyze_field_recording.py)をv7設定で実行し、[一括解析レポート](phase5_live_dryrun_r02_analysis/analysis_report.md)とCSVを保存した。bagはSQLite3内のROS 2 CDRを、[解析スクリプト](analyze_phase5_bag_r02.py)で`oit_interfaces`のメッセージ定義に従い復元した。[bag集計JSON](phase5_live_dryrun_r02_bag_summary.json)と[全イベントCSV](phase5_live_dryrun_r02_events.csv)を保存した。rosbagの記録時刻とメッセージのheader時刻を区別して比較した。

## カメラ側

| 指標 | 結果 |
|---|---:|
| セッション | `phase5_camera_mock_odom_dryrun_r02_20260917_145834_900` |
| フレーム・長さ・実効FPS | 1,035フレーム・約34.6秒・29.882 FPS |
| raw/BEV/detection動画 | すべて1,035フレーム、CSVと一致 |
| 青箱検出 | 1,035/1,035フレーム |
| ODOM available | 343/1,035フレーム |
| 0.25 m/sを観測 | 122フレーム、録画開始後9.654～13.791秒 |
| WARNING | 122フレーム、9.720～13.856秒 |
| FFB active指令 | ８件、9.720～10.121秒、要求強度0.25 |
| 最小有限TTC | 4.235秒 |
| FFB publish API失敗 | ０件 |

一括解析の`DIAGNOSTIC`は要件CSVを渡していないことを示し、録画破損を意味しない。セッション完全性はPASSだった。

## ハンコン接続PCのbag

bagは14:56:31.909～14:59:50.569 JST、合計10,900件。３topicをすべて記録し、0.25 m/sの模擬ODOMも含んでいた。

| topic | 件数 | 警告区間の内容 |
|---|---:|---|
| `/phase5/mock_odom` | 3,937 | 速度0が3,848件、0.25 m/sが89件（14:58:44.480～47.414） |
| `/collision/ffb_command` | 3,641 | active８件、sequence 2383, 2384, 2385, 2389, 2390, 2393, 2394, 2395。すべてWARNING、要求強度0.25 |
| `/collision/ffb_status` | 3,322 | 上記８sequenceに対応するstatusがすべて存在。ただし全件fault・stop・出力inactive |

active commandは14:58:44.535～44.958 JSTにbagへ到着し、カメラCSVの８sequenceと完全一致した。対応するstatusのbag記録時刻はcommandの0.423～0.769 ms後（中央値0.539 ms）。したがって、この区間では指令はadapterまで届き、adapterが拒否したと判断できる。単なるrosbag購読漏れではない。

対応する８statusはすべて`output_mode=disabled`、`requested_magnitude=0.25`、`applied_magnitude=0.0`、`fault=true`、`reason=invalid_request:future_message`だった。active指令の`header.stamp`はハンコン接続PCのbag記録時刻より67.2～89.7 ms先（中央値89.4 ms）。adapterが示したageは`-67.071`～`-89.434 ms`で、既定の未来時刻許容`50 ms`を超えた。bag全体ではstatus 3,322件のうち3,318件が同じ未来時刻fault、`output_mode`は3,322件すべて`disabled`、`output_active=true`は０件だった。終了時のstatusはinactiveの`shutdown`。

## 原因の切り分けと次の確認

1. **時刻不整合：観測事実。** カメラ側header時刻がハンコン接続PCの受信時計より約90 ms先にあり、adapterの`future_tolerance_sec=0.05`秒の安全検査で拒否された。ネットワーク遅延だけでは「受信より未来」のheaderにならないため、両PCの時計系の不整合が強く疑われる。bag単体からNTPの具体的な設定原因までは確定しない。しきい値は緩めず、両PCで試験直前の`timedatectl --no-pager timesync-status`を保存し、CLEARのstatusでfaultが出ないことを確認する。
2. **adapter mode不一致：観測事実。** 全statusの`output_mode=disabled`。手元のadapter実装ではstatusへ実際の`self.output_mode`を書き込むため、記録されたadapterは`dry_run`で動いていなかった。旧プロセスが残っていた、または起動引数が反映されなかった可能性があるが、現時点では原因未確定。ハンコン接続PCで`ros2 node list`、`ros2 topic info /collision/ffb_status -v`、`ros2 param get /collision_ffb_node output_mode`、adapter起動ログを確認し、意図したadapterが１つだけで`dry_run`になっていることを確かめる。
3. **再録画はまだ不要。** カメラ検出・0.25 m/s模擬ODOM・FFB指令生成とPC間伝送はこの録画で実証された。まず安全なCLEAR指令だけで`output_mode=dry_run`、`fault=false`を確認する。active試験の再実施はその後にする。G923 hardware modeや安全時刻許容値の緩和には進まない。

参考実装：`FFB_feedback_control/FFB_feedback_control/src/oit/oit/collision_ffb_node.py`の`output_mode`既定値・statusへの代入、および`collision_ffb_policy.py`の未来時刻判定（ageが`-future_tolerance_sec`より小さいと拒否）。

## 追試：同じ録画riskのPC間dry-run再生

ハンコン接続PCでadapterを明示的に`dry_run`へ起動し直し、`ros2 param get /collision_ffb_node output_mode`で`dry_run`、status publisherが１つであることを確認した。Kobuki PCからの単発CLEARは`fault=false`で受理された。次にr02録画の`detections.csv`を30 Hz・triple設定で再生した。元のカメラ再録画はしていない。受領した[再生レポート](phase5_dryrun_replay_r02/replay_report.md)と[adapter status CSV](phase5_dryrun_replay_r02/adapter_status.csv)を保存した。

| 指標 | 結果 |
|---|---:|
| 再生命令 | 1,036件（終了時CLEARを含む） |
| active命令 | ９件、tripleの３区間 |
| 受信status | 1,006件、全件`dry_run` |
| active status | ９件、全件`action=apply`・`output_active=true` |
| fault | ０件 |
| 要求強度・最大適用強度 | 0.25・0.05 |
| 末尾status | inactive |
| 自動判定 | **PASS** |

この追試は**記録済みriskからROS topicを通してdry-run adapterが受理・上限クランプ・解除できること**を確認した。先のr02ライブ試験そのもののFAIL判定をPASSに書き換えるものではない。再生は映像認識を再計算せず、G923の物理振動も出さない。実カメラからadapterまでを同時に通す短いライブdry-runの再試験が、次の統合検証として残る。安全時刻許容値は緩めない。
