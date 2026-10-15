# コーン距離変換の切り分け：実カメラ床面基準の収録

今回必要なのは**実THETAで床のテープ十字だけを撮る、静止約10秒の動画1本**。
箱・コーン、ハンコン、adapter、relay、rosbag、走行は不要。
10/8の既存収録設定をそのまま再利用する。今回のコーン6録画とカメラ幾何9項目が一致し、AI・FFB publish・relayは無効であることを確認した。

準備時点：ユーザーから実カメラ床面基準は未撮影との回答があり、実測に基づく床面誤差の評価は未実施だった。
WebSimの床面録画、配置予定値、コーン台座のassistant目視点を、実測された床面正解へ置き換えない。

同日追記：実カメラの録画を受領し、7点の設置とレンズ高さ59cmのユーザー確認を得た。[床V字基準の固定幾何診断](../cone_floor_reference_real_r01/README.md)を実施済み。以下は収録手順の記録であり、同じ録画の再提出を求めるものではない。

## 1. 配置と実測

Kobukiを固定して停止。カメラの高さ・傾き・取付位置は変えない。
操縦ノードやhardware adapterは停止し、可能ならKobukiの駆動電源を切ってカメラだけ使う。

従来どおり**カメラ直下/Kobuki中心の床点**を起点とする。右がX正、前がZ正。
薄い白黒等のテープ十字を、下表の目安へ置く。十字の中心が測定点。
GUIの推定位置ではなく、メジャーと車体の物理的な正面方向を基準に測る。

| ID | X目安 [m] | Z目安 [m] | 用途 |
|---|---:|---:|---|
| C080 | 0 | 0.80 | 近距離診断 |
| C130 | 0 | 1.30 | 中距離診断 |
| C200 | 0 | 2.00 | 遠距離診断 |
| L130 | -0.40 | 1.30 | 左右差診断 |
| R130 | +0.40 | 1.30 | 左右差診断 |
| H100 | 0 | 1.00 | 追加確認用・将来の補正fitには使わない |
| H160 | 0 | 1.60 | 追加確認用・将来の補正fitには使わない |

**7点を同時に置ければ録画は1本でよい。** まず上5点を優先。追加2点が重なって識別しづらい場合は無理に置かず、その旨を伝える。
実際の座標が分かれば多少ずれて構わない。ミリ単位の完璧な設置・停止は不要。
0.40mと1.30mの斜距離ではなく、右左X・前後Zの成分を測る。
テープは浮かせず、床の反射や模様と見分けられる色・大きさにする。遠い点も中心を判別できるようにし、手前の点で奥の点を隠さない。
距離を合わせる目的で画像上の位置やカメラ取付を調整しない。

[measurement_notes.md](measurement_notes.md)へ、各中心の**実測X/Z**と測り方を残す。
加えて、カメラ光学位置の目安から床までの高さを、取付を変えずに測る。レンズへメジャーを接触させない。
設定の0.58mを実測値として写さない。測れない項目は未測定と残す。
傾きは無理に測定・変更しなくてよい。「変更なし、実角度未測定」でよい。

## 2. Kobuki PCでの準備

使うPCは **matunuc-NUC13ANHi5**。ハンコン接続PCは使わない。
リポジトリが従来どおり`~/theta_ws`にある想定。clone先が違う場合は`cd`だけ読み替える。
K1/K2両ターミナルで実行：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

K2で確認：

```bash
git status --short
test -f Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json
```

Git確認は未コミット差分がないこと。差分があれば内容を確認・保存してから収録する。
`--allow-dirty-git`で迂回したり、差分を捨てたりしない。既存10/8設定を使うため、今回の文書だけのために収録PCの設定を書き換える必要はない。

## 3. K1：停止した模擬ODOM

既存の模擬publisherを確認：

```bash
ros2 topic info /phase5/mock_odom
```

トピックなし、またはPublisher count=0なら次へ。既存publisherがあれば元ターミナルで停止する。
停止速度を送信し、K1はそのままにする：

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  '{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}'
```

これは実機の`/odom`や`/cmd_vel`へ送るコマンドではない。車体を動かさない。

## 4. K2：カメラ起動・録画

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-15_floor_reference_real \
  --experiment-label floor_reference_real_r01 \
  --camera-device 0 \
  --camera-width 1280 \
  --camera-height 720 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

1. Preflight PASS後、GUIで前方raw画像に全マーカーの中心が見えるか確認する。
2. 録画開始。マーカーを隠さない位置へ移り、静止状態で約10秒記録する。
3. 録画停止→アプリを正常終了。
4. K1の模擬ODOMをCtrl+Cで停止する。

`--camera-frames 60`は事前確認の枚数であり、録画時間ではない。録画開始・停止はGUIで行う。
録画中にコーンを置く、人が点の上に立つ、Kobukiを動かす必要はない。
青箱検出表示がなくても今回は問題ない。目的は無加工raw映像の床点と実測座標の比較である。

## 5. 提出するもの

- 今回のsession一式の`.tar.xz`（`raw.avi`、`metadata.json`、`detections.csv`等）。保存先は上記`src/recordings/2026-10-15_floor_reference_real/`。
- 実測X/Z、カメラ高さ、取付変更なしのメモ。チャットへ数値を書いてもよい。
- 配置写真があれば元画像のまま。なくても動画と実測メモがあれば進められる。

画像への点の描き込み・切抜き・リサイズは不要。pixelやframeは解析側で指定できる。
どの点か迷う場合は、推定値から逆算せず、対応を確認してから評価する。

## 6. 解析側と検証の範囲

[floor_points_template.csv](floor_points_template.csv)は実測値/pixel/frameを空欄にした入力雛形。
[point_layout.csv](point_layout.csv)の予定値を、測定した正解として自動転記しない。
追加確認用H100/H160は事前に用途を分けたもので、将来の補正が学習に使っていない点へ適用できるかを確認するために残す。
同じカメラ・同じ1本内の点であり、別日・別環境に対する完全な独立試験ではない。

既存のオフライン評価器を再利用する：

```bash
python3 src/evaluate_floor_reference.py \
  --session /path/to/floor_reference_real_session \
  --points /path/to/measured_floor_points.csv \
  --output-dir Experimental_results/2026-10-15/cone_floor_reference_real_r01
```

実測前の現時点ではこの評価を実行しない。係数fit・本番configの修正・ROS/FFB試験もまだ行わない。
原動画と無加工PNGの画素対応、metadataのdeviceと幾何、実測メモとの対応を確認してから残差を出す。
今回の用意は収録準備までであり、距離精度PASSや原因確定を意味しない。
