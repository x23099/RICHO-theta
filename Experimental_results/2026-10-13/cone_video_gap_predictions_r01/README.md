# B動画の検出途切れ・枠下端変動の追加診断（2026-10-13）

## 結論

追加録画なしで、前回のB動画評価から選んだ無加工12フレームを、同じbest.pt・RTX 3070でconfidence floor 0.01まで再推論した。
0.25で検出出力が0になった10区間の**代表1点ずつ**では、9点に赤コーン領域へ重なる低score候補があった。
一方、魚眼端に赤台座断片だけが映るframe3213には、その領域の0.01以上のNMS後候補がなかった。
「全区間の9割を正しく認識した」「閾値を下げれば距離測定・FFBに使える」という結論ではない。

現行候補のconfidence 0.25は変更していない。モデル・元画像・注釈・HSV距離/TTC・ROS/FFBも変更していない。
位置と接地状態の検証を先に進める必要がある。

## 条件と照合

- 入力：[前回の無加工PNG12枚とmanifest](../cone_video_b_r01/raw_review_manifest.csv)。1280×720、dual-fisheye全画角。
- 同一重み：`runs/cone/received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt`。
- 重みSHA256：`f8f63446223ceac9e3d0f9227eae0ef814a2c569f1887748e10bf032821f8ad7`。
- `device=0`, `imgsz=960`, `rect=False`, `batch=1`, `conf=0.01`, `iou=0.7`, `max_det=300`。画像はモデル内部で入力変換するが、保存原画像は加工していない。
- 12点からNMS後候補97枠をCSVへ出力。max_det到達0点。PNGファイルhash・復号画素hash・寸法を推論前後と集計時に確認した。
- 0.25以上の2枠は、前回の動画評価とscore・座標が完全一致（最大絶対差0）。低floorへの変更で高score枠が変わっていないことを、この選択12点では確認した。
- 前回の[目視記録](../cone_video_b_r01/visibility_review.csv)に加え、12原画像を再確認し、0.05以上の33候補に位置別の判断を付けた。
- 色と領域の判断はassistantによる目視記録。YOLOの出力classは赤・黄色を含む`traffic_cone`一種類であり、色分類を実装したわけではない。

## 選択点での閾値比較

| 診断用confidence | 残る候補枠 | 赤領域に重なる候補枠※ | 黄色の候補枠 | コーンではない手付近の候補 | 10途切れ代表点のうち赤領域候補がある点 |
|---|---:|---:|---:|---:|---:|
| 0.05 | 33 | 19 | 12 | 2 | 9 |
| 0.10 | 18 | 17 | 0 | 1 | 9 |
| 0.25 | 2 | 2 | 0 | 0 | 0 |

※重複、端の断片だけの枠、人物側へ広がった枠も含む。「TP数」ではない。同じ物理コーンが複数枠・両レンズに出るため、物体数でもない。
原本：[review_threshold_summary.csv](review_threshold_summary.csv)、[reviewed_candidates.csv](reviewed_candidates.csv)。

0.10に下げた場合、選択した9点には赤領域候補が残るが、frame3207では人の手付近の誤候補もscore 0.20188で残る。
したがってconfidenceだけで真のコーンと誤候補を分離できるとは言えない。
以前の38注釈画像でも0.10で重複候補が残っており、今回の点診断だけを根拠に本番閾値を採用しない。

## 途切れ代表点の内訳

| frame | 選択した赤領域候補score | 目視状態・注意点 |
|---|---:|---|
| 22 | 0.21789 | 小さい赤コーンが机の後ろに部分的に見える |
| 33 | 0.19392 | 小さい赤コーンと机脚が重なる |
| 51 | 0.24414 | 人が傾けて運搬中 |
| 56 | 0.24696 | 同上。0.25に近いが閾値採用の根拠には不足 |
| 63 | 0.18340 | 小さい傾いたコーンを運搬中 |
| 1462 | 0.16341 | 持ち上げ中。候補は上部・左側を十分含まず、人物と混在する別枠もある |
| 2872 | 0.14644 | 持ち上げ中。候補上端が人物側へ伸びている |
| 3207 | 0.23318 | 魚眼端に赤本体・台座断片。全体の位置は未確定 |
| 3213 | 該当なし | 赤台座断片の領域には0.01以上のNMS後候補なし。最高score候補は人の手付近で、代用不可 |
| 4566 | 0.20427 | 赤本体に重なるが先端を含まず、下端が床側へ伸びる候補 |

9点のscore範囲は0.14644〜0.24696。全部が0.25未満なので、既存設定で出力されなかったことは確認できる。
ただし「赤領域に候補がある」ことと「物体全体の枠が正しい」ことは分ける。手動GT bboxは新規作成しておらず、IoU・位置誤差・距離誤差を測定していない。
frameごとの根拠原画像と注記：[gap_point_diagnosis.csv](gap_point_diagnosis.csv)、[review_catalog.json](review_catalog.json)。

## 最大下端変動の2点

frame4553・4554は途切れ点ではなく、前回の最大下端変動の比較点。右画像の最高候補は以下。

| frame | score | x1 | y1 | x2 | y2 |
|---|---:|---:|---:|---:|---:|
| 4553 | 0.61954 | 1168.810 | 287.007 | 1256.693 | 458.581 |
| 4554 | 0.75294 | 1170.837 | 296.206 | 1255.713 | 486.827 |

33.385 msで枠下端y2が28.2456 px移動。原画像では赤コーンが左右レンズの端に分かれて見え、4553の枠下端は台座下端まで届いていないように見える。
部分形状に対する枠の切り替わりが寄与した可能性はあるが、物体自体も移動しているので、28 px全部を検出ノイズと断定しない。
低floorでは反対レンズの赤断片や同じ断片の別枠も出る。複数枠を複数障害物として即採用しない。

## 次の実装・評価で守る区別

1. **検出候補**：class/score/bbox/原画像座標/時刻/モデルhash。赤・黄色の一種類classであることを保持する。
2. **床面の距離測定として有効か**：接地点が見える、床に置かれている、魚眼端の欠けでない、対象レンズの校正に対応する、を別に検証する。bbox下端を無条件に接地点へ変換しない。
3. **TTC/FFB入力**：距離と時系列の有効性が確認できてから接続する。候補があるだけで有効距離・安全状態を生成しない。検出途切れを自動補間して「見えている」扱いにしない。

上記は次回の接続条件の整理であり、runtimeの判定や安全ゲートを今回変更したわけではない。
追加の既存走行録画が見つかったら、固定済みモデル・設定で別フォルダへ評価し、接地したコーン・端欠け・対象なし区間を分けて確認する。
ただしコーンが映っていない走行動画は負例・処理時間評価には使えるが、コーン検出Recallの検証には使えない。
新しい背景・物体配置での独立testは未実施。Bは以前のval録画であり、再診断の結果を独立testとして扱わない。

## 成果物・再現

- [グラフ](gap_candidate_confidence.png)：10途切れ代表点の赤領域候補scoreと0.10/0.25。
- `predictions.csv`：0.01以上の全97候補。`timing.csv`：12点の実測時間（初回含む）。
- `provenance.json`、`environment_freeze.txt`：GPU・依存関係・重み・実行コード・入力hash。
- [review_verification.json](review_verification.json)：集計入力/出力/生成scriptのhash、高score枠の再現チェック。
- 推論helper：`src/run_cone_review_frames.py`。GPUなしの`--dry-run`は入力確認だけで、推論成功とは表示しない。

リポジトリ直下で、**未使用の出力先**を指定する。venvを作り直す必要はない。

```bash
./yolo-env/bin/python3 src/run_cone_review_frames.py \
  --input-dir Experimental_results/2026-10-13/cone_video_b_r01 \
  --weights runs/cone/received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt \
  --output-dir Experimental_results/2026-10-13/cone_video_gap_predictions_r02 \
  --prediction-floor 0.01 --device 0
```

集計再現（r01の固定目視記録に対して。別推論結果を無確認で流用しない）：

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-13/cone_video_gap_predictions_r01/analyze_gap_candidates.py
/home/robo25/theta-env/bin/python3 -m unittest discover -s Experimental_results/2026-10-13/cone_video_gap_predictions_r01 -p 'test_gap_candidates.py'
/home/robo25/theta-env/bin/python3 -m unittest discover -s tests -p 'test_*cone*.py'
```

検証：関連100テストPASS（新helper10、既存90）。目視集計7テストPASS。原画像・元モデルを変更せず、学習やROS通信、物理FFBは行っていない。
