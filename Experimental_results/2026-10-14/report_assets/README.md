# 2026-10-14 代表資料

今回の作業は追加注釈の品質確認と確認ツールの修正。モデル学習・性能改善・FFB出力はまだ行っていない。

| 資料 | 説明 |
|---|---|
| [frame4261の原画像](../cone_annotation_quality_r01/raw_examples/block_a_e68ece502c09e03a_f004261.png) | 魚眼端に赤コーン台座の断片が映る。保存labelでは同じ断片へ複数枠が付いていた |
| [frame4651の原画像](../cone_annotation_quality_r01/raw_examples/block_a_e68ece502c09e03a_f004651.png) | 大きな赤コーンと、黄色の保存枠を確認した1枚。赤枠の重複を修正・再確認する対象 |

原録画は`cone_train_block_a_r01_20261012_153804_108`。2点とも1280×720・dual-fisheye全画角・元PNGのバイト同一コピー。
枠・文字・補正は画像に保存していない。
session/frame/time・画素/PNG/raw hashは[raw_example_manifest.csv](../cone_annotation_quality_r01/raw_example_manifest.csv)。
実際の保存枠や重複組は[品質報告](../cone_annotation_quality_r01/README.md)からCSVで確認できる。

修正後、基準35枚と追加36枚をこのPCの同じFP32条件で学習・評価した。追加版は誤候補が多いため採用保留。

| 追加のグラフ | 説明 |
|---|---|
| [学習と色別Recallの比較](../cone_ab_retraining_comparison_r01/retraining_comparison.png) | 実50 epoch CSV、同じ検証38枚の赤/黄色別固定閾値Recall。独立testではない |
| [固定閾値のPrecision/Recall](../cone_ab_retraining_comparison_r01/fixed_threshold_tradeoff.png) | 低い閾値で全GTを拾っても、余分な枠が増える点を示す。実CSVから生成 |

グラフを含め、本日の代表資料は上記の原画像2点＋グラフ2点の計4点。
比較CSV・生成script・hash・採用保留の根拠は[再学習比較報告](../cone_ab_retraining_comparison_r01/README.md)。
