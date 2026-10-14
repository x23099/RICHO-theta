# Eのhuman GT確定・友人モデルのオフライン確認（2026-10-14）

## 結論

**E24枚のhuman label確認と、友人のコーンモデルの実映像推論・比較まで完了。自動採用はしない。**
友人の`cone.pt`はYOLO11nの1クラス`cone`で動作したが、こちらのB/Eでは入力サイズによって見逃し・誤検出が残った。
「大量画像から学習した」という説明だけでは、THETAのdual-fisheye全画角へ適用できるとは判断しない。

`shiho_lane_mask_v2_best.pth`はstate_dict checkpointで、モデル定義・入力前処理・出力channel意味が未提供。
重みの読込・型/形状/metadata検査はできたが、**白線の実映像推論は未実施**。壊れていると判断したわけではない。
不足情報を友人から取得すれば確認を続けられる。ROS・FFB・運用設定には接続していない。

## Eの人による確認

| 項目 | 結果 |
|---|---:|
| 確認済み画像 | 24 |
| negative | 8（E01） |
| positive | 16（E02/E03各8） |
| 正解枠 | 32 |
| pending | 0 |
| レビュー時のlabel hashと現在label | 全一致 |
| 元PNG/デコード画素/1280×720 | 全一致 |

`reviews.csv` SHA256：`f48935bade458c6e57a0b9bd660a2fc496f3c410c56eb29d3ada258b1b18c42f`。
範囲外枠・同一枠の重複・positive/negative不一致はなかった。
[human_e_review_snapshot.csv](human_e_review_snapshot.csv)、[human_e_ground_truth.csv](human_e_ground_truth.csv)、`human_labels/`へ小容量snapshotを保存。
Eは評価専用で、どの52枚datasetへも追加していない。今回の値はhuman bboxとの正式な固定閾値照合。
以前のassistant参考領域の集計は過去snapshotとして保持した。
色属性だけは前の原画像目視とhuman bboxのIoU対応を用いたもの。YOLOが赤/黄を別クラス分類したわけではない。

## 受領ファイル・読込方法

| ファイル | 判明した形式・条件 |
|---|---|
| `cone.pt` | Ultralytics DetectionModel、YOLO11n、class0=`cone`、checkpoint内version8.4.123、学習imgsz640、device=mps |
| `shiho_lane_mask_v2_best.pth` | dictキーstate_dict/epoch/best_iou。state tensor542。epoch50、記録best_iou0.6839998858。最終Conv weight shape=(2,8,3,3) |

checkpoint内のIoU・training metricsは友人の学習環境の保存値で、今回の学校映像で測った値ではない。
学習画像数、赤・黄の学習範囲、撮影背景、元dataのsplit/重複はmetadataから検証できていない。

- `cone.pt` SHA256：`39c94a4b37d8997ed8faf67a7602c4e6e7aaeba5770faf0d16f68a6b4dc06b2d`。
- 白線weights SHA256：`5b27059d531604246ffc2c38e410be229801157f14c97b3a8417e85200f705eb`。
- 受領原本：`/home/robo25/Downloads/`。
- バイト同一のローカル保持：`runs/cone/received_friend_models_20261014_r01/`（Git対象外）。
- [checkpoint_inspection.json](checkpoint_inspection.json)、[lane_tensor_shapes.csv](lane_tensor_shapes.csv)。

最初にZIP/Pickle metadataを非実行で調べ、未知のglobalをチェックした。
白線は`weights_only=True`のCPU読込で通った。コーンは制限読込の初回でDetectionModelが未許可と拒否され、
既設torch/Ultralyticsの列挙したNN classのみを許可して読み込んだ（`weights_only=False`へのfallbackはしない）。
そのserialized moduleを直接実行せず、テンソルと検査済みYOLO11n cfgから既設DetectionModelを新規構築し、state_dictをstrict=Trueで全一致ロードした。
元`cone`class0を評価用の`traffic_cone`class0へ明示対応。元checkpointは書き換えていない。
未知classを自由にimportする汎用loaderや、受領Pythonの実行はしていない。
これは使用した読込制限の記録で、任意の外部weights全般の安全性を保証するものではない。

## 比較条件

B38枚・human56枠、E24枚・human32枠、D16negativeの**同じ原PNG**を使用。
初回の統一比較はimgsz960、FP32、batch1、rect=false、floor0.01、NMS IoU0.7、max_det300、bbox照合IoU0.5・1対1。
友人modelは追加で学習サイズ640も確認し、統一960比較とは別欄へ記録した。
前処理内部のletterbox/resizeは推論のみ。保存原画像の加工・枠描画・crop・保存動画作成は行っていない。
既存35/36/52modelの推論CSVは原画素が同一であることを確認し、human label照合をやり直した。

### confidence0.25、同じimgsz960

| model | B TP/FP/FN（56正解） | E TP/FP/FN（32正解） | D false枠（正解0） |
|---|---|---|---:|
| 基準35枚 | 56 / 39 / 0 | 31 / 0 / 1 | 8 |
| 追加36枚 | 56 / 88 / 0 | 32 / 0 / 0 | 3 |
| 負例追加52枚 | 53 / 12 / 3 | 30 / 2 / 2 | 0 |
| 友人YOLO11n | 50 / 45 / 6 | 20 / 20 / 12 | 16 |

Eの35枚modelはRecall96.875%、36枚100%、52枚93.75%、友人960は62.50%。
ただし36枚modelはBで余分な枠88と多く、Eだけで採用しない。
52枚版のEの追加FP2は0.50で0となるが、Bの0.50ではFN43。閾値を上げるだけで全場面が良くなるわけではない。
52枚版のDは学習に使った画像の再確認。Dで0枠になっても未見の非コーン物体への精度証明ではない。

### 友人modelの640補足

| imgsz / confidence | B TP/FP/FN | E TP/FP/FN | D false枠 |
|---|---|---|---:|
| 960 / 0.25 | 50 / 45 / 6 | 20 / 20 / 12 | 16 |
| 640 / 0.25 | 49 / 2 / 7 | 8 / 0 / 24 | 0 |
| 960 / 0.50 | 15 / 38 / 41 | 19 / 4 / 13 | 13 |
| 640 / 0.50 | 44 / 1 / 12 | 6 / 0 / 26 | 0 |

640のBでPrecision96.08%・Recall87.50%（0.25）と良い側面があるが、EではRecall25%に低下する。
960ではEの対象をより多く拾う反面、B/D/Eで余分な枠も増えた。
友人modelの640・Eでは赤3/16、黄5/16（0.25）。赤黄双方の見逃しがあり、単に黄色class非対応と断定しない。
この2サイズを調べただけで最適サイズや原因が確定したわけではない。threshold/runtimeを採用値へ変更していない。

全表のCSV：[fixed_threshold_comparison.csv](fixed_threshold_comparison.csv)、[color_recall.csv](color_recall.csv)、[matches.csv](matches.csv)。
[evaluation_summary.json](evaluation_summary.json)に入力/model/hashと制約を記録。
友人の各78枚の予測・時間は`cone_inference_{960,640}/`。GPUはRTX3070、依存やdriverは変更していない。

## 白線modelで不足しているもの

必要なのは、友人が実際に使っている次の一式：

1. 推論用Pythonとmodel class/forward定義（または元repositoryと該当commit、architecture/config）。
2. 入力サイズ、resize/letterbox、RGB/BGR、画素の正規化。
3. 背景・白線のchannel対応、argmax/sigmoid等の後処理。
4. 可能なら依存versionと、友人の環境での入力1枚・期待mask。

state_dictは重みであり、構造とforwardを定義するmodel classを用意してロードする必要がある。
[PyTorch公式のモデル保存・読込説明](https://docs.pytorch.org/tutorials/beginner/basics/saveloadrun_tutorial.html)を根拠に、形状だけから構造・白線channelを推測して実装しない。
2channelの最終層はsegmentationを示唆するが、task・architecture・channel意味を証明するものではない。
そのため`YOLO(shiho_lane_mask_v2_best.pth)`等で無理に起動していない。
白線maskが得られても、コースの右内側線/左境界の選択と逸脱判定は別設計で、まだ合意・実装していない。

## 終業時の判断・次回

- 全4modelはオフライン候補。今回の結果だけで実機FFBへ置換しない。
- 友人coneは破損ではなく、この入力・閾値では直接採用できる精度を確認できなかった。追加学習の起点やレンズ別入力の比較候補として保持する。
- 次回、白線のmodel定義・推論手順を入手し、同じ原映像で確認する。白線のboundary選択はその後ユーザーと確認する。
- コーンでは正例を保持しながら非コーンを抑える条件の比較を続ける。Eは引き続きtrainへ混ぜない。
- 新たな録画を今すぐ求める状態ではない。まず提供モデルの条件と既存データを整理する。

## 検証と資料

関連coneテスト145件PASS。新しいdated scriptは構文、重みのstrictロード、実78×2画像の原画素hash、human32枠のreview hash、生成CSV・図の来歴を確認。
汎用checkpoint loaderとしての網羅的security試験ではなく、今回の許可した形式・classに限定した確認。
最初のmetadata検査では一時Ultralytics設定folderへのfallback警告が出た。GPU推論時はrun内に設定folderを作成し、グローバル環境は変更していない。
既存MatplotlibのAxes3D警告はあるが、2D図は正常生成・目視確認した。

- [human GTでの比較グラフ](human_gt_model_comparison.png)：FPとFNを併記して改善/悪化を区別。
- 原画像は[受入れ時のD02/E02/E03](../cone_de_intake_r01/README.md)を再利用。加工していない。
- `check_models.py`：受入れ/制限読込とGPU推論。
- `evaluate_models.py`：human E review gate・元prediction再照合・表/図生成。

weights・録画・仮想環境はGitへ入れず、報告・CSV・label snapshot・原画像・生成scriptだけを共有する。
