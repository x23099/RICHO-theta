# 送信nodeのROS時計読出しをmonotonicで挟んで記録

2026-11-16。**送信PC内のROS時計読出し区間をtelemetry経由で保存する実装と模擬検証を完了**。[計画](implementation_plan.md)、[正式模擬結果](results_r01/audit.json)、[17ケース](results_r01/cases.json)、[検証記録](verification.json)。ローカル未commit/未push、両PCへ未反映、実ROSでは未確認。

これはPC間同期の完成ではない。今回は「送信nodeのROS nowと送信monotonic」を観測できるようにする第一段階。Kobuki nodeのheader時計との関係、送信/受信PC間対応、drift/精度の上限、センサ取得/露光同期は未認定。

## 実装

- [driver_sender_clock_observation.py](../../../src/driver_sender_clock_observation.py)：標準ライブラリのみ。ROS nowを読むcallableの前後でmonotonic_nsを採り、整数nsの読出し区間・状態・世代を返す。ファイル/通信/ROS publish/時計設定はしない。
- [webrtc_stream.py](../../../src/webrtc_stream.py)：既存TelemetryNodeに任意のclock observerとgetterだけを追加し、辞書key `sender_clock_observation` を追加。odometry_observation v1と旧UI用値はそのまま。既存odom observerと同じsender IDを使う。
- [driver_telemetry_recording.py](../../../src/driver_telemetry_recording.py)：新keyがあればv3 envelopeで時計観測とdecode状態を保存。既存有界queueへ投入するだけで、受信callbackへディスク処理を追加しない。

運転UIのコード・操縦publish・subscription/topic・camera/codec・距離計算・既存odom helperは変更していない。新しいprobe交換やcontrol channelメッセージも追加していない。旧senderの記録はv1/v2のまま、新senderのclock keyありはv3。古い受信側は新keyを記録しないので、確認には**matsunucとGPUPCの両方の反映**が必要。

## 観測内容と意味

`driver_sender_ros_clock_observation_v1` は以下を持つ。

| 項目 | 意味 |
|---|---|
| sender_id / sender_monotonic_clock_id | 同一sender observerの識別。OS boot IDや同期証明ではない |
| sample_sequence / clock_generation | clock読出し試行の順序と区切り。ROSメッセージのsequenceではない |
| mono_before_ns / mono_after_ns | nodeのROS now読出しを含む処理の前後、整数ns |
| ros_now_ns | sender node自身の時計を読んだ整数ns。odom header値とは別 |
| clock_type | 実clockのROS_TIME / SYSTEM_TIME / STEADY_TIME。ROS_TIMEでもsim無効はあり得る |
| use_sim_time / ros_time_active | parameter値とclock active状態の読出し。前後で設定が変わった場合は不採用 |
| ros_minus_mono_lower_ns / upper_ns | `ros_now−mono_after` / `ros_now−mono_before`、読出し時点の算術区間 |
| bracket_width_ns | 前後monotonicの幅。clock精度や通信遅延ではない |
| ros_time_status | first / advanced / repeated / reversed / zero |
| configuration_changed | 前回の時計種別/parameter/active状態との違い |

ROS_TIMEのactive状態はbool、他種別ではnull。ros_now=0はzeroと明記し、初期化済みとは扱わない。ROS逆行・設定変更・観測異常ではgenerationを分け、古い区間を新しい観測として使い回さない。

statusはsampled / sampling_error / monotonic_invalid / observer_busy。失敗・競合時は時刻フィールドを全nullにし、返却処理はobserverのlock取得を待たない。新機能の初期化/読出し例外は新metadataだけを不採用にして既存telemetryを継続する。ROS clock取得そのものの最悪所要時間は保証しておらず、実機負荷/通信周期への影響は未確認。

ROS−monotonic区間は、読出しの間に時計値が単位歩度で進むと見たときの1回の観測。機器時計の量子化/読出し精度、間の時刻ジャンプ、drift、実header起源の不確かさまで含む検証済みbindingではない。有限サンプルの前進jumpや中間設定変化を全件検知する実装でもない。中点への自動固定や無期限の区間適用をしない。

clock_scopeは `sender_node_clock_NOT_odom_publisher_or_sensor_clock_verified`。header_clock_relation_verified / receiver_clock_binding_verified / source_freshness_verified / usable_for_ffb / published_to_rosは全false。

### receiverの扱い

対応版はversioned_sender_clock_observation、未知版/不正は理由付きnull。clockとodomが両方検査済みなのにsender IDが異なる場合はsender_clock_scope_mismatchでclockを捨てる。clock単独でも記録は可能だが、odomとの対応が確認された意味ではない。

旧UI用linear/angularと入れ子odomは独立のまま。トップレベルsource_clock_id/measurement_validはnullを維持し、clock区間を使って運動入力の有効性を昇格しない。以前のoffline adapter/監査はv1/v2対象なので、v3を未対応として拒否する場合がある。今回そこへ自動投入せず、次段階でv3対応と時計条件を検証する。

metadataには対応schema/record schema一覧と新helperを含むreceiver4コードSHAを追加。過去r03の原本・原metadata/監査SHAは履歴のまま保持し、旧記録を今回版へ書き換えない。

## 検証結果

| 項目 | 結果 |
|---|---:|
| 実sender getter→JSON→実receiver callback→保存（fake ROS/peer） | 17 / 17 |
| v3 / 旧v2 / 旧v1 telemetry | 15 / 1 / 1 |
| 開始終了込みevents | 19、offered=queued=written |
| queue/lock/drop/reject | 全0 |
| ROS逆行/0/設定変化/読出し異常/競合/monotonic逆行 | 保持または明示null、旧clock再利用なし |
| 既存の距離/表示12ソース | 全byte不変 |
| 関連テスト | 252成功、0失敗（8.55秒） |

新clock20テストを含むsuite。以前の76/83/145/200等と重複するので合算しない。senderの旧TelemetryNode固定AST hashは、正確なmetadata追加9箇所（旧odom5＋新clock4）だけを取り除くと従来baselineと一致。baselineの差替えではない。sender control/camera/spin/receiver keyboard/ROS/controlの固定hashも維持。

模擬rawはrecordings/2026-11-16/sender_ros_clock_bracket_synthetic_r01。今回の成功は実通信の負荷・node clock API実機互換性・PC間同期・実FFBを確認した意味ではない。

## 両PCへ反映後の確認手順（まだ未実施）

今回分をGit等で反映してから行う。過去のGPU反映済みという申告はこの変更前なので、この新helper/変更が含まれるか確認する。旧patchの再適用は不要。

1. matsunuc：通常の送信repoにsrc/webrtc_stream.pyと新src/driver_sender_clock_observation.pyを反映。
2. GPUPC：src/driver_telemetry_recording.pyと新helperを反映。src/driver_odometry_observation.pyは従来版を保持。UI本体は今回変更なし。

senderの通常repo rootで構文確認：

```bash
python3 -m py_compile src/webrtc_stream.py src/driver_sender_clock_observation.py
```

GPUPCでは：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 -m py_compile src/driver_telemetry_recording.py src/driver_sender_clock_observation.py
```

双方反映後、既存送受信を通常終了。kobuki/ROS設定は変更せず、機体は停止、ハンドル/ペダル/WASD操作なし。新しい受信を先に起動し、その後いつものsenderを再接続する。今回の記録は新項目の初回確認であり、以前のodom疎通試験をやり直すためではない。コーン移動・撮影・走行・画面録画は不要。

GPUPCの従来ROS/Qt環境で：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
THETA_UI_NO_VENV=1 python3 src/webrtc_receive_ui.py --cam-width 1280 --cam-height 720 --telemetry-record-dir recordings/2026-11-16/received_sender_clock_r01
```

送信接続後10〜20秒待ち、GPUPCの別端末で `wc -l recordings/2026-11-16/received_sender_clock_r01/received_telemetry.jsonl`。0行なら圧縮せず起動端末ログを確認する。距離推論は起動していないため距離欄が出ないのは正常。

受信画面を通常終了して、GPUPCで：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
python3 -m json.tool recordings/2026-11-16/received_sender_clock_r01/telemetry_recording_summary.json
test ! -e /home/hsr/Downloads/received_sender_clock_20261116_r01.tar.xz && tar -cJf /home/hsr/Downloads/received_sender_clock_20261116_r01.tar.xz -C recordings/2026-11-16 received_sender_clock_r01
```

summaryのclosed/error=null/shutdown_complete=trueを確認し、3ファイル入りarchiveを提出。同名directory/archiveがあれば削除せず、新しいr名に全箇所を揃える。matsunucでGPUPCの/home/hsrパスを実行しない。

## 根拠・ローカル再現

[rclpy Node.get_clock](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/node.py)、[Clock.now/clock_type/ROS active](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/clock.py)、[Python3.10 monotonic_ns](https://docs.python.org/3.10/library/time.html#time.monotonic_ns)を確認。これらはAPIの根拠で、実機の誤差上限の根拠ではない。

未使用の出力名を指定する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/sender_ros_clock_bracket_r01/check.py --output-dir Experimental_results/2026-11-16/sender_ros_clock_bracket_r01/results_r02 --raw-output-dir recordings/2026-11-16/sender_ros_clock_bracket_synthetic_r02
```

全関連テストのコマンドはverification.jsonに保存。次は実記録でnode clock区間を確認し、その後PC間時計対応を別に実装/検証する。時計対応だけで車体変換・点の意味・車幅・リスク勾配・FFB認定が完了するわけではない。
