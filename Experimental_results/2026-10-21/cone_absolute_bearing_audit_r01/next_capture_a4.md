# 次の最小追加観測：前方魚眼のA4格子1録画

今回の診断で、絶対視線方向とレンズ中心/内部モデルの影響を中央点だけでは分離できないことを確認した。**別の距離でコーンを撮り足すより、独立にK/Dを取得する観測を優先**する。実校正済みのK/Dを別途入手できれば、その情報のモデル・解像度・対象レンズを確認する手段でもよい。

## 準備・撮影

1. 既存の[A4 PDF](../../2026-10-19/fisheye_intrinsic_target_a4_r01/checkerboard.pdf)を、A4横・100%・実際のサイズで印刷する。A3版を縮小印刷しない。対象は10×7マス、内側交点9×6、設計1マス20mm。[spec](../../2026-10-19/fisheye_intrinsic_target_a4_r01/board_spec.json)
2. 100mmの確認線とマスの縦横を測り、**印刷後の1マスの実測mm**をメモする。紙を平らな硬い板へ密着させ、余白を残す。
3. カメラ・Kobukiは静止。高さ・取付・解像度・カメラモードはそのまま。左の前方レンズに全格子が入り、交点が大きく鮮明に見える距離にする。ボードまでの距離を正確に測る必要はない。
4. 中央・上下・左右・斜め、近い/遠い、左右/上下へ傾けた状態を含め、**30～40程度の異なる姿勢**を作る。各姿勢で約2秒静止し、連続1本・2～4分程度。全て正面向きの平行移動だけにはしない。端で格子を切らず、手で交点を隠さない。
5. 提出物はsessionの録画一式、A4使用のメモ、1マスの実測mm。コーン、床の距離7点、GPU学習、ハンコン、走行、rosbagは不要。

A4版は今回新規生成・上書きしていない。元の[詳細手順](../../2026-10-19/fisheye_intrinsic_preparation_r01/capture_procedure.md)の撮り方を使える。そこでの解析用`--board-spec`だけはA3版ではなく上記A4 specへ合わせる。

## 起動：Kobuki PC（matunuc-NUC13ANHi5）のみ

実機は動かさない。ハンコン接続PC・adapter・relayは起動しない。コードの各PCへの反映は通常どおり先に済ませる。preflightのGit検査は迂回しない。

以下はリポジトリ直下が`~/theta_ws`の場合。`~/theta_ws/RICHO-theta`の場合は`cd`だけ読み替える。

両端末で：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

端末A：`ros2 topic info /phase5/mock_odom`で既存publisherがないことを確認し、停止状態だけを送る。実機`/odom`へ模擬値を送らない。

```bash
ros2 topic pub -r 30 /phase5/mock_odom nav_msgs/msg/Odometry \
  '{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}'
```

端末B：

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-21_intrinsics \
  --experiment-label front_fisheye_intrinsic_a4_r01 \
  --camera-device 0 \
  --camera-width 1280 \
  --camera-height 720 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

GUIで録画開始→格子を提示→録画停止。端末Aの送信もCtrl+Cで停止。`--camera-frames 60`は事前検査の枚数で録画時間ではない。実施日が変わる場合は保存日・labelを合わせる。

この起動引数はローカルの`--dry-run`で展開確認しただけで、実カメラやROSを起動していない。FFB/AI/relay無効の既存撮影設定を使い、過去の校正候補JSONを本番設定として渡さない。

取得後は、既存ツールで角抽出→姿勢数/分布の確認→K/D候補→fit未使用姿勢での検証→既存床/コーンへの照合、と進める。K/Dを得ただけで床TF・距離が完成したとは扱わない。仮の7°補正を先に導入しない。
