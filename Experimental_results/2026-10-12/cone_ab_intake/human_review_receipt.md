# GPU PCの枠確認結果の受入れ（2026-10-12）

判定：**学習前の枠確認記録・データ整合性はPASS。モデル学習・検出精度の評価は未実施。**

提出原本：`/home/robo25/Downloads/cone_ab_bootstrap_v01_reviewed.tar.xz`。写真は再送せず、reviews.csv・labels・manifest.csv・dataset.json・data.yamlの計77ファイルを受領した。

| split | 画像 | 人の確認記録 | positive | negative | 枠 |
|---|---:|---:|---:|---:|---:|
| train A | 35 | 35 | 35 | 0 | 53 |
| val B | 38 | 38 | 38 | 0 | 56 |
| 合計 | 73 | 73 | 73 | 0 | 109 |

- 73行すべてのnoteがGUIの`human full-frame review: all visible cone boxes annotated`へ更新されている。ユーザーの写真確認報告と一致する。
- 初期ラベルからの変更は0件。109枠をそのまま採用した記録である。
- manifestとdataset.jsonは手元の初回用datasetとbyte単位で一致。GPU PC向けdata.yamlはroot pathだけ異なり、train/val・単一クラスtraffic_coneの定義は一致する。
- class、座標範囲、positive/negative、確認時のlabel hash、split・元動画・画素hashの漏洩検査、未登録ファイルの有無を既存`cone_dataset.validate`で検査してPASS。
- 提出アーカイブのパス、link、重複、サイズ、ファイル集合を検査し、任意のファイルを既存datasetへ展開しない。作業用の一時コピーだけに提出ラベル・reviewsを適用して検査し、元73枚／元400枚のdatasetは上書きしていない。

画像検査の範囲：共有manifestと一致する手元の無加工・全画角PNG73枚を検査した。GPU PCの画像本体は今回の提出に含まれないため、遠隔側の画像を直接再検査したとは扱わない。レビュー記録の受入れは、検出精度や完全な枠品質を数値で保証するものでもない。

記録：[human_review_verification.json](human_review_verification.json)、[human_review_snapshot.csv](human_review_snapshot.csv)。初回のassistantレビュー段階の`annotation_verification.json`と`bootstrap_review_snapshot.csv`は、その時点の履歴として維持する。

再現：

```bash
python3 Experimental_results/2026-10-12/cone_ab_intake/verify_reviewed_export.py \
  --input /home/robo25/Downloads/cone_ab_bootstrap_v01_reviewed.tar.xz
```

## 次に進める作業

GPU PC（hsr-Alienware-m16-R2）の`~/yopi_ws/RICHO-theta`で、73枚版の初回学習に進める。GPU確認は別途ユーザーの環境確認アーカイブでPASSを確認済み。この解析PCでCUDA学習を実行したわけではない。ドライバー・PyTorchの再インストールは不要で、引数なしのsetup再実行は版を更新するため避ける。

```bash
cd ~/yopi_ws/RICHO-theta

./start_cone_yolo.sh train \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --output-dir runs/cone/train_ab_bootstrap_v01_r01 \
  --epochs 50 --batch 8 --imgsz 960 --device 0
```

GPU PC側の確認済みdatasetを使う。初期データアーカイブを再展開すると人の確認記録を戻してしまうため、上書きしない。既存run出力は削除・上書きせず、未使用run名を使う。

コーンが全くないnegative画像0枚と独立test未取得は引き続き制約。開発用の初回学習は可能だが、valの集計値だけで赤コーンの誤検知率・実用精度・FFB採用可否を決めない。Ultralyticsの設定保存先が/tmpへ退避した警告は別の保存先課題として残っており、今回のラベル検査とは無関係。
