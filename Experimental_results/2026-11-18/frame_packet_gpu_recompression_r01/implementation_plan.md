# 保存画像のpacket再圧縮・GPU測距比較

## 目的と前提

GPUPCのユーザー報告でHEAD 39e1e67、PyTorch 2.7.1+cu118、PyAV 16.1.0、OpenCV 5.0.0を確認。CUDA unknown errorは再起動後に解消し、RTX 4070 Laptop GPUでtensor計算1.0が成功した。再起動で回復した事実と原因の特定は別であり、ドライバー等を再導入していない。

保存native PNGと、同じ画像を現行encode_packet / FramePacketReceiverでVP8再圧縮・復号した画像へ、既存YoloConePredictor / observe_upper_completion / MotionRangeEngineを同条件で適用する。最初はGPU上の所在が確認できた11/16 pin 5186の1枚で予備確認する。追加撮影、送受信、走行、ROS、G923は不要。

## 実装と測定

- 実験専用run.pyとテストのみを追加し、srcのcodec/検出/支持点/幾何/制御を変更しない。
- 既存監査で確認済みの4 PNGだけを名前・SHA・1280x720で照合する。指定された入力以外を探索・暗黙追加しない。元PNGを読み取り専用で保持し、派生画像はメモリ内だけで扱う。
- CUDA専用の既存predictor1個を使用。CPU fallbackや環境自動導入、checkpoint downloadなし。weights/config/profile SHAを記録する。
- warmupを除き、各画像でoriginal / packet / packet / original（ABBA）を反復し、全試行を記録する。新規検出を使い、保存済みbboxを転用しない。
- 採否、理由、検出枠、実観測支持点、距離差、画素差を比較。原画像側の反復変動も分離する。片方保留を距離誤差0へ換算しない。
- 圧縮、復号・検証・copy、GPU同期込み推論、支持点/幾何のwall時間とprocess CPU時間、PyTorch allocatorのpeak allocated/reserved bytesを採取する。GPU全体使用率や機体側CPU負荷と偽らない。
- 保存画像の幾何比較は明示的な合成zero-ageを用いる。実測したreceiver段階時間は別集計し、100/200ms超過を全件計数する。5/10Hzの実スケジューリングや実queue/ネットワーク期限を達成したとはしない。
- packet用capture identity/timeは実験fixture、odom未観測のまま。保存画像に実運動を捏造せず、全認定flag falseを保持する。
- 新規output/新規archiveのみ作成し、失敗時はfailed summaryを残す。成功時に結果だけを圧縮し原画像/重みは含めない。

## 検証と限界

ローカルでは実VP8と実幾何、合成predictorで経路/集計/入力不変/失敗時挙動を試験する。CUDA成功や距離精度はGPUPCの提出結果を待つ。1枚予備試験では距離1/1.5/2m全域、body-display guard、実通信、走行姿勢、FFBを承認しない。測定対象は「保存済み受信画像への追加再圧縮」であり、camera原画からの直接packetと同じ圧縮履歴ではない。
