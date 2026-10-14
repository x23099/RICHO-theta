# D負例16枚の追加・52枚版再学習（2026-10-14）

## 結論

**人がコーンなしと確認した16枚を追加し、52枚版の作成・50 epoch再学習・B/D/Eの比較まで完了した。**
水筒への誤検出とBでの余分な枠は減った。一方、固定confidenceでは正しいコーンのscoreも下がり、見逃しが増える条件がある。
**52枚版は開発候補として保管し、運用採用は保留。** HSV・距離/TTC・ROS・FFBや運用モデル参照先は変更していない。

追加録画は今すぐ必要ない。次は評価Eの24枚のhuman labelを確認する。

## 人の確認と追加データ

ユーザー回答「全てコーンを確認できませんでした。進めてください」は、直前に案内したDの16枚についてのコーン不在確認として扱った。
GUI記録には15枚のnegativeと先頭1枚のpendingがあり、他15枚の保存label/reviewは変更していない。
先頭のD01 frame1だけ、今回の明示的な全画像確認を根拠にCLIでnegative記録を完了した。
GUIで保存したと偽らず、noteへchat確認と記した。[input_receipt.json](input_receipt.json)に変更前後review hashと根拠を保存。

- 確認前GUIレビューhash：`0f10195e907c4d9877d4e332d02ad3a8b2ad705e4f4a9dac72de2497941804a1`。
- 最終Dレビュー：negative16、pending0。空labelのhashは全てSHA256(empty)。
- [human_review_snapshot.csv](human_review_snapshot.csv)：確認済みDレビューのsnapshot。
- [added_negative_manifest.csv](added_negative_manifest.csv)：追加16枚の原画像来歴。

| データ | 今回の構成 |
|---|---|
| `datasets/cone/ab_negative_augmented_v04` | train52枚：positive36、negative16、正解枠55 |
| 既存B val | 38枚・正解枠56。画像・labelは元36枚版とバイト同一 |
| D01/D02 | 学習に追加した負例。D02水筒は非コーンとして扱う |
| E01/E02/E03 | 学習に含めない。raw/source/group/pixelの重複なし |

元の35枚版・36枚版・D/E原録画・Eのレビューは維持した。
52枚版の`merge_verification.json`・dataset整合性PASS、全referenceの画像/labelバイト一致を検査済み。
Eはdata.yamlのない評価用queueのまま、human labelはまだpending。
原画像は1280×720・全画角、枠・切り抜き・補正なし。dataset/model runはGit対象外。

## 学習条件

初期weightsは`src/yolov8n.pt`、SHA256 `31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95`。
既存36枚modelの継続学習ではなく、以前と同じ初期checkpointから再学習した。
RTX3070、torch2.14.1+cu130、Ultralytics8.4.175、50 epoch、batch8、imgsz960、seed0、FP32、workers0。
offline、外部logger停止、plots=false、driver/venv/global設定は変更しない。

35/36/52の実`args.yaml`を照合し、data/project/save_dir以外の差がないことを確認。
GPU・依存version・初期weights hashも一致。元35/36の成功済み学習結果を再利用した。
単一seedの開発比較。枚数増加で1 epochあたりの更新回数も変わるため、「負例だけの純粋な因果効果」とは断定しない。

実run：`runs/cone/train_ab_negative_v04_local_20261014_r01`。
Ultralyticsの実保存名は`yolov8n`。使用bestは`yolov8n/weights/best.pt`、SHA256
`e613f9a5c20d83fc537bb41495e358d7583c3962b7ed2d229454abef70225c5d`。

## 学習終了時bestの集計

| model | train画像 | mAP50 | mAP50–95 | 学習best検証Recall | epoch CSVの累積時間 |
|---|---:|---:|---:|---:|---:|
| 基準35枚 | 35 | 98.42% | 78.94% | 98.21% | 151.426秒 |
| 追加36枚 | 36 | 98.88% | 78.31% | 98.21% | 154.639秒 |
| 負例追加52枚 | 52 | 99.07% | 83.39% | 95.83% | 188.964秒 |

mAPが上がっても固定confidenceで全てのコーンを保持できるとは限らない。
これは最終epochそのものではなく、Bで選ばれたbest weightsを再検証した値。
最終epoch CSVには低いRecallが出たが、評価には自動保存されたbestを使用し、lastと混同していない。
時間はCSV内のepoch累積で、コマンド全体・モデル起動・後続診断を含まない。共有GPUの厳密benchmarkではない。

## 既存B：固定confidence比較

全38画像、human確認済み56枠を同じIoU0.5・1対1で照合。confidenceは変更せず0.25/0.50を比較。

| 閾値 | model | TP | FP | FN | Precision | Recall |
|---|---|---:|---:|---:|---:|---:|
| 0.25 | 35枚 | 56 | 39 | 0 | 58.95% | 100.00% |
| 0.25 | 36枚 | 56 | 88 | 0 | 38.89% | 100.00% |
| 0.25 | 52枚 | 53 | 12 | 3 | 81.54% | 94.64% |
| 0.50 | 35枚 | 55 | 2 | 1 | 96.49% | 98.21% |
| 0.50 | 36枚 | 50 | 7 | 6 | 87.72% | 89.29% |
| 0.50 | 52枚 | 13 | 0 | 43 | 100.00% | 23.21% |

0.25の52枚版は赤16/18、黄37/38。0.50では赤13/18、黄0/38。
FP0だけを成功と見ない。0.50の52枚版は多くの対象を見逃すため、採用条件にはできない。
FP数は別物体だけでなく重複・位置不良も含む。

0.25の3見逃しには、十分重なる候補自体は存在した：

| Bの対象 | 最大重なりIoU | 候補score |
|---|---:|---:|
| 赤、frame2101 | 0.8341 | 0.18950 |
| 黄、frame3601 | 0.9131 | 0.23001 |
| 赤、frame4201 | 0.9208 | 0.19801 |

位置が完全に取れなくなったのではなく、この3枠ではscoreが0.25未満に下がっていた。
だからといって閾値を下げて採用していない。負例と正例の保持を両立できるか、全条件で比較する必要がある。
単一実験ではscore低下の原因を断定しない。

## D：水筒への出力

| confidence0.25で水筒をコーンと予測したframe | 35枚 | 36枚 | 52枚 |
|---|---:|---:|---:|
| D02の抽出8枚 | 8/8 | 3/8 | 0/8 |

**52枚版にとってD02は学習に使った画像。** 0/8は学習内容の再確認で、未見の水筒への汎化成功ではない。
同じ水筒1個の反復であり、8種類の水筒でもない。
今後は別配置・別の非コーン物体への確認が必要だが、今回のラベル確定に追加録画は不要。

## E：学習に未使用の参考照合

同じ24PNG・同じassistantの目視参考領域で比較。**正式human GTではない**。
E02の赤・黄は3モデルとも0.25/0.50で各8/8関連付け。
E03の赤も3モデルとも各8/8だった。

| E03黄色の参考領域へ関連付いたframe | 35枚 | 36枚 | 52枚 |
|---|---:|---:|---:|
| confidence0.25 | 7/8 | 8/8 | 6/8 |
| confidence0.50 | 1/8 | 5/8 | 6/8 |

52枚版のE03 frame940/1097、配置変更後の小さく映った黄色はscore0.13657/0.14047で0.25未満。
この2画像にも参考領域へ重なる候補は存在する。黄色の保持が完全に改善したとは言えない。
E01のコーンなし8枚は全モデルで0.25/0.50の予測0枠。ただしhuman negative GTの全画角確認はpending。
同じ物理コーンや室内背景の繰り返しで、完全に未知のコースや走行・FFB性能を保証しない。

## 次の作業：評価Eの人による確認

この解析PCで次を実行：

```bash
cd ~/theta_ws/RICHO-theta
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/de_evaluation_review_v01 \
  --split val
```

全24枚のうち、E01の8枚は両レンズにコーンがなければN→Y。
E02/E03の16枚はP→見える赤・黄コーンを台座まで囲む。各画像2枠、計32枠が目安。
Enterは1対象につき1回、選択終了はEsc、画面で確認してY。
人物・反射・水筒には枠を付けない。置き替え中などで判別が難しければSで保留して知らせる。
保存するのはlabel/reviewだけで、生PNGはそのまま。

この人確認後、Eの正式照合を行い、負例を増やすだけで正例を弱めていないかを判断する。
E画像はモデルのtrain/epoch選択に含めず、元Bも維持する。
今回は52枚版を自動採用せず、モデル選択・追加の学習条件変更は次の判断事項として残した。

## 成果物・再現

- [比較グラフ](negative_retraining_comparison.png)：Bの余分な枠、学習D水筒、E03黄色参考照合。scopeを分けて表示。
- [training_metrics.csv](training_metrics.csv)：best検証指標。
- [b_fixed_thresholds.csv](b_fixed_thresholds.csv)、[b_color_recall.csv](b_color_recall.csv)：同じBの固定条件照合。
- [d_water_bottle_resubstitution.csv](d_water_bottle_resubstitution.csv)：学習場面での水筒出力。
- [e_target_associations.csv](e_target_associations.csv)、[e_color_reference_summary.csv](e_color_reference_summary.csv)：未human確定のE参考照合。
- [miss_cases.csv](miss_cases.csv)、[miss_verification.json](miss_verification.json)：5つの低score事例。
- [comparison_summary.json](comparison_summary.json)：条件・model/hash・結果・非採用の記録。
- `negative_52_{args.yaml,results.csv,metrics.json,provenance.json}`：小容量の学習来歴コピー。

新たな画像加工はしない。D/Eの原画像は[受入れ原画像](../cone_de_intake_r01/README.md#原画像グラフ)を再利用。
グラフ生成scriptは`analyze_retraining.py`、元CSV・hashが同folderから追跡できる。
集計時に旧診断CSV名を`aggregate.csv`と誤記した1件は、実在する`threshold_summary.csv`へ修正。
推論結果・dataset・modelを再計算/改変せず、集計だけ再実行して完了した。

再現は新しいrun/output名を指定：

```bash
./start_cone_yolo.sh train \
  --dataset datasets/cone/ab_negative_augmented_v04 \
  --weights src/yolov8n.pt \
  --output-dir runs/cone/train_ab_negative_v04_local_20261014_r02 \
  --device 0 --epochs 50 --batch 8 --imgsz 960 --seed 0 \
  --offline --amp-mode fp32
```

データ整合性・val/元画像保護・E除外・学習全50 epoch・実args共通・model/input hash照合を確認。
merge関係の合成テスト12件PASS、関連145件の既存成功は再利用。
Python構文、diff空白、2Dグラフ目視、追加診断の完了来歴を検査した。
実機操作・ROS通信・FFB振動・新コース走行は未実施。Git commit/pushは今回依頼されていないため行っていない。
