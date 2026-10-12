# 床面基準点の静止撮影手順（2026-10-08）

目的は、前回の箱の色検出とは独立に固定の距離変換を確認すること。前回の箱なし／箱あり3距離を丸ごと繰り返す手順ではない。**薄い床マーカー5点を同じ画面へ置き、静止動画を1本・約10秒**収録すればよい。学校へ行けない場合は、ここからは未実施として待つ。

## 1. 準備・実測

1. Kobukiを固定して停止する。操縦・keyop・hardware adapterは起動しない。可能なら駆動電源を切り、カメラだけ使う。
2. カメラ取付は前回から動かさない。カメラ光学位置の目安から床までの高さを、変更せずに測って記録する。レンズにメジャーを接触させない。傾きの実測が難しければ未測定と残す。
3. カメラ直下の床点を起点に、Kobukiの物理的な正面方向に前方の線を決める。GUIの箱位置や投影値を基準に線を決めない。
4. 薄い白黒等のテープ十字を床へ貼る。中心が実測点。厚い物体や青箱そのものは床基準にしない。反射の少ない床で、浮き・段差を避ける。
5. 配置目安は下表。実測値と不確かさは[実測メモ](measurement_notes_template.md)へ別途記入する。予定値から数cmずれても、実測座標が分かれば診断に使える。

| ID | X目安 | Z目安 |
|---|---:|---:|
| centre_near | 0 | 0.90 m |
| centre_middle | 0 | 1.10 m |
| centre_far | 0 | 1.30 m |
| left_middle | −0.20 m | 1.10 m |
| right_middle | +0.20 m | 1.10 m |

箱はこの撮影ではどけておく。全5点の中心が前方raw画像に見えることを確認する。床面までの鉛直高さと、床上のX/Zを混同しない。マーカー幅は中心を画像で数pixel程度に特定できる大きさにし、全点が見えなければ無理に10秒撮らず配置・可視性を先に確認する。

## 2. Kobuki PCだけで起動

ホストは`matunuc-NUC13ANHi5`。以下は従来どおりリポジトリが`~/theta_ws`にある想定。`~/theta_ws/RICHO-theta`へcloneしている場合は`cd`だけ読み替える。必要な新規ファイルをユーザーのGit操作で反映し、各PCで取得してから使う。clean git検査を迂回しない。

K1／K2の両ターミナルで最初に実行：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

FFB interfaceのsourceは今回の設定では不要。ハンコン接続PC、adapter、relay、rosbagも不要。専用設定はFFB publish／relay／AIを無効にした別ファイルで、本番v12を書き換えていない。

K1：停止模擬ODOM。別のmock publisherが残っていないことを確認してから起動する。

```bash
ros2 topic info /phase5/mock_odom
```

存在しない場合は正常。Publisherが残っている場合は元ターミナルで停止してから次へ進む。

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  "{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}"
```

これは`/cmd_vel`や実機`/odom`へ送らず、車体を動かさない。K1は起動したまま。

K2：

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-08_floor_reference \
  --experiment-label floor_markers_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

preflightがPASSしてGUIが開いてから、全5点が見えることを確認する。マーカーを隠さない場所へ移り、GUIで録画開始→約10秒→録画停止→正常終了。`--camera-frames 60`は事前確認枚数で録画時間ではない。終わったらK1をCtrl+Cで停止する。

## 3. 提出

撮影したsession（`raw.avi`、`metadata.json`、`detections.csv`等）をこれまで同様にアーカイブして解析PCへ持ってくる。加えて実測メモを渡す。配置写真があればそのまま添付する。画像へ注釈・切抜き・リサイズを加える必要はない。

録画とメモが揃ったら、解析側で元画像からmarker中心を独立指定し、[オフライン評価手順](README.md)を実行する。pixelの選択を投影誤差へ合わせて調整しない。これで箱の下端の検出と床面投影を切り分ける材料が得られるが、1本だけで全距離精度や本番採用を合格にするものではない。
