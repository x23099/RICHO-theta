# 既存コーンモデルの画像別・confidence別診断（2026-10-13）

## 到達点

前日の[日報](../../../Daily_reports/2026-10-12_daily_report.md)を受け、`start_cone_yolo.sh diagnose`を追加した。
既存のbest.ptと既存val Bを使い、画像別の予測枠・confidenceと、固定閾値別の見逃しを保存できる。
学習・録画・カメラ・ROS・FFBを起動する処理ではない。

**実装と合成データテストは完了。GPU PCでの実モデル診断はまだ実行していない。**
この解析PCにはtorch/ultralyticsがなく、GPU推論や新しい検出精度の数値を得たとは扱わない。
診断の実行手順は[GPU PC手順](gpu_procedure.md)。Gitへの追加・コミット・PUSHは今回まだ行っていない。

## 実装

- [run_cone_yolo.py](../../../src/run_cone_yolo.py)：diagnose起動、データ検査、GPUチェック、単一クラスモデル確認、来歴保存。
- [cone_detection_diagnostics.py](../../../src/cone_detection_diagnostics.py)：原画像へのpredict、元pixel座標とconfidenceの保存、正解との対応、閾値/属性別集計。
- [test_cone_detection_diagnostics.py](../../../tests/test_cone_detection_diagnostics.py)：合成結果を使う対応・集計・出力・拒否・無改変テスト。

既存のenv/train/val/testを維持。diagnoseではlabel cacheの削除もしない。
datasetと出力先の重なり・既存出力の上書き・checkpointフォルダ内への出力を拒否する。
独立testのないdatasetへ`--diagnostic-split test`を指定すると、GPUやmodelの読み込み前に拒否する。

## 固定条件と解釈

| 項目 | 条件 |
|---|---|
| 対象 | defaultはval B。trainを評価画像へ混ぜない |
| 元画像 | 1280×720、全dual-fisheye、無加工PNG |
| 推論 | imgsz=960、rect=false、FP32（quantize=32）、batch=1、augmentationなし |
| 予測保存floor | confidence=0.01 |
| 集計confidence | 0.05、0.10、0.25、0.50、0.75 |
| NMS | IoU=0.70、max_det=300 |
| 正解との対応 | IoU>=0.50、confidence降順で最良の未対応正解へ一対一のgreedy対応 |
| size区分 | 正解枠の元pixel高さ：small<32、medium<96、large>=96 |
| 左右区分 | 正解枠中心の画像左半分/右半分。前方/後方と自動的に同一視しない |

予測保存floor以上のNMS後の枠を1回取得し、同じ枠へ各confidence閾値を適用する。
TPは正解に対応した枠、FPは対応しない予測枠、FNは対応しない正解枠。
予測0件のPrecisionは未定義（CSV空欄）とし、正解がある場合のRecallは0となる。
同じ正解へ複数の予測がある場合は一対一で対応し、余分な枠をFPへ数える。

**この固定閾値診断はUltralyticsのval/mAPを再現する実装ではない。**
前日のRecall64.3%と今回のconfidence=0.25のRecallが違っても、それだけで退行と判定しない。
元のvalはconfidenceの探索や評価内部条件があり、こちらの入力padding/演算精度/対応規則も明示して別記録にした。
floor未満のscore、NMS前に消えた候補は保存されない。max_det到達はtiming.csv/summaryで警告材料として残す。
閾値を下げるのは診断のためで、本番の採用閾値やFFB許可条件を変更したものではない。

## 出力

| ファイル | 内容 |
|---|---|
| predictions.csv | 全NMS後予測のimage、index、class、confidence、元pixel xyxy |
| ground_truth.csv | 正解枠、index、元pixel xyxy、サイズ・左右・属性、label hash |
| image_manifest.csv | session、frame、時刻、解像度、PNG/元rawの来歴 |
| per_image.csv | 各画像×confidenceのTP/FP/FN |
| matches.csv | 個別のTP/FP/FNと対応gt_index/prediction_index/IoU |
| threshold_summary.csv | 閾値ごとの件数・Precision/Recall |
| stratum_recall.csv | GTサイズ・左右・確認済み属性ごとのRecall |
| timing.csv | 各画像のpredict+export時間、framework内preprocess/inference/postprocess、初回call区分 |
| attributes_template.csv | 色・前後・遮蔽を人が確認するための雛形 |
| diagnostic_summary.json / analysis_report.md | 診断完了記録・条件・制約・集計 |
| provenance.json / environment_freeze.txt | model/dataset/codeのhash、GPU・依存版・実行条件 |
| raw_examples/ / raw_example_manifest.csv | 参照閾値でFN+FPが多い順に最大3枚。原PNGとbyte一致する無加工コピーと選択理由 |

raw_examplesは診断結果から選ぶ例であり、事前に選んだ独立評価標本ではない。
枠を描いた画像は保存しない。FNのimage/gt_indexをmatches.csvで調べ、ground_truth.csvの座標と元画像を対応付ける。
timingには初回起動・転送等が含まれ得る。実カメラの連続FPSやFFB遅延として使わない。

## 属性の確認

赤・黄色をまとめた単一クラスの既存labelには色・レンズ・遮蔽の属性がない。
HSVやファイル名から決めず、初回はすべてunknownにする。
必要に応じてattributes_template.csvを別ファイルへコピーして人が確認し、
`--object-attributes /path/to/reviewed_attributes.csv`で次の診断へ渡せる。
色はred/yellow/other/unknown、レンズはfront/rear/unknown、遮蔽はnone/partial/unknown。
確認した属性にはnoteを記入する。gt_indexは正解labelの0始まり順序で、label hashが変わったものは拒否する。
属性の追加で正解bboxやdatasetのレビュー内容は変更しない。
画像別の見逃しを把握した後、再推論を避けた既存CSVの属性別再集計は必要に応じて次に用意する。

## ローカル検証

関連unit testは既存51件＋新規23件の計74件PASS（GPU/モデル結果はMock・合成データ）。
実datasetの読み取り検査はPASS、val B=38画像/56枠。元pixel高さでlarge=51、medium=5、small=0、
画像左半分13枠/右半分43枠、色・前後は56枠すべてunknown。これらは入力正解枠の集計で、モデル検出結果ではない。
構文検査、shell構文検査、diff空白検査、実在する受領checkpointを指定したdry-runも確認した。
詳細：[verification.json](verification.json)。本番bird_eye/TTC/FFBの変更・実機回帰は行っていない。

## 公式根拠

- [Ultralytics predictの引数](https://docs.ultralytics.com/modes/predict/)：confidence、NMS IoU、rect、保存の抑止を明示する。
- [GPU PCと同じ8.4.175のdefault設定](https://github.com/ultralytics/ultralytics/blob/v8.4.175/ultralytics/cfg/default.yaml)：FP32はquantize=32を用いる。モデル世代は既存YOLOv8nのままで、最新世代へ移行しない。
- [BoxesのAPI](https://docs.ultralytics.com/reference/engine/results/#ultralytics.engine.results.Boxes)：xyxy/conf/clsを使用し、モデル結果を画像別CSVへ保存する。
- [8.4.175の設定フォルダ実装](https://github.com/ultralytics/ultralytics/blob/v8.4.175/ultralytics/utils/__init__.py)：YOLO_CONFIG_DIR配下Ultralyticsのparentがなければ/tmpへ退避し得るため、import前にrun専用フォルダを作成した。GPUで警告が解消するかは次の実行で確認する。
