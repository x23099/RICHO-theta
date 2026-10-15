# 次の最小確認：床Vとコーンを同じ動画で撮る

## 目的

床録画から得た有効な幾何が、別sessionのコーン録画へ完全には転用できていない。
同じ取付・同じ動画で、床基準とコーンの車体側の辺を比較し、撮影条件の差と物体代表点の問題を分ける。
新しい校正候補を収録PCへ適用する必要はない。ハンコン・実走行・rosbag・FFB出力は不要。

## 準備と撮る順番

現在の床Vマーカー7点を残してあればそのまま使う。起点と設置位置は従来どおり。
Kobukiを停止固定し、カメラの取付・高さ・向きを途中で触らない。可能なら駆動電源OFF、カメラだけ使う。
台座の辺をおおよそ車体の前後左右へ平行にしておく。ミリ単位の完璧な設置は要求しない。

**録画を止めずに**次の順で撮る：

1. コーンなし、床のVが見える状態：約10秒。
2. 中央1.30mのV先端へ、コーン台座の「車体側の辺の中央」を合わせる。手を離し、人は隠れない場所へ退いて約10秒。
3. 中央2.00mへ、同じく「車体側の辺の中央」を合わせて約10秒。
4. コーンをどけ、最初と同じ床Vが見える状態を約10秒。

移動・設置の時間は何秒かかっても構わない。その間も録画を続けるので、全体1～2分程度でよい。
今回は左右条件や0.80mを撮り直す必要はない。コーンを動かす人はKobukiやカメラに触れない。
時刻や動かし方が完全に揃う必要はなく、順序を守って撮り、実際の辺の位置が少し違えばその距離をメモする。

## Kobuki PC：ターミナル2つ

`matunuc-NUC13ANHi5`で実施。リポジトリが`~/theta_ws`の場合。
両ターミナルで：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

K1：`ros2 topic info /phase5/mock_odom`で既存publisherがないことを確認。残っていれば元のターミナルで停止してから、停止模擬ODOMを送る：

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  '{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}'
```

K2：既存設定でカメラを起動する。Git差分がある場合は内容を保存・整理し、clean検査を迂回しない。

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-15_floor_cone_same_pose \
  --experiment-label floor_cone_same_pose_r01 \
  --camera-device 0 \
  --camera-width 1280 \
  --camera-height 720 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

Preflight PASS後にGUIで録画開始し、上記4段階を同じ録画に収める。
`--camera-frames 60`は事前確認枚数で録画時間ではない。終わったら録画停止・アプリ終了、K1もCtrl+Cで停止。

## 提出

session一式の圧縮ファイルと「床→中央1.30m→中央2.00m→床」の順で撮った旨を伝えればよい。
高さ59cm・マーカー位置・取付に変化があればその内容を追記。画像加工やpixelラベルは不要。
この撮影は校正/検出の確認専用で、TTC/実機FFBの試験ではない。
