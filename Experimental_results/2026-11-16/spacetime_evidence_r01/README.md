# 保存ログから時計・車体座標の接続根拠を整理

2026-11-16。**時計対応の追加観測項目と、車体座標変換で不足している情報を具体化した。** 既存の距離推定やodom受信の成功を取り消す作業ではなく、同じ情報をFFBの車体基準入力へ取り違えずに渡すための整理。

[計画](implementation_plan.md)、[計算](diagnostics.py)、[再現監査](audit.py)、[正式結果](results_r01/audit.json)。実行系・操縦・測距・ROS/FFBは変更していない。追加撮影・走行・外部時計調整もしていない。

## 最新：貼付出力からKobuki元stampの生成経路を確認

ユーザー提出のgrep出力は先頭が切れていたが、必要な連鎖は全て残っていた。再送・ソース全体の再提出は不要。[抽出根拠](kobuki_stamp_source_evidence.json)。295行の元テキストをrecordings/2026-11-16/kobuki_stamp_source_intake_r01/terminal_excerpt.txtへそのまま保存、SHA201fcc9ba30c9aa9f597fc78e5e9638491148ad0def15833c6518f179242ab8b。

1. kobuki_ros.cpp:593で `this->get_clock()->now()` を `odometry_->update()` の最後の引数へ渡す。
2. odometry.cpp:87で `const rclcpp::Time & now` として受ける。
3. 同104行で `odom_quat_time_ = now`。
4. 同138行で `odom->header.stamp = odom_quat_time_`。
5. kobuki_ros.cpp:598で `getOdometry()` の結果をpublishする。

このソースでのheader stampは**Kobukiドライバのodometry更新時に読んだROSノード時計**であり、firmwareの計測timestampをそのまま渡したものではない。従って今後の時計対応では、まずdriver更新timestamp→sender/receiver時計を対象とし、センサ計測時刻そのものへの同期とは区別する。上の欠けた部分を補完しなくてもこの生成経路は読めた。

直前の両ノードuse_sim_time=falseと合わせて、生成元確認は前進した。ただし添付は部分grepであり、ソース全文SHA・現在実行binaryとの一致・driver固有TimeSource/時刻補正までは確認していない。通常ROS時計の既定挙動の説明と実機時計同定を混同せず、既存のsource_clock_id=nullや同期未認定flagを遡って書き換えない。snapshot/受信/露光の時刻とも同一視しない。

次はROS時計読出しをsender monotonicの前後で挟む観測形式と、sender/receiverの対応区間を保存する実装段階。headerがセンサ取得時刻だという前提では実装しない。今回の返答ではそのruntime変更や追加記録はまだ実施していない。ユーザー側の追加操作は現時点では不要。従来の通信・操縦・ドライバ設定はそのままにする。

## 後続の実機読み取り結果：両ノードuse_sim_time=false

ユーザー貼付出力を[時計設定の記録](ros_clock_settings_user_report.json)へ保存。matsunucの `/kobuki` と `/theta_driver_telemetry_node` はともにuse_sim_time=false、`/clock` はUnknown topic。読み取り時の設定/可視性を確認できたが、以前のr03記録期間全体の設定・元stamp生成元・PC間の時計同期まで遡って認定しない。`/clock`の不存在を故障扱いして起動/設定変更する必要はない。

既存の[8/18 odometry診断メモ](../../2026-08-18/2026-08-18_kobuki_odometry_diagnosis_memo.md)から、当時の実体は `/home/matunuc/kobuki_ws/install/kobuki_node/lib/kobuki_node/kobuki_ros_node`、元ソースは `/home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/src/` と分かった。メモにはwheelbase/IMU設定修正と走行時odomの符号/値の検証もあり、それを破棄して停止0から物理検証をやり直させない。ただし当時のメモはheader stamp生成行を記録しておらず、11/16実行binaryとの一致も未確認。

次はこの既知のソースでstampをどこから作るかを読み取り、実行中のドライバ起源と照合する。上流GitHubやROS1/Gazeboの別版を本機実装と見なさない。通常のkobuki/送信は停止・再ビルドせず、matsunucで次を実行して出力を得る。

```bash
rg -n -C 4 'header[.]stamp|[.]now\(|->now\(|odometry.*(update|publish)|Clock|rclcpp::Time' /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/src/kobuki_ros.cpp /home/matunuc/kobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/src/odometry.cpp
```

パス不在/rg不在の場合も出力をそのまま共有し、別版のコピー・ドライバ再起動・システム時計変更では回避しない。この確認は元stampの生成起源を狭めるためで、PC間同期や露光同期を確認するコマンドではない。結果を踏まえてROS→sender時計bracketの追加箇所を決める。

## 時計：現ログで分かること

r03の3原本を受信監査SHAへ照合して2,045件を解析。整数nsの元stampは先に整数差を取ってから秒へ変換し、epoch全体のfloat化を避ける。

| 同じ記録の先頭から末尾までの経過 | 秒 |
|---|---:|
| 元header stamp | 87.164885501 |
| sender callback monotonic | 87.164924483 |
| sender snapshot monotonic | 87.158089766 |
| receiver受信monotonic | 87.160979457 |

差の揺れも集計したが、異なるイベント・時計を比べるため**時計精度や通信遅延ではない**。

| 先頭を0とした経過差 | 最小ms | 最大ms |
|---|---:|---:|
| 元stamp経過 − sender callback経過 | −15.394341 | 0.402682 |
| receiver受信経過 − sender snapshot経過 | −0.271221 | 62.250626 |

前者は元stamp/ROS時計・callback到着遅延/スケジュール等、後者は時計歩度・伝送/処理待ち等が混ざる。終点差だけでドリフトを認定したり、62.522msの変動幅を通信遅延上限としたりしない。

### 片道ログからoffsetを決められない実例

一定の相対歩度という条件を置いても、受信時刻r・送信snapshot sは `r-s = 時計差b + 片道遅延d` としか観測されない。

このr03に対して、bを593.462465584秒と仮定すると非負dは0〜62.521847ms。bを0.1秒小さく仮定しても、非負dは100〜162.521847msで、同じログを説明できる。これは**真のoffsetや遅延の2候補を選んだ結果ではなく、識別不能の反例**。0.1秒は説明用の任意シフトで採用した期限/遅延上限ではない。相対歩度が未知の場合はさらに対応が必要。実bindingは生成していない。

## 時計対応の収集方式

[ROS2 Clock and Time](https://design.ros2.org/articles/clock_and_time.html) はROS/System/Steadyを区別し、use_sim_timeや時刻ジャンプを扱う。header stampがepochらしく見えるだけでSystem時計とは同定しない。

今後必要な観測を、既存操縦メッセージから切り離して準備する。

1. `/kobuki`と送信ノードの時計設定・元stamp生成元を確認する。use_sim_time=falseだけでもdriver独自のstamp起源までは証明しない。
2. senderでROS nowの読出し前後をmonotonicで挟み、ROS→senderの対応区間と読出し誤差・ジャンプを保存する。元stampがそのROS時計と同じ起源である根拠も必要。
3. senderとreceiver間は4timestampの観測交換、または根拠付き外部同期＋両時計の同時サンプルを用いる。session/process、nonce/交換順序、読出し誤差、適用区間、相対歩度/ドリフト上限を記録。単一offsetの適用を無期限に続けない。
4. 同じ接続・receiver時計の距離と運動を記録して結合条件を確認する。露光同時刻性は別の問題として残す。既存の別sessionの距離とr03運動を混ぜない。

4timestamp方式は [RFC5905 §8](https://www.rfc-editor.org/rfc/rfc5905.html#section-8) のoffset/往復遅延の考え方を参照した。ただし今回の関数はNTP実装や同期daemonではなく、以下の条件付き算術のみ。

receiver送信r1、sender受信s2、sender返送s3、receiver受信r4に対し、一定相対歩度と非負の両方向遅延を仮定すると、receiver−senderの時計差は `[r1-s2, r4-s3]`。中点が真値とは限らず、区間幅には非対称遅延の曖昧さが残る。読出し誤差・ドリフト分はさらに拡大が必要。

合成例r1=100、s2=10.02、s3=10.025、r4=100.055秒では区間89.98〜90.03秒、半幅25ms。真値90秒の非対称な往復も整合し、中点90.005秒へ勝手に固定しない。**実r03に4timestampは存在しない**ため、この25msも実機誤差の結果ではない。

方式比較：片道最小差は現データだけで計算できるが未知遅延を0と仮定するため不採用。既存NTP等の利用は有用でも、それだけでROS/monotonicやprocessの対応が完成するわけではない。4timestampは新しい観測交換の実装が必要だが、対称遅延を仮定せず区間を作れる。今回は将来の収集項目を定めるまでで、network/telemetry/controlへの新交換追加やOS時計設定は行わない。

## 座標：現在採用できる車体変換はない

[光学床面ベクトルの監査](../motion_spatial_inputs_r01/README.md)の派生原本SHAを照合。19,297点が条件付き光学床面ベクトル、31,905点は保留という既存結果を再利用した。今回それらを車体XYへ変換した件数は0。

確認した過去候補は次の理由で現在の車体変換へ自動採用しない。

- [10/19診断変換](../../2026-10-19/fisheye_tf_preparation_r01/results_r01/diagnostic_transforms.json)：measured_extrinsics=false、base_link_transform=false。
- [10/21紙基準候補](../../2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json)：高さ0.59m・XY0固定のpaper7_ground_reference条件付きfitで、物理変換独立測量false。
- [11/9同frame診断](../../2026-11-09/wide_floor_geometry_r01/same_frame_pose_r01/summary.json)：別sessionの左右/handedness保留、selected_solution=null。

これらのSHAは正式集計に保存。新しいカメラ取付の車体原点・前方軸・並進をこれらから埋めない。ユーザーの前進方向基準の左右定義は確定済みで、再質問しない。

軸の設計は [REP103](https://github.com/ros-infrastructure/rep/blob/master/rep-0103.rst) の車体x前/y左/z上と光学x右/y下/z前に従う。ただし本機の取付向き・originがそのまま一致するという根拠ではない。

カメラ直下→床支持点の光学ベクトルq、床上向きu、高さhに対して、光学原点→車体変換(R,t)を明示できれば、支持点は `R(q-hu)+t`、カメラ直下点は `t-hRu`。直下点を原点としたqへカメラ原点のtをそのまま足す誤りを避ける。

合成例では、h=.59m、カメラ原点t=(前.2m、左.1m、高さ.59m)、光学q=(右.3m、下0、前1m)に対して、車体支持点(前1.2m、左−.2m、高さ0)を得る。反射・非直交・床向き不一致・bool/非有限値は拒否する。同じ床法線と1m距離でもyaw90度の別解なら車体前1mが左1mになり得ることも検証。**これらの寸法や回転を実機に採用していない**。

必要なのは現取付でのbase_footprint原点からカメラ光学原点/直下点の前後左右・高さ、前進方向に対する光学向き、測定根拠と適用session。車幅と支持点/台座近辺中央/物体の広がりの意味も後段リスク評価には必要。現在の支持点を物体全体や追跡IDへ昇格しない。

## 次にユーザー側で行う読み取り確認

通常のkobuki・映像送信が起動している状態で、matsunucの同じROS環境の別端末から実行する。パラメータを設定するコマンドや走行指令ではない。

```bash
ros2 param get /kobuki use_sim_time
ros2 param get /theta_driver_telemetry_node use_sim_time
ros2 topic info /clock
```

`/clock`が存在しないという出力もそのまま記録する。エラーを消すためにdriver再起動・parameter set・chrony/NTP設定変更を行わない。出力に応じて元stamp生成元/時計観測の追加方法を決める。同じ停止記録・新しいコーン撮影・走行はまだ不要。

## 検証と再現

新10＋関連計83テスト成功、0失敗（1.30秒）。片道非同定、任意シフト、非対称往復、無効時刻、原点差、yaw非一意、反射/非剛体拒否、入力非変更を確認。先行83/145/200等との重複を独立件数として加算しない。

初回集計scriptの合成yaw行列に符号の転記ミスがあり、det=−1の反射として検証器が拒否した。正式結果保存前に正しいyaw90回転へ修正し、全監査・関連83テストを再実行して成功。実行系・実機変換には影響していない。

出力名は未使用にする。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/spacetime_evidence_r01/audit.py --output-dir Experimental_results/2026-11-16/spacetime_evidence_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_spacetime_evidence.py tests/test_received_motion_handoff.py tests/test_odometry_metadata_live_audit.py tests/test_driver_motion_time_join.py tests/test_driver_motion_spatial.py tests/test_driver_motion_integration.py
```
