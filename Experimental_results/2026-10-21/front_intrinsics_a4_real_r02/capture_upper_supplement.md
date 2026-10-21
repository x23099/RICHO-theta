# r02を活かす補足撮影：前方画像の上側だけを大きく

## 撮り直す範囲

**r02の54候補は残す。全周を回る・30姿勢全てやり直す必要はない。** 今回は、左の円の「上中央・左上・右上」に大きく読める板を追加する。右の円は別レンズなので今回は使わない。

r02は大きく映ったときの紙の位置が中央の横長の帯へ集中した。上側へ持っていったときは格子が小さく、今の検出条件に足りなかった。足りないのは枚数ではなく画像内の上下分布。

## 撮影の要点

1. 同じ20 mm格子・同じ平板・同じカメラ取付、1280×720・MJPG30 fpsを維持。カメラを上へ傾けて板を映すのではなく、**カメラは固定したまま板を上へ移動**する。ハンコン・走行・FFB・rosbagは不要。
2. 生画像の**左の円だけ**を見る。板を腰の高さではなく胸付近へ持ち上げ、板をカメラへ少し下向きに向ける。身体ごと背面へ回らない。距離は厳密に測らず、格子を大きくするため近づく。
3. 上中央→左上→右上で、各3～4通り、正対・左右への軽い傾き・上下への軽い傾きを作る。各2～3秒静止し、移動中も録画を継続。**追加10姿勢程度、約40～60秒を目安**とする。検出・校正成功の保証枚数ではない。
4. 板の全マスと白い余白を左の円内へ収める。黒い縁へ押し込まず、切れるなら少し中央へ戻す。手・反射・動きによるブレで格子を隠さない。下側を車体で隠して無理に撮る必要はない。
5. 画像位置の目安：元1280×720画像で、**左の紙の中心がy≈170～220 px**、上側の内角がy≈120～140 px付近まで届くようにする。これは設置距離や紙の物理高さの指定ではなく、表示画像上の目安。格子1マスをおよそ10 px以上に見せたい。単に上へ小さく映すだけでは不足する。

数値目安の根拠：既存train角群の下端y=394.823 pxを使う場合、縦範囲252 pxを確保する上端はy≤142.823 px。格子中心の上段区画はy<240 px。ただし最終train/validation分割、ブレ、姿勢分布、ソルバーの検証が別に必要であり、画素目安到達だけで内部校正完了にはならない。

## コマンド（Kobuki PC：matunuc-NUC13ANHi5）

repo直下が`~/theta_ws`の場合の例。別PCで`~/theta_ws/RICHO-theta`に配置している場合はcd先を合わせる。作業内容のGit反映・pullは通常どおり先に済ませ、clean Git検査を迂回しない。

各端末で：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

端末A：停止模擬ODOMが既に起動中なら二重起動しない。実機`/odom`には送信しない。

```bash
ros2 topic info /phase5/mock_odom
```

Publisherが0またはtopicなしのときのみ：

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  '{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}'
```

端末B：

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-21_intrinsics \
  --experiment-label front_fisheye_intrinsic_a4_upper_r03 \
  --camera-device 0 \
  --camera-width 1280 \
  --camera-height 720 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

GUIで録画開始→上側の追加姿勢→録画停止。終わったら端末AもCtrl+C。`--camera-frames 60`は録画枚数ではなく事前検査用。実施日が変わったら保存先の日付を変更する。

AI・FFB・relayを無効にした既存の収録設定を使う。コマンドは解析PCで`--dry-run`の展開確認のみ実施し、実カメラやROS送信は起動していない。

今回の録画にNo Signal表示があったため、開始時・途中に生画像が正常なことも見る。ケーブルを抜き差しした場合や撮影モード・取付が変わった場合は、そのことだけ知らせてほしい。内部設定が変わっていないとは自動で仮定しない。

提出は追加session一式のtar.xzだけでよい。床やコーンの距離録画を新たに撮る必要はない。
