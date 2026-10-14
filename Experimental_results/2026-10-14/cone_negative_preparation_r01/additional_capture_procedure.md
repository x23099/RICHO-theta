# 負例補強と別収録評価の追加撮影

今回は**YOLO学習画像の収集だけ**。車体は停止、ハンコン・adapter・relay・keyop・rosbagは不要。
速度・停止位置・ミリ単位の距離合わせはしない。録画中の圧縮・ダウンロードは避ける。
既存の[10/12収録手順](../../2026-10-12/cone_yolo_preparation/capture_procedure.md)のカメラ専用設定を使う。

## 撮るもの：最低4本、録画合計約2分

| 順番・label | 時間 | 役割・内容 |
|---|---:|---|
| `cone_negative_train_d01` | 約30秒 | 学習用D。**赤・黄・その他色の三角コーンを両レンズから完全に退ける**。机・椅子・棚・機材・ホワイトボード脚などのある背景。10秒ごとに無理のない範囲で物の位置や向きを変え、各配置で静止する |
| `cone_negative_train_d02` | 約30秒 | 学習用D。コーンなし。コーンではない赤・黄の箱、袋、工具等（手元にあるものだけ）を中央・左右・魚眼端付近へ置き替える。コーンに似た台座・小物もあれば入れる。人が一度通ってもよい |
| `cone_negative_eval_e01` | 約30秒 | 評価用E。学習用Dと**別の位置・構図／物の配置**で撮るコーンなし映像。家具・小物を含める。Dと同じ長い動画の続きや、その別frameをEにしない |
| `cone_positive_eval_e02` | 約40秒 | 評価用E。赤コーンと黄色コーンを確実に見える状態で撮る。前半20秒は赤、後半20秒は黄（両方同時でも可）。約1～3m、中央・左右で各数秒静止。体やホワイトボード脚で隠さず台座まで見せる |

この4本は厳密な30/40秒でなくてよい。黄色コーンが用意できなければ、E02は赤だけ撮り、その旨をメモする。黄色の新規評価は未実施として扱う。
白線だけの路面も有益だが、今回は誤検出した家具・小物系を優先する。
カメラの高さ・取付角・解像度は変えない。3つ目の部屋や広いコースは必須ではない。

**データ分離：** 既存Bは引き続き検証専用。Bをほぼ同じ構図で撮り直したものをDに入れて、既存Bでの改善を独立性能として報告しない。
可能なら学習A側の背景に紛らわしい小物を置くか、Bとは異なる構図でDを収録する。
同じ部屋を使う場合は「同室・別収録の評価」と記録し、未知背景での汎化を主張しない。
Eの2本は同一評価groupとしてtrainに入れない。まず評価条件・比較モデルを凍結し、その後に確認する。後で条件を調整したら開発評価に格下げする。

コーンなしは「赤がない」ではなく**traffic_coneクラスがどちらのレンズにもない**という意味。
布や物陰に隠すだけではなく、画角外へ退ける。黄色を片方のレンズの隅に残さない。

## Kobuki PC（matunuc-NUC13ANHi5）のコマンド

従来の`~/theta_ws/src/`配置の例。cloneが`~/theta_ws/RICHO-theta`なら、そのrepoへcdだけ変更する。
必要なコード・専用設定を反映済みにする。clean-gitの確認を迂回しない。

ターミナルK1（速度0のmockのみ）：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

ros2 topic info /phase5/mock_odom
```

topicがない／Publisherが0なら以下を起動。他のPublisherが残っていれば元のターミナルで停止する。

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  "{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}"
```

ターミナルK2（録画アプリ）：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-12/cone_yolo_preparation/cone_capture_config.json \
  --record-dir src/recordings/2026-10-14_cone_negative \
  --experiment-label cone_negative_train_d01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

GUIでStart Recording→約30秒→Stop Recording→正常終了。
同じコマンドの`--experiment-label`だけを表の順にD02→E01→E02へ変え、それぞれ新しいsessionで収録する。
`--camera-frames 60`はpreflightの検査枚数で、録画秒数ではない。
違う日に撮るなら`--record-dir`の日付も当日へ変更する。最後にK1もCtrl+C。
専用JSONはAI・FFB publish・relayが0。本番v12設定は使わず、書き換えない。

## 提出

4つのsessionをtar.xzでまとめ、ファイル名／場所を知らせる。
`raw.avi`・`metadata.json`・`detections.csv`を欠かさず含める（普段どおりsessionフォルダを丸ごと圧縮でよい）。
撮った背景・物・コーンの個数、D/Eが同室か、E02で黄色を撮れたかを簡単にメモする。
解析側で原画像を抽出するので、撮影側でYOLOの枠を保存したり手でPNG化したりする必要はない。

これは候補収集。撮影だけでnegativeラベル確定・再学習合格・YOLO→FFB接続完了にはしない。
