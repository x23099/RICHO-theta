# コーン画像別診断

オフライン診断完了。実用精度や実機安全性の合格ではない。

| confidence | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| 0.05 | 56 | 184 | 0 | 0.2333 | 1.0000 |
| 0.1 | 56 | 157 | 0 | 0.2629 | 1.0000 |
| 0.25 | 56 | 88 | 0 | 0.3889 | 1.0000 |
| 0.5 | 50 | 7 | 6 | 0.8772 | 0.8929 |
| 0.75 | 16 | 0 | 40 | 1.0000 | 0.2857 |

IoUを満たす未使用正解枠へconfidence降順で一対一対応する診断値。
Ultralytics valの集計RecallやmAPと同一条件・同一値とは扱わない。
NMSのIoUと正解対応のIoUは別設定。色・前後・遮蔽は確認情報がなければunknown。
raw_examplesは原PNGのbyte一致コピーで、枠・注釈・補正なし。
matches.csvでFNのimage/gt_indexを探し、ground_truth.csvの枠座標と原画像を照合する。
attributes_template.csvは人の属性確認用。datasetの正解ラベルを変更するものではない。
timing.csvの最初の呼出しは準備時間を含み得る。実カメラFPSの証明ではない。
