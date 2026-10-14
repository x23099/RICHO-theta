# 2026-10-14 代表資料

## 終業時の代表4点

| 資料 | 説明 |
|---|---|
| [水筒を含むD02原画像](../cone_de_intake_r01/raw_examples/block_d_20261014_1eba1760023abcce_f000001.png) | 学習用の確認済み負例。水筒とコーンの区別を説明できる |
| [赤・黄のE02原画像](../cone_de_intake_r01/raw_examples/block_e_20261014_b6fd99bdae17dfd4_f000661.png) | 同じTHETAの両レンズによる、評価用のコーン配置 |
| [負例追加による比較](../cone_negative_retraining_v04_r01/negative_retraining_comparison.png) | 誤検出低減と正例保持を分けて見る。Dは学習再確認、Eは当時の参考領域 |
| [human GTと友人モデルの比較](../friend_models_review_r01/human_gt_model_comparison.png) | 正式human bboxと予測を照合し、FPとFNの両方を表示 |

原画像2点は1280×720・全画角・元PNGのバイト同一コピー。枠・補正・cropなし。
後続Eのhuman確認・友人weightsの確認は[終業報告](../friend_models_review_r01/README.md)。
図の根拠CSV・script・hashは各リンク先READMEで追跡できる。以下の前半資料は履歴・補助として維持する。

## 前半の資料

今回の作業は追加注釈の品質確認、確認ツールの修正、同条件再学習の比較、負例候補の準備。
モデルの運用採用・FFB出力は行っていない。

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

グラフを含め、前半の候補資料は上記の原画像2点＋グラフ2点の計4点。終業時の選定は冒頭の4点を優先する。
比較CSV・生成script・hash・採用保留の根拠は[再学習比較報告](../cone_ab_retraining_comparison_r01/README.md)。

補助原画像として、別日の[箱なしframe](../cone_negative_preparation_r01/raw_examples/legacy_box_20260825_377e1afc8358eacb_f000001.png)と
[箱ありframe](../cone_negative_preparation_r01/raw_examples/legacy_box_20260901_5686fb7d85b44135_f000410.png)も保存した。
両レンズでコーンを特定しなかった負例候補だが、人のGT確認はまだpending。
どちらも1280×720・元PNGのバイト同一コピー。来歴と候補推論は[負例準備報告](../cone_negative_preparation_r01/README.md)。
上記2点は補助資料とする。終業時の代表4点は冒頭の表に記載した。

## 追加録画D/Eの補助資料

5本の追加録画を受け取り、負例と評価用を分離した。下の資料は再学習前の診断snapshot。

| 資料 | 説明 |
|---|---|
| [D02原画像](../cone_de_intake_r01/raw_examples/block_d_20261014_1eba1760023abcce_f000001.png) | 赤い水筒を含む負例。ユーザーが水筒・非コーンと確認 |
| [E02原画像](../cone_de_intake_r01/raw_examples/block_e_20261014_b6fd99bdae17dfd4_f000661.png) | 赤・黄の固定配置。両レンズで対象が見える |
| [E03原画像](../cone_de_intake_r01/raw_examples/block_e_20261014_acec4adbfa04e57a_f000940.png) | 配置変更後の赤・黄コーン。評価用で学習に混ぜない |
| [今回の比較グラフ](../cone_de_intake_r01/selected_frame_comparison.png) | 水筒への誤検出と、黄色のassistant参考照合。正式human GT評価ではない |

原画像は1280×720・元PNGのバイト同一コピー、枠や補正なし。
新しい録画と来歴・根拠CSV・生成scriptは[追加録画の受入れ報告](../cone_de_intake_r01/README.md)に記載。

## D負例確認後の再学習

D16枚がhuman negative確定し、52枚版の学習・B/D/E比較まで完了した。
[52枚版の比較グラフ](../cone_negative_retraining_v04_r01/negative_retraining_comparison.png)では、
Bの余分な枠の低減、学習に使った水筒の再確認、学習に使わないE03黄色の参考照合を分けて表示する。
全条件で改善したわけではないため運用採用は保留。根拠CSV・生成script・hash・見逃しは[再学習報告](../cone_negative_retraining_v04_r01/README.md)。
cameraの原画像は上のD02/E02/E03を加工せず再利用する。

## Eのhuman確認完了

E24枚（positive16/negative8、32枠）がhuman確認済みとなり、友人modelも同じ原画像で評価した。
以前のassistant参考照合はsnapshotとして維持し、終業の判断には[human評価結果](../friend_models_review_r01/README.md)を用いる。
白線weightsはmodel定義不足で実映像推論未実施。白線maskの画像は作っていない。
