# 2026-10-13 代表資料

RTX 3070で実行した既存best.ptの画像別診断、色別・FP/FN診断、B動画の全frame評価を示す代表4点。
独立test・実機FFBの成功画像ではない。

| 資料 | 用途と原本 |
|---|---|
| [色別Recallグラフ](cone_color_recall_by_confidence.png) | 赤18/18と黄色の低confidenceを分離。実予測CSVの固定閾値評価で、mAPではない |
| [動画の検出・処理時間グラフ](../cone_video_b_r01/video_detection_and_timing.png) | B全5,808frameの実推論。0区間と処理時間を分離。全frameのRecallやlive FPSではない |
| [赤・黄が隣接する元画像](cone_adjacent_red_yellow_raw.png) | cone_train_block_b_r01_20261012_155114_513、frame3301。広い混同枠と黄色の低score候補を調べた場面 |
| [黄色の低confidence例](cone_yellow_low_confidence_raw.png) | cone_nasi_block_b_r01_20261012_155435_017、frame451。黄色は見えているが候補score0.0478で0.05未満 |

補足資料として[赤コーンの重複例の元画像](cone_red_duplicate_raw.png)（B赤ありframe2101）も保存したまま維持する。
元画像3枚とも1280×720・全dual-fisheye・無加工。説明や枠を画像に描き込んでいない。
元画像、session/frame/time、PNG・画素・raw hashは[cone_visual_review_raw_manifest.csv](cone_visual_review_raw_manifest.csv)。

グラフ元CSV：[stratum_recall.csv](../cone_ab_visual_review_r01/stratum_recall.csv)。
生成：[analyze_visual_review.py](../cone_ab_visual_review_r01/analyze_visual_review.py)。
図・元CSV・scriptのhash：[verification.json](../cone_ab_visual_review_r01/verification.json)。
解釈・限界：[原因診断報告](../cone_ab_visual_review_r01/README.md)。

動画グラフの元CSV/生成script/hashと追加rawレビュー12点は[動画評価報告](../cone_video_b_r01/README.md)から追跡できる。

追加の補足グラフ：[検出途切れ代表点の候補score](../cone_video_gap_predictions_r01/gap_candidate_confidence.png)。
検出0となった10区間の代表1点ずつを同一モデルで再推論し、赤領域に重なる候補のscoreを比較する。
9点に0.146〜0.247の候補があるが、枠の正確性・接地・全区間のRecallは未確認。
原画像は加工していない。CSV・生成script・hash・限界は[追加診断報告](../cone_video_gap_predictions_r01/README.md)。

学習データ追加準備の補足原画像2点：[魚眼端の断片](../cone_train_a_hardcase_preparation_r01/raw_examples/block_a_e68ece502c09e03a_f004261.png)、
[近くで持っているコーン](../cone_train_a_hardcase_preparation_r01/raw_examples/block_a_e68ece502c09e03a_f004651.png)。
train側Aの未注釈170枚から確認待ち16枚を選んだ例。検出精度改善を示す画像ではない。
2点とも元PNGのバイト同一コピー・1280×720全画角。
session/frame/hashと生成scriptは[学習追加準備報告](../cone_train_a_hardcase_preparation_r01/README.md)から追跡できる。
