# 実受信したsender ROS時計観測の確認完了

2026-11-16。**全1,177telemetryでROS nowのmonotonic読出し区間を保存し、同じsenderのodometry情報と対応していることを確認した。** この送信PC内の時計観測の疎通確認は完了。同じ試験の再提出・撮影・走行は不要。

[正式全件結果](results_r02/audit.json)、[監査script](review.py)。results_r01は同じ提出物の初回監査成功履歴で、r02は同一メッセージ内のodom snapshot→clock readの因果順序検査と依存コードSHAを追加した正式結果。2回の実機試験として件数を合算しない。

## 入力と完全性

archive `received_sender_clock_20261116_r01.tar.xz`、SHA `07cdbd52ca87b33a33f5eabba9bf09d21a59c9da57b6caa8a5d4e0b2ac89488e`。directory1＋通常file3を検査し、余分なpath・リンク・重複・容量超過を拒否。受信記録器/UI/odom helper/clock helperの4コードSHAは現在のローカル版と一致。全rawをrecordings/2026-11-16/sender_ros_clock_live_intake_r02へ保持。r01 intakeも同じ原本として保持する。

| 確認項目 | 結果 |
|---|---:|
| 保存イベント | peer_begin 1＋telemetry 1,177＝1,178 |
| telemetry受信時間幅 / 平均頻度 | 50.329734秒 / 23.3659 Hz |
| v3時計metadata検査成功 / sampled | 1,177 / 1,177 |
| senderとodomのID/monotonic時計ID一致 | 全1,177件 |
| odom snapshot→clock readの同message因果順序 | 全件整合 |
| node時計種別 / use_sim_time / ros_time_active | ROS_TIME / false / false |
| 時計sample sequence | 1〜1,177 |
| clock_generation | 全1、設定変化観測0 |
| ros_time_status | first 1、advanced 1,176 |
| ROS逆行 / 反復 / 読出し失敗 / 観測競合 | 観測なし |
| odometry受信済み / 元stamp進行status | 全1,177件 |
| odometry保存観測間の元stamp進行 | 1,176 / 1,176区間 |
| 受信したv / ω | 全0 m/s / 全0 rad/s |
| twist frame / pose frame | base_footprint / odom |
| queued / written | 1,178 / 1,178 |
| 保存bytes | 2,895,788、summary一致 |
| queue/lock drop / 受理後破棄 | 0 / 0 |
| offered / rejected | 1,180 / 2 |
| 保存sequence | 1〜1,178、内部欠けなし |
| 終了 | closed、error=null、writer_done/shutdown_complete=true |

末尾2offerの拒否理由やevent種別は記録されていないので、正常終了処理だけが原因とは断定しない。受理済み範囲は全件保存。終了peer event自体の保存はない。

単一session `122bb71ea3ae44cb8e38c21534c8edf1`、receiver時計 `receiver-process/8cc2ba7b04d84ba19abdbd668e2b8c02`、sender ID `13c3ef90fd6a41e7a283b7195abd6604`。同じsender IDはこのclock/odom観測の対応を示すが、別PC時計の同一性や実行binary全体のSHA認定ではない。

## 読出し区間と時刻観測

| 項目 | 中央値 | P95 | 最大 |
|---|---:|---:|---:|
| ROS clock読出しを挟むmonotonic幅 | 0.102126 ms | 0.165567 ms | 0.287649 ms |
| 受信間隔 | 42.757187 ms | 45.974163 ms | 58.617648 ms |
| receiver受信→writer timestamp差 | 0.297108 ms | 0.611987 ms | 4.081418 ms |
| sender ROS now − odom headerの数値差 | 10.732290 ms | 19.563005 ms | 21.817868 ms |

時計読出し幅の最小は0.047061ms。recorder投入最大0.222888msは受信callback全体ではない。writer timestamp差はディスク完了・通信遅延ではない。ROS nowとodom headerの数値差は、別node時計の同一起源やドライバbinary一致を独立認定していないため、証明済みの輸送遅延/元計測年齢とは呼ばない。カメラ露光との対応もない。

同一clock generationの各ROS−monotonic区間を、**一定相対歩度・一定offsetという仮定**で交差させると、下限1794806106166096880ns、上限1794806106166142944ns（幅46,064ns）の非空区間になる。観測にこの仮定との明白な矛盾がないことは分かるが、真のclock精度・drift上限やdriver header対応の保証ではない。単一区間の中点を実bindingへ採用していない。

## この確認で完了したこと／次の段階

完了したのは **sender nodeのROS clock読出し→monotonic前後区間→JSON→受信callback→有界queue→ファイル保存** の実記録確認。新schemaの導入と実node API呼出しに伴うsampling_error等は今回観測されなかった。測距推論併走や長時間運転の性能保証ではない。

未完了はsender/receiver PC間の時計差・適用区間・drift/誤差上限の対応。この片道記録だけでそのoffsetを決めない。既存の[片道識別不能の解析と4timestamp方式](../spacetime_evidence_r01/README.md)を継承し、次は両PC時計の対応区間を採る実装段階。今回それを新実装/実行したわけではない。

同時刻の距離/運動結合、現在取付の車体↔光学変換、車幅/点の意味、リスク勾配、G923出力も別途必要。過去の別session距離ログとこの50秒の運動記録を混ぜず、source_clock_id/measurement_validやfalse flagを遡って昇格しない。今回の同じ停止記録を繰り返す依頼はしない。次の実装ができるまでユーザー側の追加操作は不要。

## 検証方法

監査器はv3のclock schemaを厳密検査し、odom schemaとsender IDを照合。メッセージの共通envelope/件数/受信時刻/終了状態は、検査用コピーだけclock keyを除いてv2へ投影し、従来の厳密監査器を再利用する。さらに元JSONLのbytesを元summaryへ独立照合。rawや元metadata/summaryを書き換えてはいない。

clock sampleのsequence/generation/monotonic順序、同generationでのROS逆行、同一messageのodom snapshot→clock read順序も検査。秒floatと整数nsの比較には1nsの数値許容を置くが、時計同期誤差の採用値ではない。

新監査10＋既存v2監査12＋clock観測20＋odom観測20＋記録22＝**84テスト成功、0失敗（1.13秒）**。未知schema/不正型/方程式/権限/余分なfield/別sender/順序/元bytes/コードSHA/archive pathやlinkを検証。過去83/252等との重複を独立件数として合算しない。runtime変更なしで252テスト成功を再利用し、全suiteは再実行していない。

再現時は未使用の出力名を指定。実機/ROS/GPU/G923を起動しない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/sender_ros_clock_live_audit_r01/review.py --archive /home/robo25/Downloads/received_sender_clock_20261116_r01.tar.xz --raw-output-dir recordings/2026-11-16/sender_ros_clock_live_intake_r03 --output-dir Experimental_results/2026-11-16/sender_ros_clock_live_audit_r01/results_r03
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_sender_ros_clock_live_audit.py tests/test_odometry_metadata_live_audit.py tests/test_driver_sender_clock_observation.py tests/test_driver_odometry_observation.py tests/test_driver_telemetry_recording.py
```
