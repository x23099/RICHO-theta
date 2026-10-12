# コーンYOLO初回学習結果（2026-10-12）

判定：**50 epochの学習完了を確認。コーン検出の試作重みを取得した。実用精度・距離/TTC/FFBへの接続・独立testの完了ではない。**

受領原本：`/home/robo25/Downloads/train_ab_bootstrap_v01_r01.tar.xz`。受領7ファイルのパス、link、重複、展開上限100 MiBを検査し、モデル重みを含む原本は改変せず、Git対象外の`runs/cone/received_train_ab_bootstrap_v01_r01/`へ保存。重みの存在・非空・SHA256は確認したが、この解析PCではcheckpointをデシリアライズしたり、モデル推論を実行していない。

小容量のCSV・metrics・provenance・args・環境freezeをこのフォルダへ保存。原本・checkpointのhashと検査結果は[verification.json](verification.json)。再現スクリプトは[analyze_training_result.py](analyze_training_result.py)。

## 学習の整合性と実測時間

| 項目 | 確認結果 |
|---|---|
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU |
| PyTorch / CUDA | 2.7.1+cu118 / 11.8 |
| Ultralytics | 8.4.175 |
| 初期重み | リポジトリのyolov8n.ptとSHA256一致 |
| dataset | train A=35枚/53枠、val B=38枚/56枠 |
| 人の確認済みデータ | 受領したmanifest・reviews・全label hash・件数と学習provenanceが一致 |
| 設定 | epochs=50、batch=8、imgsz=960、device=0、workers=0、seed=0、plots=false |
| CSV epoch | 1～50、連番・欠落なし・数値有限 |
| 50 epoch時点の累積時間 | **76.4385秒（約1分16秒）** |
| 出力重み | best.pt / last.ptの両方あり |
| 学習provenance | COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL |

CSVの`time`は学習開始から各epochの指標保存までの累積値であり、学習ループとepoch内検証を含む。起動準備・最終のbest検証なども含めたコマンド全体の実行時間は今回記録されていない。76秒を全作業時間や将来の大規模datasetの所要時間として使わない。[公式実装の時間保存](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/engine/trainer.py)

## 開発用valの集計結果

下表は受領した`metrics.json`の値を採用する。CSVのepoch50の値も`verification.json`へ別途保存した。両者は末尾の数値が少し異なり、同一値として混同しない。公式trainerはループ終了後にbest.ptの検証も行うため、epoch内CSVと終了後の評価は別記録である。[公式trainer](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/engine/trainer.py)

| 指標 | 値 |
|---|---:|
| Precision | 0.93818（93.82%） |
| Recall | 0.64286（64.29%） |
| mAP@0.50 | 0.94136（94.14%） |
| mAP@0.50:0.95 | 0.77870（77.87%） |

Precisionは検出した枠の正しさ、Recallは正解対象をどれだけ拾えたかを示す。APはprecision-recall曲線を集計した別の指標であり、mAP94%を「常に94%のコーンが検出される」と解釈しない。[公式の指標説明](https://docs.ultralytics.com/guides/yolo-performance-metrics/)

今回の結果からは、初回学習が成立し、開発用val上で認識指標が得られたことを確認できる。ただしRecallが64.3%なので、見逃しの対象・confidence・位置・遮蔽を画像単位で確認する必要がある。赤色と黄色をまとめた単一クラス集計のため、赤コーンだけのRecallや見逃し個数をこの数値から断定しない。

## 学習曲線・未検証範囲

[学習曲線](../report_assets/cone_ab_bootstrap_training_curve.png)は受領CSVの全50 epochを使い、指標の推移とtraining lossを描いた。source CSV hash、生成スクリプト・画像hashはverificationから追跡できる。画像にコーン枠を描いたものではなく、カメラ生画像は変更していない。

epoch間で検証指標が大きく揺れている。最終集計だけで安定した検出を保証せず、少数データと閾値等を含め、次の画像別診断で調べる。原因はこのCSVのみでは特定していない。

- 全73枚にコーンがあり、コーン皆無のnegativeは0枚。何もない場面の誤検知率は未評価。
- Bは調整用valで、独立testはない。未知コースや別環境に汎化したとは扱わない。
- 赤コーン別、黄色コーン別、前後レンズ別の性能は未算出。
- 距離/床接地点/TTC/FFBへの接続、白線逸脱、実カメラの推論FPSは未評価。
- 学習runの実保存先は`yolov8n/`。provenanceの要求引数`name=model`と実際の`args.yaml`の`name=yolov8n`・`save_dir`は異なる。この差を保存し、後続コマンドは実在する重みpathを使う。

## 次のGPU PCコマンド

学習済みbest.ptを固定して、明示的val実行を記録する。これも開発用Bの再評価で、独立testではない。その後にconfidence別・画像別の見逃し診断へ進む。今すぐ追加録画や再学習を要求する段階ではない。

```bash
cd ~/yopi_ws/RICHO-theta

./start_cone_yolo.sh val \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --weights runs/cone/train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt \
  --output-dir runs/cone/val_ab_bootstrap_v01_r01 \
  --device 0

tar -cJf ~/Downloads/val_ab_bootstrap_v01_r01.tar.xz \
  -C runs/cone val_ab_bootstrap_v01_r01
```

`--weights`は以前の案内にあった`model/weights/best.pt`ではなく、今回確認できた`yolov8n/weights/best.pt`。モデルrunは上書きせず、既存のval出力があれば未使用名を選ぶ。setup・ドライバー更新は不要。Ultralyticsの設定が/tmpへ退避した警告は別件として残るが、今回の学習完了やCSV保存の失敗ではない。

## 解析再現

```bash
python3 Experimental_results/2026-10-12/cone_ab_bootstrap_training/analyze_training_result.py \
  --input /home/robo25/Downloads/train_ab_bootstrap_v01_r01.tar.xz
```

同一原本は再利用できる。既存の受領重みと異なるarchiveの場合は上書きを拒否する。
