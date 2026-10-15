# コーン候補2条件の連続録画比較（2026-10-15）

## 結論

既存7録画11,397frameを、固定した2候補で全frame解析した。合計22,794frame、間引きなし。
次の**床置き静止距離試験**では、36枚版・confidence0.50を開発候補として使う。
これは本番採用ではなく、距離/TTC/FFB接続の合格も意味しない。
52枚版は保存し、比較結果に合わせて学習や閾値の再調整はしない。

ユーザーが優先したコーン→FFBの手順のうち、既存動画で検出の継続性・出力数・処理時間を確認する段階を終えた。
次は[床置き赤コーンの距離参照録画](../cone_static_distance_capture_procedure.md)。
白線調査・カメラ起動・ROS通信・車体駆動・FFB出力・Git commit/pushは行っていない。

## 1. 固定条件と来歴

GPU RTX3070、torch2.14.1+cu130、Ultralytics8.4.175、FP32、batch1、imgsz960、rect=false、NMS IoU0.7、max_det300。
両候補はYOLOv8n。同じ元映像・同じ逐次デコードで処理し、各session冒頭frameは時間集計から除外。
閾値とweights hashは推論前の[profiles.json](profiles.json)で固定した。

| profile | 学習データ | confidence | best.pt SHA256先頭 |
|---|---|---:|---|
| `augmented36_conf050` | 既存positive36枚 | 0.50 | `3a6e124adb15c16e` |
| `negative52_conf025` | positive36＋D negative16枚 | 0.25 | `e613f9a5c20d83fc` |

どちらもtrainにEを含めない。ただしB/Eは既に開発比較へ使用しており、今回をblind testとは呼ばない。
Dは52枚版に対して学習再確認。比較順序は36→52の1回ずつで、厳密な速度benchmarkの反復実験ではない。
driver/依存を変更せず、パッケージの自動取得・外部loggerを無効化し、設定/fontはrun内へ保存した。

入力は[video_plan.csv](video_plan.csv)、原本のhash・モデル・コード・実際のGPUは
[comparison_provenance.json](evaluation_r01/comparison_provenance.json)へ記録。
元raw/metadata/detections、model/条件ファイルの処理前後hashが一致。
同じ78画像（B38+D16+E24）のデコード画素hashが両候補とも全て一致し、mismatch0。
全画角/正面の注釈画像TP/FP/FNは[前段の静止画比較](../cone_ffb_readiness_r01/README.md)と全条件で一致した。

## 2. 正面の連続出力

正面は左の校正円内にbbox中心があることと定義する。各値は「正面に1件以上出たframe / 全frame」。
これは対象ごとのRecallではない。複数の対象や誤検出があると、1件の出力で別対象の消失が隠れる。

| 録画 | 36枚/0.50 | 52枚/0.25 | 注意 |
|---|---:|---:|---|
| B赤移動 | 3,813 / 5,236 | 3,726 / 5,236 | 持ち運び、後レンズへの移動、遮蔽を含む |
| B赤なし | 0 / 572 | 0 / 572 | 後方の黄色は存在。全画角のnegativeではない |
| D01 | 0 / 1,104 | 0 / 1,104 | intended negative、人確認は抽出8画像 |
| D02（水筒） | 0 / 912 | 0 / 912 | intended negative、人確認は抽出8画像 |
| E01 | 0 / 1,320 | 0 / 1,320 | intended negative、人確認は抽出8画像 |
| E02固定配置 | 1,156 / 1,156 | 1,156 / 1,156 | 正面は黄色、後方は赤。各frameの正面出力は両候補とも1件 |
| E03置き替え | 1,085 / 1,097 | 1,071 / 1,097 | 正面の赤の持ち運び/遮蔽を含む |

D/E01合計3,336frameで正面出力0。全frameのhuman negative GTは付けていないので「全frameの誤検出率0%」と断定しない。
E02は約41.8秒の同一配置であり、1,156種類の独立場面ではない。
E03の正面出力ゼロは36枚版12frame（1区間）、52枚版26frame（2区間）。
最長0区間の最初/最後のsample時刻差は0.343727秒と0.474991秒。
これは厳密な遮蔽時間・警告遅延ではなく、1frame区間は0秒になる定義。

B赤移動で正面2件以上のframeは36枚版7、52枚版336。
誤検出/重複/別物体を全frameで照合していないため、そのままFP数とは数えないが、36枚版のほうが正面出力の余分な増加が少ない。
両候補のゼロ区間を、未確認のまま正解の欠測や「進路クリア」へ変換する処理はない。

## 3. 注釈frameでの照合

各欄はTP / FP / FN、IoU0.5・1対1。
B注釈には従来のassistant visual reviewが含まれ、今回新たにhuman full-frameで確認したものではない。
E32枠は前日のhumanレビューとhashが一致。

| scope | 条件 | B | E | DのFP |
|---|---|---|---|---:|
| 全画角 | 36枚/0.50 | 50 / 7 / 6（GT56） | 29 / 0 / 3（GT32） | 0 |
| 全画角 | 52枚/0.25 | 53 / 12 / 3（GT56） | 30 / 2 / 2（GT32） | 0 |
| 正面 | 36枚/0.50 | 13 / 0 / 0（GT13） | 16 / 0 / 0（GT16） | 0 |
| 正面 | 52枚/0.25 | 12 / 2 / 1（GT13） | 16 / 2 / 0（GT16） | 0 |

正面の注釈画像、E02の継続、E03のゼロframe、余分な複数出力の比較から、次の正面静止距離試験には36枚/0.50を優先する。
一方、後方を含む全画角では36枚/0.50に見逃しが多い条件がある。後退・全周検知まで完成したと扱わない。
同じ開発データからの候補選択であり、未知環境への汎化保証ではない。

## 4. 代表原画像の確認

[raw_example_manifest.csv](analysis_r01/raw_example_manifest.csv)にsource/session/frame/time/hashを記録。
全て1280×720、元の全画角PNG。注釈・切り抜き・リサイズ・色補正なし。
所見は[visual_review.csv](analysis_r01/visual_review.csv)へ保存し、学習ラベル/人確認と混同しない。

| 原画像 | 所見 |
|---|---|
| [E02 frame578](analysis_r01/raw_examples/cone_positive_eval_e02_c_20261014_165209_894_f000578.png) | 左に床置き黄色、右に床置き赤。距離の実測値はない |
| [E03 frame639](analysis_r01/raw_examples/cone_positive_eval_e03_c_20261014_165444_176_f000639.png) | 左の手で持った赤の本体・台座が見えるが52枚/0.25は正面出力0。床接地点としては使えない |
| [E03 frame686](analysis_r01/raw_examples/cone_positive_eval_e03_c_20261014_165444_176_f000686.png) | 左の赤は脚で大きく遮蔽され一部だけ見える。36枚/0.50の正面出力0を、全区間の単純な認識不良と断定しない |
| [B frame3437](analysis_r01/raw_examples/cone_train_block_b_r01_20261012_155114_513_f003437.png) | 赤・黄が右/後方にあり、左/正面にコーンを特定せず。この点の正面出力0は後方移動と整合 |

代表4frameの目視であり、区間全体へのGT補間や全frameの精度集計は行っていない。
52枚版で持ち運び赤にゼロ出力があることから、負例を増やすだけで検出が完成するわけではない。

## 5. 処理時間

| 条件 | 各sessionの逐次処理fps | 初回除外pipeline p95の範囲 | 初回除外pipeline最大 |
|---|---|---|---:|
| 36枚/0.50 | 44.74～54.33 | 21.30～28.59 ms | 88.41 ms |
| 52枚/0.25 | 47.66～51.98 | 23.29～27.83 ms | 108.35 ms |

pipelineはraw decode・GPU予測/出力取得・隣接IoU対応・予測CSV書込まで。
カメラ取得待ち、GUI、ROS、relay、FFB、全結果保存/元file hash計算は含まない。
各p95は33.3msより短いが最大は超える。live30fpsや100ms以内のFFBを保証する数値ではない。
物理コーンIDを保証する追跡や距離/TTCの時系列推定もまだない。

## 6. 友人モデル：カメラが違うから使えないのか

**カメラの種類だけを理由に利用不可とは判断しない。**
`cone.pt`は前日にstrictに再構築・ロードしてTHETA画像で推論できており、ファイル形式やGPU互換性のエラーではない。
今回は友人modelを新たに全動画へ流さず、前日に確定した同じ78PNGの結果を根拠とする。

| Eの同じhuman32枠、confidence0.25 | TP | FP | FN |
|---|---:|---:|---:|
| 友人・imgsz960 | 20 | 20 | 12 |
| 友人・学習記録と同じimgsz640 | 8 | 0 | 24 |

推論サイズを変えただけでも結果が変わる。カメラだけに原因を限定できない。
候補となる違いは、魚眼歪み/dual-fisheye配置/取付視点、対象の画素サイズ、背景・照明・反射、コーンの色/形/隠れ方、入力整形・推論サイズなど。
これは原因の仮説で、寄与率は測定していない。友人の元学習画像・撮影条件・元の推論入力を入手しておらず、カメラ要因と背景要因を分離した比較もない。
友人の学習画像数・赤黄の範囲・自分のデータとの重複も検証できていない。
「自作が全用途で上」「友人modelが壊れている」「カメラが同じなら解決する」とは言えない。

[Ultralyticsのデータ収集・注釈ガイド](https://docs.ultralytics.com/guides/data-collection-and-annotation/)は、用途に合う代表的な画像と偏りの回避を重視する。
[公式の学習ガイド](https://docs.ultralytics.com/guides/model-training-tips/)には、既存weightsから目的のデータへfine-tuneする方法も説明されている（2026-10-15参照）。
したがって友人weightsを追加学習の起点にする余地はあるが、成功を保証せず、今回のユーザー優先順位に従い別の再学習実験は増やさない。

## 7. 次の手順と成果物

1. 36枚/0.50は次のオフライン距離評価の開発候補とし、本番設定へはまだ入れない。
2. [床置き赤コーンの静止距離参照6本](../cone_static_distance_capture_procedure.md)を取得する。ハンコン・走行・FFB不要。
3. 台座が見える条件の距離/左右位置と安定性を確認してから、対象ごとの追跡・TTC・仮想FFBへ進む。
4. その後に既存challenge経路のROS dry_run、承認された低出力の実機確認へ進む。安全上限を緩めない。

結果CSV：

- [frame別の全画角/正面/投影候補数](analysis_r01/frame_counts.csv)、[区間別集計](analysis_r01/candidate_summary.csv)、[ゼロ区間](analysis_r01/zero_runs.csv)。
- [注釈frameの指標](analysis_r01/anchor_metrics.csv)、[照合](analysis_r01/anchor_matches.csv)、[前段再現確認](analysis_r01/anchor_reproduction.csv)。
- [時間](analysis_r01/timing.csv)、[投影仮説](analysis_r01/projection_hypotheses.csv)、[理由](analysis_r01/reasons.csv)。
- [比較グラフ](analysis_r01/video_readiness_comparison.png)、[集計来歴](analysis_r01/analysis_summary.json)。
- 生の推論CSV・隣接IoU対応・78原画素照合・条件は`evaluation_r01/{profile}/`。

新規出力名での再現（このPCの保持済みデータを使う）：

```bash
cd ~/theta_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-10-15/cone_video_comparison_r01/run_comparison.py \
  --output-dir Experimental_results/2026-10-15/cone_video_comparison_r01/evaluation_r02
python3 Experimental_results/2026-10-15/cone_video_comparison_r01/analyze.py \
  --input-dir Experimental_results/2026-10-15/cone_video_comparison_r01/evaluation_r02 \
  --output-dir Experimental_results/2026-10-15/cone_video_comparison_r01/analysis_r02
```

`--preview`は入力/hash/planだけを検査し、GPUを使用しない。既存結果は上書きしない。
前日の絶対pathを含むsnapshotを使うため、別PCへ移す場合は対応を確認する。

検証：新しい時系列整合性テスト8件を含むcone関連158件、既存ground/YOLO runner21件、計179件PASS。
Python構文、input/code/model/hashの保持、全78anchorの原画素と前段指標の再現、代表PNG/グラフの目視を確認。
2Dグラフの生成は成功。既存MatplotlibのAxes3D警告/テスト時の一時cache警告は残るが、driverやglobal設定を修正していない。
