# GPUPC用PNG経路・既存CUDA測距の保存画像試験準備

複数ファイルのcodec/期限/測定条件を扱う作業。ユーザーの「準備お願いします」に基づき、実行スクリプト・手順・提出pack・解析PC上の回帰検証を用意する。GPUPC/ネットワーク/実機はこの準備中に起動しない。

## 既存根拠と共用

- lossless_frame_packet_r01で4枚の全画素・元判定一致、lossless_sender_load_r01で有界待機/期限/仮想負荷を確認済み。
- frame_packet_gpu_recompression_r01/run.pyの保存原画allowlist、config/profile、statistics、pair比較、CUDA predictor設定を共用する。旧runner・旧runtime・PNG codec/fragmentは変更しない。
- 実GPIO/RTC/ROS/G923なし。PNG encode/検査/fragment/再構成/復号は実コードでメモリ内に行い、元画像への変更や派生画像保存をしない。
- 新しい依存関係は追加しない。同期計測は既存torch.cuda.synchronize、モデルは既存YoloConePredictor一個。driverやPyTorchの再導入はしない。

## 条件

1. 保存4枚をrecordings/Experimental_resultsから有界探索し、名前だけでなく既知PNG SHA/native画素を検査。不足・改変時はモデル起動前に停止し、必要な名前を列挙する。別rootの明示追加も可能。
2. ROIは5186だけ[200,0,280,720]、残3枚は[270,0,350,720]。前回のROI誤案内を繰り返さず、GPU検出結果に合わせて範囲を変更しない。
3. 準備manifestでrunner/既存source/config/profileのSHAを固定し、GPU反映漏れを開始前に検出。重みは既存configのSHAと照合しCUDA tensor演算も実行する。CPU fallbackなし。
4. 各画像6warmupを除外し、元/PNG/PNG/元を5反復。4枚で24warmup除外・80測定・40対。原画とPNG画像は毎回実際にCUDA推論する。支持点・幾何設定は既存のまま。
5. encode、送信側初片前検査、受信再構成、decode/copy、CUDA同期推論、支持点/幾何、初片→幾何完了を別計測。packet受理の初片200msは緩めない。GPU推論後に200msを超えた場合は診断結果に残すが、期限内と認定しない。sample/geometryの年齢は明示的offline fixtureであり実露光・実odomの復元ではない。
6. 結果JSONだけを1archiveにする。入力/出力/既存archiveの上書き、チェックポイントや画像の提出混入は禁止。失敗時はsummaryにfailedを残し、成功packは作らない。

## 準備検証と次の境界

解析PCはCUDA実測ではなく、合成predictorと実保存4原画/PNG/幾何で80測定40対、破損/ROI/入力不足/manifest差分/失敗pack拒否を検証する。旧276回帰も含める。実GPU速度・実GPU判定比較はGPUPCから結果を受領するまで未確認。実帯域・運転映像共存・capture鮮度・車体TF/接地/FFBは別試験のまま。
