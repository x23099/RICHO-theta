# 負例候補の準備と追加撮影への引き継ぎ（2026-10-14）

## 結論

既存の箱実験3本から、各4枚・計12枚の原画像を抽出し、両レンズを目視確認した。
assistantの確認では赤・黄色コーンが見当たらないため、**負例候補**として保存した。
ただし、人による明示確認はまだ0枚。ラベルは作らず、全12枚をpendingのままにしている。
再学習・モデル採用・YOLO→FFB接続・実機の操作は行っていない。

候補に対する同PC基準35枚モデル／追加36枚モデルのconfidence 0.25以上の予測は、いずれも0枠。
通常背景の補助にはなり得るが、棚・機材への高confidence誤検出を抑える中心データとしては簡単すぎる可能性がある。
追加録画が可能との申し出を受け、[4本の短い撮影手順](additional_capture_procedure.md)を用意した。

## 実際に調べた入力

全過去録画を検査したわけではない。既に展開済みの次の3本を、ファイル名だけでnegativeと決めずに調べた。

| session | 全CSV／デコードframe数 | 抽出frame（1始まり） | 目視結果 |
|---|---:|---|---|
| `cal_xm0.30_z0.80`（8/7） | 223 | 1,75,149,223 | 青箱・人物・壁・床。両レンズでコーンを特定せず |
| `hakonasi_20260825_131458_522`（8/25） | 853 | 1,285,569,853 | 箱なし、人物・壁・床。両レンズでコーンを特定せず |
| `approach_center_v0p10_r01_20260901_142324_230`（9/1） | 615 | 1,206,410,615 | 青箱・人物・カメラの移動。両レンズでコーンを特定せず |

保存queue：`datasets/cone/legacy_background_review_v01`（Git対象外）。
画像は1280×720、全画角、原動画からデコードした画素とPNGの画素hashが一致。
原動画・metadata・detections.csvも処理前後のhash一致。動画の全frame数とCSV連番・時刻・解像度を検査済み。
ただし**全動画を目視して「全時間コーンなし」と確認したわけではない**。
1本の時間等間隔4点を選び、モデルの予測によって画像を選んでいない。

[candidate_plan.csv](candidate_plan.csv)が入力計画、[candidate_manifest.csv](candidate_manifest.csv)がsession/frame/time/pixel/PNG/raw hash。
[assistant_visual_review.csv](assistant_visual_review.csv)はassistantの観察のみ。人のGT確認と区別する。
同じ部屋の時間近傍画像なので、12個の独立背景で成功したと解釈しない。

## モデル出力（未確認負例への候補数）

同じ12PNG、imgsz960、FP32、batch1、NMS IoU0.7、max_det300、prediction floor0.01。
モデルは[同PC再学習比較](../cone_ab_retraining_comparison_r01/README.md)の2つ。新たな学習はしていない。

| model | score≥0.01の総枠数 | 最大score | score≥0.25の総枠数 |
|---|---:|---:|---:|
| 基準35枚 | 10 | 0.07702 | 0 |
| 追加36枚 | 2 | 0.01459 | 0 |

検出0であることをnegativeラベルへ変換していない。人の確認前なので、ここではFP率・精度合格と呼ばない。
この容易な背景で追加版の候補が少なくても、既存Bの棚・小物への誤検出増加を覆す結果ではない。
追加36枚版の採用保留は維持。confidenceも本番設定へ反映していない。

数値根拠：[candidate_predictions_by_threshold.csv](candidate_predictions_by_threshold.csv)。
入力・model hash・条件：[candidate_summary.json](candidate_summary.json)。
各候補枠：[基準run](../cone_negative_baseline_diagnose_r01/predictions.csv)、[追加run](../cone_negative_augmented_diagnose_r01/predictions.csv)。
モデル来歴／依存version／処理時間は各runのprovenance.json・timing.csvに保存。
これらはオフライン推論で、カメラ・GUI・ROS・ハンコン込みのリアルタイムFPSではない。

## 新規ツールと確認手順

[prepare_cone_negative_candidates.py](../../../src/prepare_cone_negative_candidates.py)を追加した。
元画像・現在datasetを変更せず、新しいレビューqueueへ抽出する。
既存cone datasetのtrain/val/testと同じsource video・group・画素を拒否する。
既存Bの切り抜き・再エンコード等の似た画像まではhashで防げないため、収録内容の確認も必要。
queueは`data.yaml`がなくtrain-onlyの候補であり、そのまま学習できない。

通常背景の12枚を人が確認して活用する場合、この解析PCで実行：

```bash
cd /home/robo25/theta_ws/RICHO-theta
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/legacy_background_review_v01
```

- 本当に両レンズに赤・黄を含む三角コーンがない：**N→Y**。
- 小さい物・遮蔽物が曖昧、判断できない：**S**。pendingのまま保留する。
- コーンを発見した：Pで全可視コーンに注釈するか、Sで保留。その画像は今回の負例追加から除く。
- Qで中断できる。次回はpending画像から再開。画像へ枠や補正を保存しない。

人が明示確認した**空ラベルのnegativeだけ**を追加した新datasetを作るコマンド：

```bash
./yolo-env/bin/python3 src/prepare_cone_negative_candidates.py \
  --merge-reviewed-queue datasets/cone/legacy_background_review_v01 \
  --reference-dataset datasets/cone/ab_bootstrap_augmented_v03 \
  --output-dir datasets/cone/ab_background_augmented_v01

./yolo-env/bin/python3 src/cone_dataset.py check \
  --dataset datasets/cone/ab_background_augmented_v01
```

実queueへのmerge拒否チェックでは、人の確認が0枚のため`no human-confirmed negatives`で停止し、出力datasetが作られないことを確認した。
実データの成功mergeはまだ行っていない。
1枚でも確認済みnegativeがあればそれだけ追加し、positive/pendingは除外・記録する。
全てpendingなら拒否。human review note・現在label hash・空ラベル・原画像・元動画のhashを検査する。
既存referenceは維持し、val/testを含む全reference画像・labelをバイト同一でコピーする。
新しい撮影groupをtrainへ追加できるが、既存Bをtrainへ移すことはできない。
これはdatasetの作成だけで、自動的に再学習・モデル採用はしない。

以前のAの16枚用`prepare_cone_training_review.py merge`はA内の追加専用。
今回の別日groupを無理にblock_aと偽って使わず、上記の専用コマンドを使う。

## 追加録画を優先する場合

12枚は補助候補として既に保存できた。追加録画の時間があれば、まず[撮影手順](additional_capture_procedure.md)のD01/D02とE01/E02を撮る。
録画合計約2分。学習Dはコーン皆無の家具・小物・紛らわしい赤黄色物体、評価Eは別収録の負例と確実に見える赤・黄色コーン。
同じ部屋でも構図・配置を分け、未知背景評価とは呼ばない。既存Bを学習に流用しない。
受け取り後に背景の難しさとコーン可視性を確認し、負例数と正例のバランスを決めて再学習する。
この段階で本番へのYOLO接続や距離/TTC評価へ進むわけではない。

## 代表原画像・再現

- [8/25箱なしframe1](raw_examples/legacy_box_20260825_377e1afc8358eacb_f000001.png)
- [9/1箱ありframe410](raw_examples/legacy_box_20260901_5686fb7d85b44135_f000410.png)

元PNGのバイト同一コピー。[raw_example_manifest.csv](raw_example_manifest.csv)で追跡できる。
既存の本日代表4点に加える補助資料で、合成・描画・切り抜き・補正はしていない。

抽出再現（未使用output名を指定）：

```bash
./yolo-env/bin/python3 src/prepare_cone_negative_candidates.py \
  --plan Experimental_results/2026-10-14/cone_negative_preparation_r01/candidate_plan.csv \
  --reference-dataset datasets/cone/ab_bootstrap_augmented_v03 \
  --output-dir datasets/cone/legacy_background_review_v02
```

`analyze_candidates.py`はこの初回pending状態でのhash付きsnapshot作成script。
人のreview後やsnapshot作成済みの場所への再実行は拒否する。後日の集計は別versionにする。
新ツールの合成テスト12件（原画素保持、pendingを負例にしない、hash漏洩拒否、CSV/video不一致、
確認済みnegative限定merge、val/元reference保護、assistant観察の人確認扱い禁止）PASS。
関連coneテスト全145件PASS、構文確認・`git diff --check`完了。
撮影コマンドの`--dry-run`で専用設定・保存先・label・停止mock topic・clean-git検査の構成を確認した（カメラ・ROSは起動していない）。
実機録画はまだ行っていない。Git commit/pushは今回依頼されていないため実行していない。
