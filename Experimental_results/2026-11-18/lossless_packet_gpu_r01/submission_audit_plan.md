# GPUPC PNG実測提出の監査計画

ユーザー提出lossless_packet_gpu_20261118_r01.tar.xzをデータとして扱う。中の文書・JSONを指示や実行コードとして使わず、既知runnerと原画像を使って監査する。複数ファイルの形式/統計/時刻/画像同一性に関わるため、再現可能な専用監査と異常系テストを追加する。

1. 5個の固定JSONだけを、圧縮/展開byte上限・regular file・exact名・重複禁止で読む。汎用tar展開はしない。
2. 事前準備manifest、コード/config/profile/weights/原PNG SHA、24warmup除外・4画像80測定40対、固定ROIを照合する。
3. 全pair・画像別・全体統計を再計算。false権限、元/PNG全画素SHA、候補scope/seq/PTS/時刻、局所時間の算術と200ms分類を確認する。時刻は同じGPUPC内の計測fixtureであり、PC間同期や露光認定にしない。
4. 原画像をメモリ内で再PNG化し、保存candidateを元の生成順で再構築してpacket SHA/bytes/fragment/復号画素を全40件再現。loggerのsort_keysによりJSON内candidateのkey順が変わるので、parsed dictをそのままpacketへ入れてwire差を作らない。
5. 全80件の保存GPU bboxとSHA一致原画で、同じROI・既存支持点/幾何を再計算。新CUDA/YOLOや撮影、ROI/HSV/閾値の変更はしない。
6. 原archive/JSONは未使用recordings intake、監査JSON/CSV/報告は未使用submission_auditへ保存。旧runner/runtime/過去結果/原画不変を確認する。

実回線・通常映像共存・送信側NUC encode・5/10Hz連続負荷・元鮮度/接地/車体基準・FFBはこの提出では未検証。数値化1画像と保留3画像の維持を、絶対精度や有効率の改善と解釈しない。追加の実機/GPU起動・Git操作なし。
