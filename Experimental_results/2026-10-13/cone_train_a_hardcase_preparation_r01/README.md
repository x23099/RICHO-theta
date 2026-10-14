# 学習側Aの追加確認画像の準備（2026-10-13）

## 今回できたこと

既存のA録画から、次回の学習追加候補として確認する画像を準備した。追加録画・モデル更新・ROS/FFB出力は実施していない。
検証側Bを学習へ回すのではなく、既にtrainと宣言されたAの未注釈170枚だけを対象にした。
自動予測を正解ラベルへ変換せず、確認待ち16枚に絞った。

| 項目 | 結果 |
|---|---:|
| Aの未注釈・既存bootstrap未採用画像 | 170枚 |
| 同じbest.ptでの0.01以上のNMS後候補 | 819枠 |
| 全class合算の0.25以上候補が0の画像 | 0枚 |
| 0.25以上の複数候補がある画像 | 138枚 |
| 単一候補で端帯に中心がある画像 | 6枚 |
| その他の単一候補画像 | 26枚 |
| 確認用に選んだ画像 | 16枚 |
| 選択内訳 | 複数候補6・端帯4・単一候補の低score順6 |
| 確認用画像の保存サイズ | 約11.9 MB（PNG計11,881,848 bytes） |
| 選択画像の参考予測CSV | 0.05以上45枠 |
| 自動で確定した正解ラベル | 0件 |

この表の候補数はTP/FP数ではない。赤・黄色は同一classで、同じコーンが両レンズに出る場合もある。
複数枠は実際に複数のコーンがある可能性があり、自動的に誤検出とは判定していない。
「0候補0枚」も赤コーンのRecall 100%を意味しない。
今回の選別は人の確認を効率化するための優先順位であり、170枚が独立testになったわけではない。

## 入力と保存先

- 元の400枚の準備データ：`datasets/cone/ab_dev_v01`。train205枚中、既存確認35枚を除いたpending170枚。
- 現行baseline：`datasets/cone/ab_bootstrap_v01`。train35枚・val38枚。変更していない。
- 同じ重み：`runs/cone/received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt`。
- 重みSHA256：`f8f63446223ceac9e3d0f9227eae0ef814a2c569f1887748e10bf032821f8ad7`。
- 正常完了した推論：[cone_train_a_pending_inference_r02](../cone_train_a_pending_inference_r02/)。RTX 3070、imgsz960、floor0.01、NMS IoU0.7、batch1。max_det到達0枚。
- **使用する確認フォルダ：`datasets/cone/a_hardcase_review_v02`。**
- `a_hardcase_review_v01`は参照データsnapshotの固定を追加する前の準備版。使わずv02を使用する。既存ファイルは削除・上書きしていない。

画像は元PNGのバイト同一コピー。1280×720・全画角で、リサイズ・切り抜き・補正・注釈描画は保存画像にしていない。
元manifest・reviews・metadataの計6ファイルが準備前と同じhashであることを確認した。
capture group・元動画hash・画素hashで検証側との重複を拒否し、既存bootstrap画像の再採用も避けた。
同一session内の選択間隔は2秒以上。ただし2秒離すだけで独立した観測や異なる背景になるとは言えない。

未注釈のため今回の170枚で精度は計算していない。Bの失敗を必ず改善できる保証もなく、次の学習後に同じB評価条件で比較する必要がある。

## 無加工の代表画像

- [A frame4261](raw_examples/block_a_e68ece502c09e03a_f004261.png)：魚眼端の人物・赤コーン台座の断片。完全なコーン形状が見えないため要確認。
- [A frame4651](raw_examples/block_a_e68ece502c09e03a_f004651.png)：人物が近くでコーンを持っている場面。見えている台座下端が床への接地点とは限らない。

録画名：`cone_train_block_a_r01_20261012_153804_108`。
時刻・寸法・元raw/PNG/画素hash：[raw_example_manifest.csv](raw_example_manifest.csv)。
この2枚は確認準備の例であり、学習改善・距離測定・FFB成功の証拠ではない。

## 次に本人が行う確認

このPCの画面を使って実行できる。画像確認・ラベル付けにGPUは不要。OpenCVのQt5対応は確認済みだが、この作業ではGUIを開いていない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/a_hardcase_review_v02 \
  --split train
```

1. 各画像で`P`を押し、**両レンズの全ての見えるコーン（黄色も含む）**を枠で囲む。台座も対象に含め、不可視部分を推測して広げない。
2. 枠ごとにEnter/Spaceで確定し、全部選んだらEscで選択終了。`Y`でその画像のラベルを確認する。
3. コーンが本当に全くない場合だけ`N`→`Y`。赤コーンがないだけ、予測が0なだけではnegativeにしない。
4. 端の断片など判断が難しい画像は`S`で保留、終了は`Q`。保留を勝手にnegativeへ変換しない。

GUIの枠は画面表示上だけ。原画像には保存しない。
`advisory_model_candidates.csv`は参考座標であり、正解ラベルではない。今回の16枚に`.txt`ラベルは自動作成していない。

全16枚の確認が終わってから、**このPCで**新しい学習データを組み立てる。

```bash
./yolo-env/bin/python3 src/prepare_cone_training_review.py merge \
  --dataset datasets/cone/a_hardcase_review_v02 \
  --reference-dataset datasets/cone/ab_bootstrap_v01 \
  --output-dir datasets/cone/ab_bootstrap_augmented_v02

./yolo-env/bin/python3 src/cone_dataset.py check \
  --dataset datasets/cone/ab_bootstrap_augmented_v02
```

未確認・review後のラベル変更・元データとの不一致・val/testへの混入があれば拒否する。
確認時のnoteを見てhuman reviewの明示も要求するが、これは手続き上の自己申告チェックであり、人が実際に見たことをソフトウェアが証明するものではない。
確認保留が残ったら無理に通さず、その画像の扱いを相談する。
元baselineを上書きせず、valのPNG・ラベル・review内容をそのまま新データへコピーする。
16枚すべてを追加した場合はtrain51枚・val38枚になる。現時点ではこのmergeを成功実行していない。

merge/checkが通った段階で再学習に進む。新しいモデルの評価は旧baselineと同じ条件に固定し、学習データ数の増加だけで「改善」とは判定しない。
valは引き続き開発評価用で、独立testは別途必要。YOLO→距離/TTC/FFB接続の承認とは区別する。

## 実装と検証

- `src/prepare_cone_training_review.py`：pending train抽出、候補による選別、確認待ち画像集、human review後の新データmerge。
- `src/run_cone_review_frames.py`：外部`--manifest`を追加。元datasetにファイルを追加せず推論できる。
- `tests/test_cone_training_review.py`：13件。train/val混入、未確認、label変更、参照snapshot変更、既存出力などを拒否。
- `tests/test_cone_review_frames.py`：11件。外部manifestの追加列も検証。
- 関連テスト全114件PASS。前回の固定B代表点集計7件は変更なし。
- 実データで未確認queueのmergeを試し、意図どおり拒否（exit2）。`ab_bootstrap_augmented_v02`は生成されていない。
- 構文確認・`git diff --check`完了。GUIでの確認・追加ラベル・merge成功・再学習・改善評価・実機出力は未実施。

初回の`cone_train_a_pending_inference_r01`は外部manifestの`image`列とのキー衝突で停止した。元データへの影響はない。
追加列を許容するよう修正し、回帰テストを追加してr02へ再実行した。r01は不成功の記録として保持し、r02だけを採用する。

## 証跡と再現

- [candidate_manifest.csv](candidate_manifest.csv)：170枚の入力一覧（trainのみ）。
- [inventory.json](inventory.json)：元データの準備時snapshot。
- [queue_review_queue.csv](queue_review_queue.csv)：選択16枚と優先理由。
- [queue_candidate_features.csv](queue_candidate_features.csv)：170枚の選別用特徴。
- [queue_advisory_model_candidates.csv](queue_advisory_model_candidates.csv)：選択画像の参考45候補。
- [preparation_summary.json](preparation_summary.json)：入力・出力・script hash、変更なしのチェック。
- [summarize_training_review.py](summarize_training_review.py)：確認開始前のqueueから本フォルダのCSV・無加工例を再生成。ラベル付け後はpending snapshotの条件が変わるため再実行しない。

確認用画像集とモデルは大容量ローカルデータなのでGitには含めない。このフォルダには小さい集計・証跡・代表原画像を残す。
