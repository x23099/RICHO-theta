# RTX 3070搭載解析PCでの初回画像別診断（2026-10-13）

このPC（`robo25-NUC11PAHi5`）のRTX 3070で、既存モデル・既存val Bによる画像別診断を実行し、38/38画像の処理を完了した。
別の学校GPU PCへ移動する必要はなかった。学習・追加録画・ドライバー/依存更新・ROS/FFB操作は行っていない。

## GPU確認と実行環境

制限付き実行ではnvidia-smiが失敗し/dev/nvidia*が見えなかったが、PCI一覧ではRTX 3070を確認した。
サンドボックス外の読み取り確認ではnvidia-smiとGPU tensor計算が成功した。
制限付き環境からGPUが見えないことを、物理GPU不在・driver故障・性能不足と解釈しない。

| 項目 | 確認結果 |
|---|---|
| GPU | NVIDIA GeForce RTX 3070、8192 MiB |
| driver | 580.178.04。既存のまま変更なし |
| Python | このリポジトリのyolo-env/bin/python3 |
| torch / CUDA build | 2.14.1+cu130 / 13.0 |
| Ultralytics | 8.4.175 |
| GPU確認 | cuda:0の2×2 onesのsum=4.0 |
| 実行コードの基点 | 0550dbc（YOLO学習３） |
| dataset | ab_bootstrap_v01、val B 38枚/56枠 |
| model | received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt |
| checkpoint | 10/12受領best.ptとSHA256一致 |
| 最終provenance status | COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL |

学校GPU PCのtorch 2.7.1+cu118と、このPCの2.14.1+cu130は同じ環境ではない。
今回は同じ重みで行う固定閾値診断として独立した来歴を保存し、前日のval/mAPと完全同一の評価とは扱わない。
新しいUltralytics設定ファイルはrun配下に作られ、/tmpへ退避する警告は今回出なかった。

## 初回結果

| confidence | 正解対応TP | 余分な予測FP | 見逃しFN | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| 0.05 | 54 | 7 | 2 | 88.5% | 96.4% |
| 0.10 | 22 | 1 | 34 | 95.7% | 39.3% |
| 0.25 | 18 | 0 | 38 | 100.0% | 32.1% |
| 0.50 | 18 | 0 | 38 | 100.0% | 32.1% |
| 0.75 | 17 | 0 | 39 | 100.0% | 30.4% |

confidenceを0.05から0.10へ上げると正解に対応する予測が54→22へ減った。
低confidenceの正解候補が多くあることが分かる一方、0.05では余分な枠7件も残る。
これだけで本番閾値を0.05へ変更せず、matches.csvと原画像で正解対応・余分な検出を確認する。
全予測は保存floor=0.01以上のNMS後236枠。max_det=300へ到達した画像は0枚。
色・前後レンズ・遮蔽の確認属性はunknownのままで、赤だけの検出率や見逃し原因はまだ未確定。
独立test・コーン皆無のnegative・実カメラFPS・距離/TTC/FFBの合格ではない。

条件・集計：[analysis_report.md](analysis_report.md)、[diagnostic_summary.json](diagnostic_summary.json)。
個別照合：[matches.csv](matches.csv)、[ground_truth.csv](ground_truth.csv)、[predictions.csv](predictions.csv)。
原画像3枚はraw_examples/へ無加工コピーし、[raw_example_manifest.csv](raw_example_manifest.csv)に元session/frame/hashと選択理由を保存した。

## 使用したコマンド

実行は完了しており、再度同じコマンドを打つ必要はない。同じ出力名は上書き拒否される。

```bash
cd /home/robo25/theta_ws/RICHO-theta

./start_cone_yolo.sh diagnose \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --weights runs/cone/received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt \
  --output-dir Experimental_results/2026-10-13/cone_ab_bootstrap_diagnose_r01 \
  --device 0
```

CodexからGPUを使う場合はサンドボックス外での実行承認が必要だった。
通常のユーザー端末での実行と、制限付きツール環境での実行を区別する。
ここから画像別の見逃し・余分な枠を診断できる。追加録画・再学習はまだ不要。
