# Phase 5 実カメラ・模擬ODOM・PC間 dry-run 再試験手順（r02）

## 目的と合格条件

前回 r01 ではカメラ側が WARNING と FFB active 指令を生成したが、ハンコン接続PCのbagはその区間を記録していなかった。今回は**両PC間の指令・応答を同じ時間帯に記録する**。`output_mode=dry_run`なのでG923は振動しない。Kobukiも走行させない。

合格条件は、青箱検出と0.25 m/sの模擬ODOMによるWARNING、bag内の0.25 m/s ODOM・active command・対応する`output_mode: dry_run`のactive status、fault 0件、最後のinactive statusを確認できること。bagのtopic件数だけでは合格にしない。

## 準備（両PC）

- Kobukiは停止させ、青箱をカメラ正面約0.9～1.0 mに固定する。実機の`/odom`には模擬データを送らず、専用の`/phase5/mock_odom`を使う。
- 両PCで時刻同期を確認する。`timedatectl --no-pager timesync-status`の`Offset`を読み、数十ms以上のずれやadapterの`future_message`が続く場合は、速度試験を始めず同期を直す。時刻検査の許容値は緩めない。
- 両PCの各ターミナルで`ROS_DOMAIN_ID=88`、`ROS_LOCALHOST_ONLY=0`を明示する。ハンコン接続PCは`hsr-Alienware-m16-R2`、Kobuki PCは`matunuc-NUC13ANHi5`。
- Kobuki PCのリポジトリで`git status --short`を確認する。`run_field_experiment.py`は既定でclean gitを要求するため、無関係な未コミット変更があると起動前に止まる。変更を勝手に破棄しない。

ハンコン接続PCのターミナルA・Bそれぞれで最初に実行：

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

Kobuki PCのターミナルC・Dそれぞれで最初に実行：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

## 起動順

1. **ハンコン接続PC・A：dry-run adapterを起動し、終了まで動かしたままにする。**

   ```bash
   ros2 run oit collision_ffb_node --ros-args \
     -p output_mode:=dry_run \
     -p max_magnitude:=0.05
   ```

   `mode=dry_run`の起動ログを確認する。G923のdevice pathや`hardware_armed`は指定しない。

2. **Kobuki PC・C：模擬ODOM 0 m/sを開始する。**

   ```bash
   ros2 topic pub --rate 30 --print 30 \
     --qos-reliability reliable --qos-durability volatile \
     /phase5/mock_odom nav_msgs/msg/Odometry \
     "{header: auto, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}"
   ```

   Cは動かしたままにする。この試験では速度0と0.25 m/sのpublisherを**絶対に同時起動しない**。

3. **Kobuki PC・D：カメラアプリを起動する。**

   ```bash
   cd ~/theta_ws
   git status --short
   python3 src/run_field_experiment.py \
     --config src/bird_eye_config_ttc_v7_ffb_triple_20260916.json \
     --record-dir src/recordings/2026-09-17_phase5_live_dryrun \
     --experiment-label phase5_camera_mock_odom_dryrun_r02 \
     --camera-device 0 \
     --camera-fps 30 \
     --camera-frames 60 \
     --odom-topic /phase5/mock_odom \
     --odom-timeout-sec 10
   ```

   Preflightが全項目PASSし、カメラ画面で青箱を検出していることを確認する。ここでは**まだ録画ボタンを押さない**。

4. **ハンコン接続PC・B：新しいrosbagを開始する。**

   ```bash
   mkdir -p ~/ffb_recordings/2026-09-17
   ros2 bag record \
     -o ~/ffb_recordings/2026-09-17/phase5_live_dryrun_r02 \
     /collision/ffb_command \
     /collision/ffb_status \
     /phase5/mock_odom
   ```

   Bに**３topicすべて**の`Subscribed to topic`が表示されるまで待つ。表示されなければ録画・速度切替を始めない。Aのログに時刻起因の`future_message`やfaultが出ていないことも、ここで数秒確認する。

5. **Kobuki PC・D：GUIの録画を開始する。** 速度0のまま約5秒記録する。

6. **Kobuki PC・C：0 m/sを`Ctrl+C`で完全に停止する。** 同じPCの別ターミナル（またはC）で次を確認し、`Publisher count: 0`になってから次へ進む。

   ```bash
   ros2 topic info /phase5/mock_odom
   ```

7. **Kobuki PC・C：0.25 m/sを約3秒、90件だけ送る。**

   ```bash
   ros2 topic pub --rate 30 --times 90 --print 30 \
     --qos-reliability reliable --qos-durability volatile \
     /phase5/mock_odom nav_msgs/msg/Odometry \
     "{header: auto, twist: {twist: {linear: {x: 0.25}, angular: {z: 0.0}}}}"
   ```

   送信が終わってコマンドプロンプトへ戻ったら、`ros2 topic info /phase5/mock_odom`でpublisher数が0になったことを確認する。箱とKobuki本体は動かさない。AではWARNINGに対応する`action=apply`と、その後のinactive/stopを観察する。dry-runなので振動は出ない。

8. **Kobuki PC・C：0 m/sを再開し、約5秒維持する。** 手順2と同じコマンドを再実行する。これによりWARNING解除後のCLEARを記録する。

9. **終了順：** DのGUI録画を停止してカメラアプリを閉じる → Cの0 m/s publisherを`Ctrl+C` → Aのadapterを`Ctrl+C` → Bのbagを**最後に**`Ctrl+C`。bagを先に止めると最後のinactiveやshutdownを取り逃がす。

## 現場での確認・提出物

ハンコン接続PCで以下を実行し、３topicがすべて0件超であることを確認する。ただし内容の合否は後続解析で判定する。

```bash
ros2 bag info ~/ffb_recordings/2026-09-17/phase5_live_dryrun_r02
```

提出物は、Kobuki PCの`src/recordings/2026-09-17_phase5_live_dryrun/`に作成された**r02セッション**と、ハンコン接続PCの上記rosbag一式。個別にアーカイブ化して名前を伝える。A・B・Dの開始／終了ログも残せると、購読開始時刻とfaultの確認に役立つ。映像側の録画が終わった後にadapterを再起動した場合、そのbagは再試験の証拠として扱わない。

## 中断条件

Preflight FAIL、青箱未検出、bagの３topic購読未完了、mock ODOMのpublisherが切替時に２以上、adapterに`future_message`などのfaultが継続、ROS domain不一致の場合は0.25 m/s送信を始めない。安全設定の緩和やhardware modeへの切替で回避しない。
