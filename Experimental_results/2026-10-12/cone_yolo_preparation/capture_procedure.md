# 赤コーン学習用録画：最初の収録（2026-10-12）

まず学習・検証・最終評価を分けた**3つの収録ブロック、各約60秒**を作る。初回データの出発点であり、3本で汎化性能を保証するものではない。1本をframe番号で3分割してtrain／val／testへ入れない。

| label | split/group例 | 内容 |
|---|---|---|
| `cone_train_block_a_r01` | train／train_block_a | 主に学習用。赤コーンあり約45秒、なし約15秒 |
| `cone_val_block_b_r01` | val／val_block_b | 別の位置・背景や撮影ブロック。学習用とは別収録 |
| `cone_test_block_c_r01` | test／test_block_c | さらに別収録。初回条件を凍結してから評価に使う |

## 配置・安全

- Kobukiは固定・停止。操縦／keyop・hardware adapterは起動しない。可能なら駆動電源を切り、カメラだけ使う。
- コーンあり区間では、手で置き直しながら距離約0.7～3.0 m、中央・左・右、向き・背景の違いを含める。ミリ単位の距離・速度合わせは不要。これは学習画像を集める試験で、TTC評価ではない。
- 人が移動してもよいが、置いたコーンだけが見える場面も残す。コーンと人物・背景が常にセットになる偏りを避ける。
- 可能なら複数コーン・部分遮蔽も少し含める。初回から難条件をすべて集める必要はない。
- コーンなしでは**前後両レンズから**コーンを退ける。他の赤い物体や白線・影があってもコーンなしと分かる場面を残す。
- カメラの高さ・取付角を毎回変えない。別背景が難しくても別収録ブロックとして記録し、「未知背景で評価済み」とは呼ばない。
- ダウンロード・圧縮・同期を録画中に行わない。後でラベル付けしづらいほど大きくブレる操作は避ける。

## Kobuki PC：環境と停止mock ODOM

ホストは`matunuc-NUC13ANHi5`。新規設定を含むカメラ側リポジトリを取得済みにする。以下は従来の`~/theta_ws/src/`配置を想定。`~/theta_ws/RICHO-theta`へcloneしている場合はcdだけ読み替える。

K1／K2の各ターミナル：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

K1で、他のmock publisherがないことを確認：

```bash
ros2 topic info /phase5/mock_odom
```

topicが未存在なら正常。Publisherが残っていたら元ターミナルで停止してから、速度0だけを起動：

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  "{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}"
```

実機`/odom`や`/cmd_vel`へ模擬速度を送らない。FFB interfaceのsource、ハンコンPC、adapter、relay、bagは今回不要。

K2：

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-12/cone_yolo_preparation/cone_capture_config.json \
  --record-dir src/recordings/2026-10-12_cone_dataset \
  --experiment-label cone_train_block_a_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

clean git・preflightを迂回しない。GUIで録画開始し、コーンあり約45秒→なし約15秒、録画停止、アプリ正常終了。時間は目安で厳密な60秒に合わせる必要はない。`--camera-frames 60`は事前検査枚数で、録画時間ではない。

場所や背景を変え、labelだけ`cone_val_block_b_r01`、`cone_test_block_c_r01`へ変えて同様に収録。K1の停止mockは3本の間そのままでよい。終わったらK1もCtrl+Cで停止する。

FFB publish・relay・AIは専用JSONで0にしている。本番v12を直接書き換えていない。学習画像の収集でハンコンの振動や車体移動は不要。

## 提出物

3本のsessionをまとめた録画アーカイブと、次をメモして解析PCへ渡す：

- 各sessionのtrain／val／testの指定と収録block。
- 場所・背景・照明の違い（同じ場合はその旨）。
- コーンの個数、部分遮蔽や他の赤い物体の有無。

画像のframe抽出は解析側でできる。撮影中にYOLOの枠付けをする必要はない。提出後、[学習データ作成・ラベル手順](README.md)へ進む。rawの姿が違うGPU PCのwebcamや一般画像だけで学習した結果を、THETA映像へそのまま保証しない。
