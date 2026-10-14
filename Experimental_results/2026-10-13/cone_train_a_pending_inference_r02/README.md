# A未注釈170枚のオフライン推論（2026-10-13）

完了結果：原画像170枚、NMS後confidence0.01以上819候補、max_det到達0枚。
`summary.json`・`provenance.json`・`predictions.csv`・`timing.csv`を保存した。
元PNG/画素hashを推論前後に照合。同じbest.ptをRTX 3070で使用し、学習や物理FFBは行っていない。
未注釈の学習側画像なので、候補数を精度や独立testの合格と解釈しない。

入力manifestは[学習候補170枚](../cone_train_a_hardcase_preparation_r01/candidate_manifest.csv)。
選別結果と次の確認手順：[準備報告](../cone_train_a_hardcase_preparation_r01/README.md)。

再推論には既存venv・重みを使い、未使用の出力先を指定する。

```bash
./yolo-env/bin/python3 src/run_cone_review_frames.py \
  --input-dir datasets/cone/ab_dev_v01 \
  --manifest Experimental_results/2026-10-13/cone_train_a_hardcase_preparation_r01/candidate_manifest.csv \
  --weights runs/cone/received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt \
  --output-dir Experimental_results/2026-10-13/cone_train_a_pending_inference_r03 \
  --prediction-floor 0.01 --device 0
```
