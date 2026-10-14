# 追加16枚の注釈品質と黄色の扱い（2026-10-14）

## 決定と現状

ユーザーから「黄色の位置は分かるが、ホワイトボードの足などに隠れていてコーンと判別しづらく、枠を付けていない」と共有を受けた。
確認質問への回答は**赤・黄色の同一`traffic_cone`クラスを維持し、曖昧な画像の追加学習を保留する**。
この方針に沿って追加16枚を照合した。推測した黄色の枠を付ける、黄色を別クラスや背景に変更する、元画像を加工することはしていない。

現在の追加queueは画像16枚・保存枠23個。assistantが無加工の原画像と保存座標を照合したところ、赤領域の保存枠22個と、frame4651の小さい黄色領域の保存枠1個があった。
赤22枠には同じコーンの重複が含まれ、22個の物理コーンを意味しない。
この照合も独立した人による品質承認ではない。

| 確認項目 | 結果 |
|---|---|
| 同じ座標の重複枠 | frame421・4351・4651：各1組 |
| 同じ赤領域を囲む複数枠の要確認画像 | 上記3枚とframe4261、計4枚 |
| 黄色の保存枠を確認できた追加画像 | frame4651のみ |
| 追加を保留する画像 | 15枚 |
| 重複修正・再確認後に追加可能とする候補 | frame4651の1枚 |
| 実施した再学習 | なし |

15枚の保留は「15枚とも確実に黄色が見えるのに漏れている」という断定ではない。
可視性・対象の有無・注釈範囲を今回確定できないため、追加採用を保留する保守的な扱い。
完全に隠れているコーンの不可視部分を推測して囲む必要はない。少し見えていても対象として判別できない場合、negativeと決めつけない。
基本方針はこの追加queueに適用し、既存のbaselineラベルや検証側Bは変更していない。

## なぜ再学習をそのまま開始しなかったか

現行classは赤・黄色を含む1種類。認識対象として見える物体の枠がない場合、正例として学習されず背景側の分類学習に影響する可能性がある。
使用中のUltralytics実装でも、ラベルからtarget bboxとtarget scoreを作り、全候補に対して分類損失を計算している。
参照：`yolo-env/lib/python3.10/site-packages/ultralytics/utils/loss.py`の`v8DetectionLoss`、targets/assigner/BCE計算部。
「黄色だけ今回は気にしない」という設定にはしていない。黄色の弱さの原因を今回の未注釈だけに断定することもできない。

また、以前の`PASS_DATASET_INTEGRITY_NOT_MODEL_ACCURACY`は、画像hash・label形式・review hash・splitなどの整合性チェックだった。
同一枠の重複や「全ての見えるコーンを囲んだか」を保証できていなかった。
今回は同一座標の重複を明示的に拒否するよう検査を強化したので、既存`ab_bootstrap_augmented_v02`は今回の学習には使わない。
以前のmerge結果は履歴として維持し、上書きや削除は行っていない。

## 追加した機能

1. `cone_dataset.parse_label`は同一座標の重複枠を通常は拒否する。train/valの起動前検査にも反映される。
2. 診断や修正画面では明示的な`reject_duplicates=False`で既存枠を読めるが、学習用の通常検査では許可しない。
3. `annotate_cone_dataset.py --edit-existing --image ...`で指定の1枚だけを描き直せる。
4. 既存ラベルを変更する場合、`annotation_backups/`へ古いlabelとreviewsを保存してから、本人が`Y`を押した場合だけ置き換える。
5. 新しい選択中に同じ座標を複数回指定した場合は、画面確認前に1枠へまとめる。過去の保存ラベルを自動で削除する処理ではない。
6. 画面に枠番号と枠数を表示する。座標が少し違う重複は自動削除せず、重なり警告と人の確認に任せる。
7. mergeに`--selection-policy`を追加し、`include/hold`を全画像について明示する。policyは元PNG hashに対応付け、holdをnegativeへ変換せず追加から外す。

GUI上の枠は表示用コピーに描画するだけ。保存する元PNGは無加工のまま。
明示的な再確認前に、今回のユーザーlabel・reviewsは一切変更していない。

## 本人が次にする操作：1枚だけ

```bash
cd /home/robo25/theta_ws/RICHO-theta
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/a_hardcase_review_v02 \
  --split train \
  --edit-existing \
  --image images/train/block_a_e68ece502c09e03a_f004651.png
```

1. `P`で既存の番号付き枠を表示する。
2. `R`で枠を描き直す。大きな赤コーンと小さい黄色コーンをそれぞれ1枠ずつ、見える範囲で囲む。Enterは異なる対象の枠ごとに1回だけ押す。
3. Escで選択を終了する。画面の枠数・枠位置を確認し、正しければ`Y`で保存する。
4. 小さい黄色の判断がなお難しい場合は`S`または`Q`で保留する。無理に2枠を作ってはいけない。その場合、この1枚も採用を見送り、追加学習は開始しない。

保存が確認できたら、15枚を保留したまま新しいdatasetを作る。

```bash
./yolo-env/bin/python3 src/prepare_cone_training_review.py merge \
  --dataset datasets/cone/a_hardcase_review_v02 \
  --reference-dataset datasets/cone/ab_bootstrap_v01 \
  --selection-policy Experimental_results/2026-10-14/cone_annotation_quality_r01/selection_policy.csv \
  --output-dir datasets/cone/ab_bootstrap_augmented_v03

./yolo-env/bin/python3 src/cone_dataset.py check \
  --dataset datasets/cone/ab_bootstrap_augmented_v03
```

この1枚を採用できればtrain35→36枚、val38枚のまま。以前の51枚版ではなく、この36枚版を次の候補とする。
追加が1枚だけなので、十分なデータ拡充や精度改善を保証するものではない。まず注釈の一貫性を守る。
これらのPASSと追加枠を確認してから、新しい出力先で学習・旧モデルとの比較に進む。
独立testやYOLO→距離/TTC/FFBへの実機採用判定は別途必要。

## 証跡・検証

- [quality_summary.json](quality_summary.json)：修正前のhash付き品質snapshot。注釈・原画像・学習モデルは変更していない。
- [label_boxes.csv](label_boxes.csv)：保存23枠の原画像座標と目視領域属性。
- [overlapping_annotation_pairs.csv](overlapping_annotation_pairs.csv)：同一枠とIoU0.5以上の組。重なりだけで同じ物体と自動断定していない。
- [selection_policy.csv](selection_policy.csv)：追加1枚・保留15枚と理由。includeも修正完了を意味せず、通常のlabel/review検査を通す必要がある。
- [raw_example_manifest.csv](raw_example_manifest.csv)：frame4261・4651の原PNGへの対応。
- [frame4261の原画像](raw_examples/block_a_e68ece502c09e03a_f004261.png)、[frame4651の原画像](raw_examples/block_a_e68ece502c09e03a_f004651.png)：1280×720、全画角、PNGバイト同一コピー。
- `audit_annotations.py`：修正前snapshot生成用。修正後の監査では新しい結果フォルダへ保存し、過去CSVを上書きしない。

関連130テストPASS。原画像保持、重複拒否、明示的な置換、backup、保存前skip、policyの未指定/不足/古いhash拒否、holdの除外とval/test保持を検証した。
実データでも新policyのmergeを試し、未修正のframe4651の重複で意図どおり拒否した。`ab_bootstrap_augmented_v03`はまだ生成されていない。
構文確認と`git diff --check`も完了。GUIでの本人による再確認とモデル学習は未実施。
