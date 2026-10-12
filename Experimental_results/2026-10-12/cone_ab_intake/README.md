# 赤コーンA/B録画の受入れ・試作データ準備

## Cがなくても試作を始める

3つの全く異なる背景が、初回学習の必須条件というわけではない。ユーザーよりC用の場所を確保しにくいと共有されたため、Aをtrain、Bをvalとする**開発用データセット**を準備した。最終の独立testは未取得として残し、BやAの隣接frameをtestへ流用しない。

代表rawではAは廊下、Bは机・椅子・機器のある室内で、既に背景差がある。同一学校内でも試作に使える。ただし別コース・屋外・未知背景での性能を検証した意味ではない。今すぐ同じ内容をCとして録り足す要求はしない。後日、同じ場所でもモデル調整に未使用の別収録を評価用にできるが、その結果が示す範囲は同様環境に限る。

前段の3split必須という手順を、試作と最終評価に分離した。明示的な`--development-only`がある場合だけtrain／valの2splitを許可。通常の3splitモードの制約は維持している。

## 提出録画の整合性

原本は`/home/robo25/Downloads/`の4アーカイブ。既存safe extractorでパス／リンク／展開上限2 GiB/原本を検査し、リポジトリの`recordings/2026-10-12_cone_ingest_ab/`へ展開。原本は改変せず、録画ディレクトリはGit対象外。

| 提出原本の略称 | raw／CSV frame数 | CSV最終時刻 | 試作用split |
|---|---:|---:|---|
| cone_train_block_a_r01_20261012_153804_108 | 5,648 | 191.792秒 | train／block_a |
| cone_nasi_block_a_20261012_154213_645 | 460 | 15.687秒 | train／block_a |
| cone_train_block_b_r01_20261012_155114_513 | 5,236 | 175.261秒 | val／block_b |
| cone_nasi_block_b_r01_20261012_155435_017 | 572 | 19.125秒 | val／block_b |

計11,916 raw frameを全件逐次デコードし、CSV連番・時刻単調増加・1280×720の元解像度・動画CSV件数一致を確認。BEV／detectionはheader件数のみ確認し、全デコードしたとは扱わない。学習用画像の元となるrawは全デコード済み。全4本のmetadataはFFB publish=0、AI=0。FFB／ROS／GPUの処理を新たに起動したわけではない。

Aの「なし」原本の内部session名は`cone_nasi_20261012_154213_645`で、外側のarchive名にあるblock_aが省かれている。提出原本との対応を保持し、内部名を改変していない。Bの「あり」は名前にtrainがあるが、今回は撮影block B全体をvalへ割り当てる。filenameからsplitや正解を自動推論していない。

根拠：[input_inventory.json](input_inventory.json)に各原本・sessionのhash、frame件数、実際のpath、設定を保存。[inspect_inputs.py](inspect_inputs.py)で再現できる。安全展開先は新規の場所に限定し、既存展開を上書きしない。

## 生画像レビューとラベルの注意

結果を学習する前に、各録画の最初／中央／最後の計12点を確認した。[manual_review.csv](manual_review.csv)、[review_frame_manifest.csv](review_frame_manifest.csv)。このサンプル確認を全frameの正解として使わない。

- Aの赤コーンは後方レンズへ移動する場面もある。前方だけを見て「なし」としない。
- Bでは赤コーンの台座が隠れる近距離の場面もある。検出枠が取れても正しい床接地点が取得できるとは限らない。
- ユーザー確認により、Bの後方物体もAの後方・部屋入口付近の小さな黄色物体も**黄色コーン**と確定した。「なし」は赤コーンを除去したという意味で、全色のコーン不在ではない。初回のA代表3点レビューでは遠方の黄色を見落としていたため、この解釈を修正した。
- class 0 `traffic_cone`は赤・黄色を同じ対象として扱う。両レンズのすべての可視コーンを囲み、HSVで正解を自動生成しない。A/Bの「なし」録画をnegativeへ一括登録しない。

代表画像は[report_assets](../report_assets/README.md)へ無加工で保存。全画角・元解像度のまま、元デコードとの画素一致を確認する。

## 作成した開発用データセット

`datasets/cone/ab_dev_v01/`をローカル出力先とし、[recording_plan.csv](recording_plan.csv)の30 frame間隔で無加工PNGを抽出した。1秒程度の目安であり、厳密な実時刻の1秒ではない。すべて未レビューの`pending`から開始する。コーンなしのファイル名でもnegativeラベルを自動生成しない。

| 役割 | コーンありとされた原録画から | なしとされた原録画から | 合計 |
|---|---:|---:|---:|
| train：A | 189 | 16 | 205 |
| val：B | 175 | 20 | 195 |
| 合計 | 364 | 36 | 400 |

上表は**原録画別の抽出枚数**であり、確定したpositive／negativeの枚数ではない。作成直後は400枚すべて未確認、labelファイル0件だった。後続の視覚レビューで73枚をpositiveとしてラベル付けし、327枚はpendingのまま保持している。[dataset_frame_manifest.csv](dataset_frame_manifest.csv)へ画像・frame・pixel／PNG hashを保存した。今回、完全一致の重複frameの除外は0件。源録画の重複hashやgroup跨ぎはなかったが、似た構図をすべて検出したという意味ではない。

```bash
python3 src/cone_dataset.py prepare \
  --plan Experimental_results/2026-10-12/cone_ab_intake/recording_plan.csv \
  --output-dir datasets/cone/ab_dev_v01 \
  --development-only
```

出力先が既存の場合は再実行せず、別のversion名を使う。data.yamlにはtrainとvalだけを記載し、test項目やtestディレクトリを偽造しない。ラベル確認後は通常のtrain／valコマンドが使えるが、`start_cone_yolo.sh test`は「独立testなし」として拒否する。

## ラベル付き初回試作用データ（追記）

400枚全件のラベル作業を待たず初回学習を試せるよう、`datasets/cone/ab_bootstrap_v01/`を別途作成した。原本4本は共通で、長い録画をframe 1から300 frame間隔、短い2本は元400枚と同じ30 frame間隔で選んだ。モデル結果を見た成功例選びではない。元400枚を削除・縮小したり、pendingを無視して学習許可したわけではない。

| dataset／split | 画像 | ラベル枠 | negative | pending |
|---|---:|---:|---:|---:|
| bootstrap train：A | 35 | 53 | 0 | 0 |
| bootstrap val：B | 38 | 56 | 0 | 0 |
| bootstrap 合計 | 73 | 109 | 0 | 0 |
| 元400枚版 | 400 | 確認済み109 | 0 | 327 |

枠数は物理的なコーン個体数ではない。同一コーンが両レンズ端へ分かれて映るA frame3301は、各可視部分に枠を付ける。台座が車体に隠れた近距離画像は、隠れた床接地点を推測して枠を伸ばさない。完全遮蔽した背景コーンには推測枠を付けない。

**今回の枠はassistantが全画角の生画像を1枚ずつ表示して作成した視覚レビューであり、ユーザーが全枠を確認したとは扱わない。** HSVの自動ラベルでもYOLOの予測でもない。特に遠方黄色、レンズ端、台座遮蔽の例は、人による独立品質確認が残る。`check`のPASSは座標形式・画素hash・split・レビュー来歴の整合性だけで、正解品質や認識精度の証明ではない。

再現・根拠：

- [visual_annotations.csv](visual_annotations.csv)：73枚ごとの画素座標xyxy枠とレビュー注記。正規化座標へ変換してlabelsへ登録。
- [bootstrap_recording_plan.csv](bootstrap_recording_plan.csv)／[bootstrap_frame_manifest.csv](bootstrap_frame_manifest.csv)：事前の時間間隔と元frame対応。
- [annotation_progress.csv](annotation_progress.csv)：元400枚の録画別進捗。
- [annotation_verification.json](annotation_verification.json)：73枚整合性PASS、元400枚は未確認があるため学習拒否、全400元画像の無改変を検査した記録。
- [bootstrap_review_snapshot.csv](bootstrap_review_snapshot.csv)：ラベルhashの保存。CSV・コードはGitへ残せるが、大容量dataset本体はGit対象外。
- 受渡し用`recordings/2026-10-12_cone_ingest_ab/cone_ab_bootstrap_v01.tar.xz`（46,727,544 bytes、約47 MB）を作成。[bundle manifest](bootstrap_bundle_manifest.json)の150ファイル全件hashが、検証済みdatasetと一致することを確認した。

再現コマンド（同一CSVなら再実行可能。人の枠修正・レビュー注記は上書きしない）：

```bash
python3 Experimental_results/2026-10-12/cone_ab_intake/build_annotated_bootstrap.py
```

bootstrapは全73枚がpositiveで、コーンが全くないnegativeは0枚。後方の静止黄色を検出するだけでvalの数値が良くなる可能性があるため、集計mAPを「赤コーンの実用精度」と呼ばない。少数・同環境の試作であり、独立test、コーン皆無／紛らわしい赤い物体の誤検知評価は未完了。これらを初回学習の着手を止める理由にはしないが、FFB実機採用の根拠にも使わない。

## 次に行うこと

まず[GPU PC向け手順](gpu_bootstrap_procedure.md)でbootstrapの枠確認・初回学習を行う。実学習はまだ実施していない。追加録画はこの準備の必須条件ではない。

後続のGPU PCでの枠確認記録を受領し、[人の確認結果の受入れ](human_review_receipt.md)で73/73枚の確認記録・109枠・変更0件・整合性PASSを確認した。前述のassistantのみの確認段階は初期履歴として残す。GPU PC側の確認済みdatasetで初回学習へ進める。手元の初期datasetは上書きしていない。

さらにGPU PCの初回学習結果を受領し、[学習結果報告](../cone_ab_bootstrap_training/README.md)で50 epoch完了、CSV累積時間76.4385秒、best/last重みの保存を確認した。後続のvalコマンドは実保存先`yolov8n/weights/best.pt`を使う。初期準備段階の「学習未実施」という記述は当時の履歴であり、現在の到達点は後続報告へ分離して記録する。

元400枚の残りをラベル付けする場合は以下。レビュー済みの73枚は通常起動ではスキップする。

```bash
# 表示可能なPCで、確認済みPython環境を使用
python3 src/annotate_cone_dataset.py --dataset datasets/cone/ab_dev_v01
python3 src/cone_dataset.py check --dataset datasets/cone/ab_dev_v01
```

元400枚は327枚が未レビューなのでcheckが拒否するのは正常。全画像の確認が完了したら以下の大きい版を使える。GPU PCへ移す場合はdatasetディレクトリ全体をコピーし、`cone_dataset.py relocate --dataset datasets/cone/ab_dev_v01`でroot pathだけ更新する。

```bash
./start_cone_yolo.sh train \
  --dataset datasets/cone/ab_dev_v01 \
  --output-dir runs/cone/train_ab_v01 \
  --epochs 50 --batch 8 --imgsz 960 --device 0

./start_cone_yolo.sh val \
  --dataset datasets/cone/ab_dev_v01 \
  --weights runs/cone/train_ab_v01/model/weights/best.pt \
  --output-dir runs/cone/val_ab_v01 --device 0
```

上記は元400枚版のラベル完了後の実行手順。初回用73枚版は別手順のdataset名を使う。valで開発を進めた結果は最終の独立評価とは呼ばない。YOLOの学習と、距離・TTC・FFB・白線逸脱への接続は別段階。

## 変更・検証範囲

`src/cone_dataset.py`へ明示的開発用モードを追加し、`src/run_cone_yolo.py`のtest実行では独立testを必須にした。従来の3split・未確認label拒否・漏洩拒否を維持。開発用の2split、test拒否、役割不一致拒否、旧3split互換を追加検証した。本番カメラアプリ・TTC・FFB・白線実装は変更していない。既存の未追跡`ground_contact_model.json`はユーザーのファイルとして触れず保持した。

新規追加分を含むデータテスト32件＋runner9件、計41件PASS。実データの開発用datasetでtestコマンドを実行し、GPU／model読み込み前に「独立testなし」でexit 2となり、出力ディレクトリも生成しないことを確認した。これは期待した拒否テストで、学習・精度評価の失敗ではない。前段の[準備verification](../cone_yolo_preparation/verification.json)は役割変更前のコードhashと69件検証の履歴であり、更新後の証拠は本報告の検証へ分ける。

ラベル付け段階では`annotate_cone_dataset.py --import-csv`と`--review-existing`を追加した。前者は全batchの画像hash・枠範囲・positive/negative・既存label/reviewとの一致を確認してから登録する。同一入力は再実行でき、異なる既存枠や人の修正は上書きしない。後者は通常ならスキップする確認済み画像もGUIへ表示し、人の品質確認に使う。

追加10件を含むdataset42件＋runner9件、**計51件PASS**。画像無改変、有限座標、未確認のnegative推論拒否、batch後半の不正入力による書き込み拒否、パストラバーサル／link／既存枠上書き拒否、同一入力の再実行を検証した。bootstrap再構築スクリプトの同一入力再実行、構文検査、diff空白検査もPASS。根拠は[annotation_test_verification.json](annotation_test_verification.json)。既存[verification.json](verification.json)は全400枚pendingだった受入れ直後の履歴として残し、後続結果はannotation系の別ファイルに分離した。

学習コマンドは`--dry-run`で引数組み立てのみ確認した。CUDA・YOLO実学習・GUIの手動操作・実機出力はこのPCで未実施。初回学習へ渡す段階であり、モデル精度、赤コーンから距離・TTC・FFBへ接続、白線逸脱を完了したわけではない。
