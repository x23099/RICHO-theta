# 中央2.00m：白紙→コーン→白紙の最小確認

目的は、明瞭な床基準とコーン台座の近側の辺を**同じ撮影状態**で対応付けること。
中央2.00mの1か所・連続録画1本だけ。白紙7点、左右、1.30m、走行、ハンコン試験は不要。
この1本だけで全域の校正/TTC/FFBが完成するという意味ではない。

## 1. 配置

- これまでと同じカメラ・取付・解像度・収録設定を使う。車体を停止固定する。
- 原点は従来どおりカメラ直下/Kobuki中心。中央X=0、前方Z=2.00mの床位置を決める。
- 以前見えると確認したA3用紙2枚を使用し、平らで角が識別できる状態にする。
- **白紙は車体に近い辺の左端の角**をこの床位置へ合わせる。紙の中心や辺中央ではない。
- **コーンは車体に近い台座辺の中央**を同じ床位置へ合わせる。コーン中心/台座中心ではない。
- 台座は床へ直接置く。紙はコーンの下に残さず、一旦どける。
- 紙をどけても位置を失わないよう、紙の外側の目印や巻尺等で同じ床位置を再現する。
  小さな目印を画像から精密に読むのが目的ではない。読取り対象は大きな白紙の角。
- 完璧なミリ合わせは不要。実際に分かる設置距離が異なればその値をメモする。
  高さ59cm・原点・台座寸法37.5cmは確認済みなので、再測定を要求しない。

## 2. 起動：Kobuki PCのみ

`matunuc-NUC13ANHi5`でターミナルを2つ使う。ハンコン接続PC、hardware adapter、走行用driver/keyopは起動不要。
車体を動かさず、カメラ録画だけを行う。ODOMは事前確認用の停止模擬データで、実走行データとは扱わない。

両ターミナルで既存の環境を準備：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

ターミナルA：`ros2 topic info /phase5/mock_odom`でpublisherが残っていないことを確認。
残っていれば元の送信ターミナルで停止してから、速度0だけを送る。

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  '{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}'
```

ターミナルB：既存のFFB/AI/relay無効の収録設定で起動する。
白紙から作ったオフライン候補JSONは指定しない。

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-19_paper_cone_same_pose \
  --experiment-label paper_cone_center_z2p00_r01 \
  --camera-device 0 \
  --camera-width 1280 \
  --camera-height 720 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

repoが`~/theta_ws/RICHO-theta`にあるPCでは、両端末の`cd`だけ実際のrepoに合わせる。
仮想環境も既存の動作したものを使い、新規構築しない。
preflightのGit検査が止まったら差分を確認・整理し、`--allow-dirty-git`等で迂回しない。
`--camera-frames 60`はカメラ事前検査の枚数で、録画時間ではない。

設定ファイルの高さ表示0.58mは以前の記録値を維持したもの。
実測59cmでの比較はオフラインで行うので、今回だけ画面から0.59へ変更しない。
pitch/roll/中心/半径・カメラ内部のモードも途中で調整しない。

## 3. 連続録画の順番

Preflight PASS後、GUIで白紙の指定角が見えることを確認して録画開始。
動かすのは紙とコーンだけ。各静止区間は**手を離し、人が画角を塞がなくなってから約15秒**。

1. **白紙・前**：指定した手前左角をX=0/Z=2.00mへ合わせて15秒。
2. **コーン**：紙をどけ、同じ床位置へ台座の車体側辺中央を合わせて15秒。
3. **白紙・後**：コーンをどけ、同じ紙の同じ角・向きで元の床位置へ戻して15秒。

**この3区間と設置作業を、録画を止めず1本へ入れる。**
移動に何秒かかってもよい。全体1～2分程度でよく、急いで設置する必要はない。
カメラアプリやカメラ接続を区間ごとに再起動しない。車体/カメラ/固定部に触れない。
紙の角が見えない場合は、その場で取付角や校正sliderを変更せず、見えない旨を知らせる。

最後の白紙15秒まで撮ったらGUIで録画停止し、アプリ終了。
ターミナルAの模擬ODOMもCtrl+Cで停止する。

## 4. 提出

- 保存先：`~/theta_ws/src/recordings/2026-10-19_paper_cone_same_pose/`配下の新しいsession。
- そのsessionをmetadata/raw/CSV/処理動画ごと、いつもどおり圧縮して提出する。
- 「白紙→コーン→白紙で撮影」、指定値と違う実測値があればそのメモを添える。
- rosbag、ハンコンログ、画像の加工、pixelラベルは不要。

本手順のCLIはローカルの`--dry-run`で検証。収録PCでのカメラ/ROS/実機試験はまだ行っていない。
