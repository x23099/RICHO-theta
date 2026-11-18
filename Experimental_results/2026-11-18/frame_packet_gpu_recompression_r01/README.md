# GPUPC：保存画像のpacket再圧縮・測距比較（予備試験）

**r02提出の解析まで完了。[最新結果報告](submission_report_r02.md)。ROI補正後は双方10/10で数値距離、前後差約3.0cm。packetの支持点・幾何を含むreceiver段階は中央値15.980ms/最大17.271ms。同じ画像の再実行は不要。次は別の既存保存画像へ比較を広げ、その後に実通信の共存負荷を確認する。追加撮影/走行はまだ不要。**

r01のROI案内不一致と事後診断は[前回結果](submission_report_r01.md)に保持。下記のr01/r02 GPUコマンドは実施済み履歴であり、今すぐ繰り返す指示ではない。

カメラ・matsunuc・映像送受信・走行・画面録画・G923は使わない。確認済みの保存native PNGを指定し、元画像と現行VP8 packet再圧縮後へ同じ既存CUDA YOLO/支持点/距離処理を適用する。**実機や既存runtimeの起動手順ではない。**

[実装計画](implementation_plan.md)、[実験runner](run.py)、[回帰試験](../../../tests/test_frame_packet_gpu_recompression.py)。今回srcは変更しない。Git commit/push/pullはユーザー操作に委ねる。

## 開始条件

ユーザー報告：GPUPCは `/home/hsr/yopi_ws/RICHO-theta`、Pythonは `./yolo-env/bin/python3`、重みは `/home/hsr/Downloads/cone_distance_v03.pt`。PyTorch 2.7.1+cu118 / PyAV 16.1.0 / OpenCV 5.0.0。CUDA unknown errorからGPUPC再起動後にCUDA True・RTX 4070 Laptop GPU・GPU tensor計算1.0へ回復した。原因やサスペンドとの関係を特定したわけではない。

まず今回追加したrunnerとテスト/資料をGit経由でGPUPCへ反映する。既に反映済みならpatchを重ねない。次の確認でrun.pyがない場合は実行へ進まない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
ls -l Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py
```

## GPUPC実行コマンド

以下は実施済みr01の履歴。再実行しない。現在の次の操作は後述r02。

下は所在確認済みの11/16 pin 5186だけを使う最初の予備試験。1枚で6 warmup＋20測定、10対比較。通常は短時間だが、CUDA初期化やmodel初回起動を含む所要時間を事前保証しない。実行中は追加の学習/YOLO/受信処理を起動しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py \
  --image recordings/2026-11-16/body_guard_live_r01/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount \
  --output-dir recordings/2026-11-18/packet_recompression_gpu_r01 \
  --archive /home/hsr/Downloads/packet_recompression_gpu_20261118_r01.tar.xz
```

最後に `state: complete`、`image_count: 1`、`measured_samples: 20`、`paired_samples: 10` が表示され、Downloadsへarchiveができる。そのarchiveを提出する。GPU画面録画は不要。失敗したら表示されたERROR/tracebackとsummaryを確認し、同じ出力先への再実行や既存結果の削除をしない。再試行は原因確認後に両方のr01をr02へ変更する。

モデルは既存設定のSHAに一致するローカルcheckpointのみを許可。CUDA不能なら停止し、CPUへfallbackしない。依存・driverの導入や更新は行わない。

## 何を比較するか

- 原画像PNG SHA/復号画素SHA、入力寸法1280x720、weights/config/profile/各code SHAと環境version。
- 各反復で新たにYOLO検出する。保存bboxを流用しない。original→packet→packet→originalのABBAを5反復し、warmupは除外。原画像側の検出/距離の反復変動も記録。
- 検出枠・支持点・支持観測・採否・理由の変化。双方数値がある組だけ距離差を集計し、一方保留を誤差0として扱わない。
- encode、decode/validate/copy、CUDA同期込みpredict、支持点/幾何のwall時間・CPU時間。PyTorch allocatorのpeak allocated/reserved bytes。GPU全体使用率は測らない。
- `receiver_stage_ms` はdecode/検証/copy＋predict＋支持点/幾何。100/200msを超えた件数も全件集計。sender encode時間は別で、同一GPUPCでのcodec試験にすぎず機体側負荷ではない。全probeのCPUcore相当/RSSにはwarmupや診断用hash/画素差/ログも含む。

採否/数値が変わっても自動で成功/失敗やライブ採用と決めない。completeは「試験完走」であり精度承認ではない。20試行が同じ1枚でも、20種類の場面を評価したことにはならない。

## 保存物と制約

`summary.json`、全測定の`samples.jsonl`、全対の`pairs.jsonl`、run専用Ultralytics設定だけを新規保存し圧縮する。元画像/重みを変更・圧縮物へ同梱しない。圧縮復号後の画像はメモリ内だけで、画像の注釈/切抜き/リサイズ/再保存なし。YOLO内部の従来前処理は既存predictorそのまま。

幾何比較は意図的なoffline zero-ageで、実際の受信時刻/鮮度を再現しない。packet metadataのidentity/timeは実験fixture、odomは未観測(null)、元保存画像の実capture番号・実運動の主張ではない。source/物理/接地/FFB/ROS flagsはfalseのまま。実処理時間は別で記録するため、遅い試行を期限切れとして数値差の集計から黙って落とさない。

body-display guard/同接続pin-load/pipe/async queue/実network/表示RTPとの対応/5Hz・10Hz実pacingは今回の対象外。実通信の200ms期限や操縦映像との共存は別試験。保存画像は既に受信codecを通ったものなので、camera原画から直接packet化する場合とは圧縮履歴が異なる。今回の差は絶対測距誤差でなく、**同じ保存画像に追加再圧縮した影響**。

追加画像を使う場合は11/13同sessionの保存evidence 28980/37696/44793もallowlist済みで、既存原本の所在確認後に`--image`を繰り返す（最大4枚）。自動探索や過去参照のsession書換えをしない。1枚予備試験の結果を確認する前に追加撮影を要求しない。

## ローカル準備検証（GPU結果ではない）

[正式監査](verification_r01/audit.json)、[pytest出力](verification_r01/tests.txt)。新16を含む関連155試験成功、失敗/skip0、4.29秒。実VP8と既存幾何を使った合成predictorのABBA/新規検出/保留維持/ログ上限/入力不変/出力・圧縮物の上書き拒否を確認した。別に保存原本4枚のSHAを既存allowlistへ照合し、現行VP8でnative寸法の復号と原本不変を確認した。これらはGPU精度/負荷の測定ではなく、実CUDA結果は未取得。

前段runtime監査のcode SHAが全て不変であることも検査した。過去manifestを書換えて通したものではない。ローカル再現は解析PCの次のコマンドで、新規outputが必要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/check.py --output-dir Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/verification_r02
```

この解析PC用検証をGPUPCで実行する必要はない。GPUPCでは上のrun.pyを使う。

## 次のGPUPC操作：r02対象範囲を補正した同画像試験

**実施・解析済みの履歴。同じ条件の再実行は不要。** [r02正式監査](gpu_r02_audit_r01/audit.json)、[結果](submission_report_r02.md)。

r01はCUDA/codec完走だが、候補がROI外だったため採用時の支持点・距離処理時間は未測定。保存GPU bboxとpacket/復号画素SHA全一致からの事後計算では、元画像1.189269m→packet1.159086m、差約3.0cm。これは追加再圧縮の前後差で、絶対精度やライブ採用を認定しない。

次は同じ画像の対象中心を含むROIを**明示**する。runtime既定や校正は変更しない。runnerはGPUPC反映済みのものから不変であり、**このr02実行のためのGit再反映・追加撮影・走行・画面録画は不要**。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py \
  --image recordings/2026-11-16/body_guard_live_r01/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --target-roi 200 0 280 720 \
  --experimental-rigid-mount \
  --output-dir recordings/2026-11-18/packet_recompression_gpu_r02 \
  --archive /home/hsr/Downloads/packet_recompression_gpu_20261118_r02.tar.xz
```

`state: complete` 後、Downloadsの `packet_recompression_gpu_20261118_r02.tar.xz` を提出する。成功を予告して古いsummaryを更新しない。r02でも保留なら保存ログの理由を確認する。旧r01の出力・archiveは保持する。

提出監査の再現（解析PCのみ、既存intake/resultと異なる新規先が必要）：

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/audit_submission.py \
  --archive /home/robo25/Downloads/packet_recompression_gpu_20261118_r01.tar.xz \
  --source-image recordings/2026-11-16/body_display_full_intake_r02/comparison/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png \
  --intake-dir recordings/2026-11-18/packet_recompression_gpu_intake_r03 \
  --output-dir Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/submission_audit_r03
```

監査は原JSON3点のSHA・全20行/10対/summaryを再計算し、全code/weights設定の来歴と各packet wire/推論画素の一致を確認する。アーカイブの汎用展開や同梱文書の指示実行はしない。新8を含む関連163成功/失敗skip0/4.67秒、正式は[verification_r02](verification_r02/audit.json)。verification_r01の155成功は監査テスト追加前の履歴で、GPU結果ではない。

### r02提出監査の再現（解析PCのみ）

既存監査結果を上書きせず新規先を指定する。r01の旧条件を緩めず、`--protocol r02`でarchive root/ROIを明示する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/audit_submission.py \
  --protocol r02 \
  --archive /home/robo25/Downloads/packet_recompression_gpu_20261118_r02.tar.xz \
  --source-image recordings/2026-11-16/body_display_full_intake_r02/comparison/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png \
  --intake-dir recordings/2026-11-18/packet_recompression_gpu_r02_intake_r02 \
  --output-dir Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/gpu_r02_audit_r02
```

同じROIの全measurementを再現し、提出GPU値の距離差・時間・採否集計を確認する。ROIを後から変えた診断ではない。監査のr02対応新2を含む関連165成功/失敗skip0/4.88秒、最新ローカル検証は[verification_r03](verification_r03/audit.json)。これは検証コードの試験結果で、実GPU結果とは別。
