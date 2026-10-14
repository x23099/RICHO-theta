# 修正後の再学習と同一PCでの比較（2026-10-14）

## 結論

**frame4651の修正は正常。追加15枚を保留し、1枚だけを追加した36枚版の作成・50 epoch学習・固定条件での評価まで完了した。**
ただし、今回の追加版は基準版より余分な予測が多く、採用は保留する。
以前ユーザーがコーンではないと確認したB右端の小物にも高いscoreを付けており、認識できる対象数だけでは合格にできない。
既存の運用設定・モデル参照先・HSV距離/TTC・FFBは変更していない。

## 修正後データ

- `a_hardcase_review_v02`のframe4651は赤・黄色をそれぞれ1枠、計2枠。重複なし、reviewのlabel hashと一致、原PNG/画素hashに変更なし。
- [selection_policy.csv](../cone_annotation_quality_r01/selection_policy.csv)に従い、残る15枚は追加から保留。保留をnegativeへ変換していない。
- `datasets/cone/ab_bootstrap_augmented_v03`を新規作成。train36枚/55枠、val38枚/56枠。
- 基準`ab_bootstrap_v01`はtrain35枚/53枠。追加は赤1枠・黄色1枠だけ。
- valの全38PNGとlabelはバイト同一であることを確認。元baselineと、以前の51枚版を上書き・削除していない。
- dataset整合性PASS。classは赤・黄色を含む`traffic_cone`1種類のまま。

追加が1枚だけなので、大規模なデータ拡充の結果ではない。判別が曖昧なコーンを推測してlabelにする作業もしていない。

## 比較条件

旧モデルはRTX 4070 Laptop GPU・torch2.7.1/cu118・AMPで学習したもの。
その結果を今回のRTX 3070での学習結果と単純比較すると、環境と追加画像の影響が混ざる。
そこで**基準35枚もこのPCで再学習**し、追加36枚と同じ条件で比較した。

| 条件 | 両run共通 |
|---|---|
| GPU | RTX 3070 |
| torch / CUDA | 2.14.1+cu130 / 13.0 |
| Ultralytics | 8.4.175 |
| 初期checkpoint | `src/yolov8n.pt`、SHA256 `31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95` |
| 学習 | 50 epoch、batch8、imgsz960、seed0、deterministic=true、workers0 |
| 計算精度 | FP32（amp=false） |
| 保存画像 | plots=false。生画像へ枠や補正を保存しない |
| 実際の保存名 | Ultralyticsが`name=model`を`yolov8n`へ変更。実在するpathで後続評価した |
| 診断 | valのみ、floor0.01、NMS IoU0.7、max_det300、imgsz960、rect=false、batch1 |
| GT照合 | score順、未対応GTとのIoU0.5以上、1対1 |

実保存`args.yaml`はdata/project/save_dirだけが異なることを検査した。GPU・依存version・初期checkpoint hashも一致。
ラベル由来の赤/黄色属性も同じCSVを使用。色はYOLOの出力classではなく、以前の原画像目視属性をGTへ対応付けている。
単一seed・少数・同環境の開発比較で、追加1枚の因果効果や汎化性能を証明したものではない。

## 学習終了時のbest検証指標

| 指標 | 同PC基準35枚 | 追加36枚 |
|---|---:|---:|
| Precision | 96.08% | 97.24% |
| Recall | 98.21% | 98.21% |
| mAP50 | 98.42% | 98.88% |
| mAP50–95 | 78.94% | 78.31% |
| epoch CSVの50 epoch累積時間 | 151.426 s | 154.639 s |

これらはtraining終了時のbest検証の`metrics.json`。下の固定confidence診断とは動作点・集計方法が異なり、同一precision/recallとして混同しない。
CSV累積時間はコマンド全体の実時間ではない。他のGPU処理が実行中だったため、厳密な学習速度ベンチマークでもない。他のプロセスは停止していない。

## 固定confidenceでの比較

全38画像・56正解枠（赤18、黄色38）で照合した。

| confidence | model | TP | FP | FN | Precision | Recall |
|---|---|---:|---:|---:|---:|---:|
| 0.25 | 基準35枚 | 56 | 39 | 0 | 58.95% | 100.00% |
| 0.25 | 追加36枚 | 56 | 88 | 0 | 38.89% | 100.00% |
| 0.50 | 基準35枚 | 55 | 2 | 1 | 96.49% | 98.21% |
| 0.50 | 追加36枚 | 50 | 7 | 6 | 87.72% | 89.29% |

0.25では両方とも赤18/18・黄色38/38を照合できたが、追加版はFPが39→88へ増えた。
0.50でも赤は両方18/18、黄色は基準37/38に対して追加32/38。追加版の優位は確認できなかった。
0.50は今回の診断条件であり、本番設定へ採用していない。

FP数は「コーンではない別物体の個数」と完全には同じでなく、重複や位置不良も含む。
検証の全画像に少なくとも1個のコーンがある。コーン皆無のnegative、別コースの独立test、実機の不要振動率は未測定。
同じ物理コーンの複数frameが含まれるため、赤18/18を独立した18個のコーンでの成功と解釈しない。

## 確認済み非コーン領域への誤検出

10/13にユーザーから「コーンではない」と確認を受けた、B右端の小物2箇所を、**その同じ画像**で再照合した。

| 同じ非コーン領域 | 基準35枚score | 追加36枚score |
|---|---:|---:|
| B赤ありframe301、右端上側 | 0.02458 | 0.59326 |
| B赤なしframe541、右端下側 | 0.01532 | 0.55835 |

追加版では0.50でも残る明確な誤候補。黄色を拾えるようになったことだけでは、この誤検出を許容できない。
背景・位置・部分形状などへの依存は考えられるが、この1回の比較で原因を断定しない。
これらのB画像をそのままtrainへ追加すると検証データの再利用になるため、行っていない。
元のユーザー確認：[review_catalog.json](../../2026-10-13/cone_ab_visual_review_r01/review_catalog.json)。
照合CSV：[confirmed_noncone_cases.csv](confirmed_noncone_cases.csv)、hash：[false_positive_case_verification.json](false_positive_case_verification.json)。

## 保存先と次の作業

- 同PC基準モデル：`runs/cone/train_ab_baseline_local_20261014_r01/yolov8n/weights/best.pt`。
- 追加版モデル：`runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt`。
- 小容量集計・学習CSV・args・provenance：このフォルダ。元モデルrunはGit対象外。
- [比較グラフ](retraining_comparison.png)：学習曲線、赤・黄色別の固定閾値Recall。
- [閾値のPrecision/Recallグラフ](fixed_threshold_tradeoff.png)：検出数と余分な枠のtradeoff。
- [comparison_summary.json](comparison_summary.json)：実条件・モデル/入力hash・比較条件一致の検証。

**追加36枚版は採用保留。基準35枚の新モデルも実機採用を決めたわけではない。**
次は既存の別録画からコーン皆無・紛らわしい物体の候補画像を調べ、訓練側の負例と独立評価データを分ける。
対象が本当に不在か確認できたものだけをnegativeへ登録する。黄色が隠れていて曖昧な画像をnegativeにしない。
現時点では追加撮影や、今回の16枚のさらなる一括描き直しは要求しない。
距離/接地点の妥当性、TTC、YOLO→FFB接続は別の検証項目で、今回のモデル指標だけで進めない。

## 実行・環境に関する記録

`run_cone_yolo.py`に`--offline`と明示的な`--amp-mode fp32`を追加した。
使用中のUltralyticsの通常AMP確認は補助の`yolo26n.pt`を取得する場合があるため、それを避けるFP32条件を両runで揃えた。
ドライバー・venvの依存関係・グローバルUltralytics設定は変更していない。

最初の基準runでは、ローカルfontを準備した位置がライブラリの実参照先より1階層上だったため、Arial.ttf約755 KBが自動取得された。
外部モデルの取得ではない。取得されたfontはそのrun内の設定フォルダに保存され、元モデルやデータへの影響はない。
参照先を`ultralytics_config/Ultralytics/`へ修正し、local DejaVu Sansをlookup用のArial.ttf名でコピーすること、実参照先・hash・ONLINE=false・AUTOINSTALL=falseを後続runで確認した。
このfont aliasはArial書体そのものを意味しない。plots=falseの学習・数値比較条件は共通。
font配置を含む追加検査後、関連133テストPASS。構文確認・`git diff --check`も完了。

学習の再現（未使用の出力先を指定）：

```bash
./start_cone_yolo.sh train \
  --dataset datasets/cone/ab_bootstrap_augmented_v03 \
  --weights src/yolov8n.pt \
  --output-dir runs/cone/train_ab_augmented_v03_local_20261014_r02 \
  --device 0 --epochs 50 --batch 8 --imgsz 960 --seed 0 \
  --offline --amp-mode fp32
```

診断再現では実在する`yolov8n/weights/best.pt`と、`reviewed_attributes.csv`を明示する。
`analyze_comparison.py`と`analyze_false_positive_cases.py`は完了runのhash付き集計を生成する。
過去snapshotを上書きしないため、再実行時には新しい結果フォルダを使用する。
