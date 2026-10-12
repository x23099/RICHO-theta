# コーンYOLO 明示的val受領結果（2026-10-12）

判定：**開発用Bのval実行完了と、学習済みbest.pt・人の確認済みデータの一致を確認。実用精度の合格やFFB接続完了ではない。**

受領原本：`/home/robo25/Downloads/val_ab_bootstrap_v01_r01.tar.xz`。
アーカイブ内の3ファイル（provenance・metrics・環境freeze）を保存した。
パス・重複・link・特殊ファイル・件数・展開容量を検査し、任意のパスへtar展開はしていない。
元録画、dataset、checkpoint、カメラ生画像は変更していない。解析PCでモデルの読み込み・推論は実行していない。

## 整合性

- best.ptのSHA256が学習結果で受領したbest.ptと一致。
- manifest、reviews、全ラベル、data.yamlのSHA256と件数が学習provenanceと一致。
- val B：38枚、56枠。train A：35枚、53枠。
- GPU：RTX 4070 Laptop GPU、torch 2.7.1+cu118 / CUDA 11.8、Ultralytics 8.4.175。
- 記録された検証引数：split=val、imgsz=960、batch=8、device=0、workers=0、plots=false。
- status=COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL、physical_output=false。

検査結果と原本hashは[verification.json](verification.json)、数値比較は[metric_comparison.csv](metric_comparison.csv)。

## 指標

| 指標 | 学習終了後の報告値 | 今回の明示的val | 差（percentage points） |
|---|---:|---:|---:|
| Precision | 93.818% | 93.775% | -0.043 |
| Recall | 64.286% | 64.286% | 0.000 |
| mAP@0.50 | 94.136% | 94.134% | -0.002 |
| mAP@0.50:0.95 | 77.870% | 77.233% | -0.636 |

大きく崩れた結果ではないが、同じ重み・データでも完全同一の数値ではなかった。
実際の評価内部の設定差や演算条件など、差の原因は今回の集計ファイルだけでは特定していない。
APは閾値を変えた曲線の集計で、mAP94%を「常に94%の対象を検出する」と解釈しない。
Recall64.3%は画像別診断を必要とする。赤・黄が同一クラスであり、赤だけの見逃し率は未算出。

## 次の作業・未評価範囲

このarchiveには画像別の予測枠・confidence・正解との対応・速度計測が含まれていない（bestディレクトリは空）。
そのため、どの画像のどのコーンを見逃したかまでは判定できない。
次は**同じbest.ptで既存B画像への推論結果を保存し、confidence別・赤/黄・前後レンズ・対象サイズ別に確認する**。
追加録画や再学習を先に行う必要はない。画像別診断用の出力処理・コマンドはまだ未実装で、今回実行したとは扱わない。

全73枚がpositiveで、コーン皆無のnegativeは0枚。Bは開発用valで独立testはない。
未知コースでの性能、背景のみの誤検知、推論FPS、距離/床接地点/TTC/FFB連携は未評価。

## 解析再現

```bash
python3 Experimental_results/2026-10-12/cone_ab_bootstrap_validation/analyze_validation_result.py \
  --input /home/robo25/Downloads/val_ab_bootstrap_v01_r01.tar.xz
```
