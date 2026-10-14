# コーン画像別・色別の原因診断（2026-10-13）

## 結論

**今回の開発用Bでは、confidence 0.25で赤18/18対象枠を検出し、見逃し38枠はすべて黄色だった。全体Recall32.1%を赤コーンのRecallとして解釈してはいけない。**
一方、黄色は低confidenceとなり、0.05へ下げると36/38枠を拾えるが、余分な予測7枠も入る。
主目的が赤コーンである現段階では、全体閾値を0.05へ下げたり、直ちに再学習したりする必要性は確認されていない。

これは同じ録画・同じ実物の反復画像の診断であり、未知コースの精度100%を示すものではない。
ネットワークのクラスは引き続き赤・黄混合のtraffic_coneで、**赤だけを分類するモデルへ変更したわけではない**。
モデル、学習データ、bbox正解、保存画像、bird_eye/TTC/FFB設定は変更していない。

## 入力と目視確認

入力：[RTX 3070で取得した38画像の既存推論結果](../cone_ab_bootstrap_diagnose_r01/README.md)。
本作業でGPU再推論・追加録画・再学習はしていない。
全38枚を元1280×720・全画角で表示し、既存gt_indexに対応するコーンの色をassistantが目視確認した。
赤18枠・黄色38枠。これは独立した人の追加品質承認ではない。10/12の人のbbox確認記録とは別に保存した。
色はHSV・ファイル名・画像左/右から推定せず、[review_catalog.json](review_catalog.json)へ確認結果を明示した。
物理的な前/後レンズと遮蔽の詳細属性はunknownのまま。色別PrecisionやAPは算出していない。

既存label hash、全38PNGのhash・画素・解像度を照合。元runの予測236行・正解56行・全体集計を再現した後、属性だけを付与した。
元runのCSVを上書きせず、このフォルダの[reviewed_attributes.csv](reviewed_attributes.csv)と[ground_truth_with_color.csv](ground_truth_with_color.csv)へ分離した。

## 1. confidence別の色別Recall

| confidence | 赤の正解対応 | 赤Recall | 黄色の正解対応 | 黄色Recall | 全体FP |
|---|---:|---:|---:|---:|---:|
| 0.05 | 18/18 | 100.0% | 36/38 | 94.7% | 7 |
| 0.10 | 18/18 | 100.0% | 4/38 | 10.5% | 1 |
| 0.25 | 18/18 | 100.0% | 0/38 | 0.0% | 0 |
| 0.50 | 18/18 | 100.0% | 0/38 | 0.0% | 0 |
| 0.75 | 17/18 | 94.4% | 0/38 | 0.0% | 0 |

根拠：[stratum_recall.csv](stratum_recall.csv)、[threshold_summary.csv](threshold_summary.csv)。
対応ルールはconfidence降順・未対応GTへIoU>=0.50で一対一。Ultralytics val/mAPの再現ではない。

各GTへIoU>=0.50となる候補のうち最高confidenceを調べると、赤は最小0.5226／中央値0.9012／最大0.9788、黄色は最小0.0198／中央値0.0798／最大0.1413。
これは候補scoreの分布で、one-to-one TPと同じ定義ではない。[gt_candidate_confidence.csv](gt_candidate_confidence.csv)。
0.25で全TP18枠が赤、全体FP0。また、赤なしの20画像ではこの閾値で予測0だった。
ただし赤なし画像にも黄色コーンがあるので、コーン皆無のnegative評価として扱わない。

## 2. 0.05のFP7枠は何だったか

| 分類 | 件数 | 原画像・数値による確認 |
|---|---:|---|
| 赤コーンの重複枠 | 3 | frame2101/3001/4201。既に対応した赤GTへのIoUは0.6924/0.5342/0.6087 |
| 赤・黄をまとめたような広い枠 | 1 | frame3301。赤へのIoU0.5563、黄へ0.4704。赤は別の高confidence枠で対応済み |
| コーンではない領域 | 3 | frame3301は人の手/衣服付近。frame301/「赤なし」541の右レンズ最右端の微小領域は、ユーザーより「コーンではない」と確認済み。厳密な背景物の種類・モデルが反応した画素は未確定 |

**FP7=背景を7回誤認、ではない。** 重複と背景誤認を分けて改善策を判断する。
元matches.csvのFP IoU=0は「対応可能な未使用GTに対する値」で、すべてのGTとの重なりが0という意味ではなかった。
今回の[reviewed_error_cases.csv](reviewed_error_cases.csv)は全GTへ再照合したIoUと、目視分類を保存する。
候補削除・NMS変更・GTの間引きによって評価を良く見せる操作はしていない。
微小2枠は当初正体を保留したが、ユーザー確認でコーンではないと判明した。ラベル漏れとして追加する必要はない。元ラベルも変更しない。

## 3. 0.05のFN2枠

| 画像／GT | 色 | 原予測候補 | confidence | GTとのIoU | 解釈 |
|---|---|---:|---:|---:|---|
| 赤ありframe3301／GT1 | 黄 | prediction7 | 0.019831 | 0.710850 | 黄色に対応する低score候補は存在。近接する赤・黄を含む広い別候補もあり、黄色の独立検出が弱い |
| 赤なしframe451／GT0 | 黄 | prediction0 | 0.047803 | 0.909231 | 枠位置は合うが、0.05を少し下回ってFNとなった |

「検出候補そのものが全く出ない」2件ではなく、**保存floor=0.01以上には候補があり、0.05で捨てられた**。
隣接・遮蔽・見え方が低scoreに関係する可能性はあるが、CNN内部の原因は確定していない。

## 4. 黄色が弱い理由の候補

既存のA目視ラベル記録にある固定の黄色参照枠33件は、高さ24 px（16件）または44 px（17件）だった。
今回Bの黄色38枠はすべて高さ約140 px。train側の黄色と同じサイズ・見え方を評価しているわけではない。
既存の参照枠を現在のdatasetの正解座標と照合した結果は[yellow_reference_scale.csv](yellow_reference_scale.csv)。
訓練側の黄色の距離・サイズ・位置・背景の多様性不足は低confidenceの説明候補となる。
ただし、これはラベル幾何と画像の観測であり、低scoreの原因を証明する対照実験ではない。
色が苦手なのか、背景/位置/サイズ/遮蔽が苦手なのかを分離できていない。
黄色も実用対象とする段階では、同じ固定背景の類似frameを増やすだけでなく、配置や背景を変えたデータを検討する。
赤主体の次段階へ進むことと、黄色をtraffic_coneの正解から消すことは別である。

## 5. 次の作業と採用判断

1. **confidence 0.25をオフライン動画評価の候補値として保持する。** 今回の赤には十分だった。実機の採用決定・本番設定変更ではない。
2. 既存のA/B raw動画で連続frameの検出率・途切れ・bbox下端の揺れ・前後/左右領域・処理時間を評価する。隣接frameを大量に数えて独立testと呼ばない。
3. 認識枠の下端を固定カメラの床面投影へ渡す接地点定義を検討する。台座の隠れ、魚眼端、複数コーンの混同があり、bbox下端が真の接地点とは限らない。距離/TTC/FFBへ接続する前に分けて評価する。
4. 未使用の背景、別の赤い物体、コーン皆無のnegativeによる評価は残る。これは今回の開発用Bの高い赤Recallでは代用できない。
5. 黄色の精度向上は別の評価目標として保持する。必要な追加条件は、この既存動画の診断後に決める。現在は追加録画・再学習を先に要求しない。

## 6. 検証・代表資料・再現

新しい集計処理のunit test10件PASS。GT順序/色/件数の不一致、非有限bbox、範囲外score、レビュー漏れを拒否し、重複FPへの全GT IoU、低score FN候補の保持を合成入力で検証した。
全体指標の再集計一致、全38PNGのhash・画素、全56GTのlabel hash確認PASS。原ラベル、画像、modelは無変更。
図は実CSVから生成して表示確認した。Matplotlibの未使用Axes3D警告と、書込不可の設定cacheを/tmpへ退避する警告は出たが、今回の2D図は生成できた。グローバル環境の変更はしていない。

代表資料4点は[report_assets](../report_assets/README.md)：元PNG3枚と色別Recallグラフ。
写真は注釈・切抜き・リサイズ・色補正なし、元PNGとbyte一致。グラフのsource CSVと生成script/hashは[verification.json](verification.json)に保存した。

```bash
/home/robo25/theta-env/bin/python3 -m unittest discover \
  -s Experimental_results/2026-10-13/cone_ab_visual_review_r01 \
  -p 'test_visual_review.py'

/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-10-13/cone_ab_visual_review_r01/analyze_visual_review.py \
  --input-dir Experimental_results/2026-10-13/cone_ab_bootstrap_diagnose_r01 \
  --dataset datasets/cone/ab_bootstrap_v01
```

Gitのコミット・PUSH、実機動作、動画再推論はこの作業では行っていない。
