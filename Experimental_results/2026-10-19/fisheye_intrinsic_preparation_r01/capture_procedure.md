# 前方魚眼・内部校正用の最小収録

## 何を撮るか

**コーンや床の2mをもう一度撮るのではない。印刷した格子を手持ちで動かす、連続1録画。**
カメラ・Kobukiは静止し、取付・解像度・カメラモードを変えない。走行・ハンコン・FFB・rosbagは不要。
距離の正解ラベルや床への印は不要。レンズの歪みを測るための撮影であり、取付TFの測量は別。

## 1. 印刷物の準備

1. [A3校正PDF](target_a3/checkerboard.pdf)を**A3横・実際のサイズ100%**で印刷する。
   「用紙に合わせる」「ページを縮小」は使わない。黒白の部分は300×210mm。
2. 100mmの確認線と、黒白の**1マス約30mm**を定規で測る。
   厳密に30.00mmでなくてもよい。実測値（例29.8mm）をメモする。
   横と縦のマス寸法が明らかに違う、欠ける、拡大縮小が歪む場合は印刷を確認する。
3. 紙を段ボール・平板などの**平らで硬い面**へ密着させる。
   曲がった紙を手で持つ、折り目、光沢フィルムによる強い反射は避ける。黒白の周囲の余白を切らない。
4. 格子は**10列×7行のマス、9列×6行の内側交点**。後から設定へ10×7を指定しない。

A3印刷ができなければA4版を生成できる。A3をそのままA4へ縮小するのではなく、次を使用。
この場合はA4横100%、1マス約20mmで、同じ交点数。生成済みディレクトリへの上書きは拒否する。

```bash
python3 src/prepare_fisheye_calibration.py board \
  --paper A4 \
  --output-dir Experimental_results/2026-10-19/fisheye_intrinsic_target_a4_r01
```

## 2. 起動（Kobuki PC：matunuc-NUC13ANHi5）

既存と同じ2端末構成。ハンコン接続PCでは起動しない。
以下はrepo直下が`~/theta_ws`の場合。実際に`~/theta_ws/RICHO-theta`へ配置したPCでは`cd`だけ合わせる。
作業内容のGit反映・各PCでのpullは通常どおり先に済ませる。Git検査を迂回しない。

両端末で環境準備：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

端末A：既存の`/phase5/mock_odom`送信が残っていないことを確認してから、停止模擬ODOMを送る。
実機`/odom`へは送らない。

```bash
ros2 topic info /phase5/mock_odom
```

Publisherが0、またはtopicが存在しなければ以下。送信中のものがある場合は元の端末で止めてから開始する。

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  '{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}'
```

端末B：これまでのAI/FFB/relay無効設定で起動する。校正候補JSONは指定しない。

```bash
python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json \
  --record-dir src/recordings/2026-10-19_intrinsics \
  --experiment-label front_fisheye_intrinsic_r01 \
  --camera-device 0 \
  --camera-width 1280 \
  --camera-height 720 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

`--camera-frames 60`は事前検査の枚数であり、録画時間ではない。
このコマンドはローカルで`--dry-run`の引数展開を確認しただけ。実カメラ起動は未実施。

## 3. 撮影のやり方（連続2～4分程度）

1. GUIで録画開始。**生画像の左の円（これまで正面として使ったレンズ）**へ格子を見せる。
   右の円は今回校正しない。BEVではなく元画像で、全マスと白い余白が収まることを確認する。
2. レンズからおおよそ35～80cm程度を目安に、全格子が入り、マスが見分けられる距離へ調整する。
   実測距離の正確さは不要。小さ過ぎる場合は近づける。近過ぎて切れるなら離す。
3. 次のように**30～40程度の違う姿勢**を作り、それぞれ2秒ほど静止する。
   動かす間も録画は止めない。全体が1本でよい。

   - 中央で近い/遠い・少し上下：4姿勢程度。
   - 左右・上下・斜めの8方向で、正対に近い向きと少し傾けた向き：各2姿勢、計16程度。
   - 中央や周辺で、左右/上下へ15～35°程度傾ける・少し斜めに回す：追加10姿勢程度。

4. 全て正面向きのまま平行移動するだけにしない。**位置・大きさ・傾き**を変える。
   円の中央だけに固めず周辺も撮るが、黒い画角外や円の縁へ格子を切らして押し込まない。
5. 手は格子や交点を隠さないよう板の端を持つ。人の顔・身体が入ってもよいが、格子は隠さない。
6. 録画停止して終了。端末Aの模擬ODOMもCtrl+Cで停止する。

同じ姿勢を長く撮っても独立校正点として水増ししない。
抽出後20視点未満、姿勢や位置が偏る、ブレや反射で読めない場合は候補作成を保留する。
30～40姿勢は余裕を見た撮影目安で、必ず1回で全検査に通る保証ではない。

## 4. 提出するもの

- 今回のsessionをいつもどおりraw/metadata/CSV等まとめて圧縮したもの。
- **印刷した1マスの実測寸法**。A3/A4のどちらを使ったか。
- 気付いた撮影上の問題があれば、そのメモ。

ピクセル座標の手入力、モデル学習、ハンコンログ、画像加工は不要。
取得後に、レンズ内部K/Dを固定したうえで既存の床・コーン録画との整合性を再評価する。
今回ボードから求まる各姿勢を、そのまま床に対するカメラTFとして使わない。

## 解析側のコマンド（録画受領後。撮影時には不要）

`--video`にはsession内の**raw.avi**を指定。tar.xz/BEV/detection動画は指定しない。
以下の`/path/to/session/raw.avi`は実際のパスへ置き換える。
出力先は新しい名前を使う。抽出・候補作成はCPUで実行できる。

```bash
python3 src/prepare_fisheye_calibration.py extract \
  --video /path/to/session/raw.avi \
  --board-spec Experimental_results/2026-10-19/fisheye_intrinsic_preparation_r01/target_a3/board_spec.json \
  --sample-every 15 \
  --save-raw-frames \
  --output-dir Experimental_results/2026-10-19/intrinsics_front_extract_r01
```

原PNGと検出角の一覧を確認後にfitする。`30.0`は実測値へ置き換える。A4なら通常約20mm。

```bash
python3 src/prepare_fisheye_calibration.py fit \
  --observations Experimental_results/2026-10-19/intrinsics_front_extract_r01/observations.json \
  --measured-square-mm 30.0 \
  --output-dir Experimental_results/2026-10-19/intrinsics_front_candidate_r01
```

生成された`intrinsics_candidate.json`はオフライン候補。本番configへコピーしたり起動引数へ渡したりしない。
