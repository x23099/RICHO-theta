# 2026年10月12日 日報

## 本日の到達点

赤色三角コーンを主対象とするYOLO開発へ着手し、録画A/Bの受入れ、無加工PNG抽出、正解枠の準備、人による確認、GPU PCの環境調整、初回50 epoch学習、学習済みbest.ptによる明示的valまで完了した。
黄色コーンも単一クラス`traffic_cone`の対象へ含めた。開発用Bの今回のPrecisionは93.8%、Recallは64.3%、mAP50は94.1%。初回モデルは得られたが、見逃し診断・独立test・距離/TTC/FFBへの接続は未完了である。

既存の青箱HSV・距離・TTC・FFBの実行系をYOLOへ置き換えた日ではない。本日はコーンデータとオフライン学習・検証が中心で、コーン検知による実機振動の成功を追加したとは扱わない。白線逸脱も未実装で、左右境界の選び方は実装前に相談する。

## 1. 方針・使用環境

| 項目 | 内容 |
|---|---|
| 優先対象 | 赤色三角コーン。黄色も同じtraffic_coneクラスで学習。人・青箱の追加クラスは初回の必須条件にしない |
| 入力 | 元dual-fisheye全画角、1280×720の無加工PNG。前後両レンズの可視コーンをラベル付け |
| GPU PC | ハンコン接続PCと同じ`hsr-Alienware-m16-R2`、リポジトリ`~/yopi_ws/RICHO-theta` |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU、約8 GiB |
| 最終環境 | NVIDIA driver 535.309.01を維持、torch 2.7.1+cu118、torchvision 0.22.1+cu118、Ultralytics 8.4.175 |
| 解析PC | `robo25`、`/home/robo25/theta_ws/RICHO-theta`。torch/ultralyticsを用いたモデル推論は実行していない |
| 学習環境 | リポジトリ専用`yolo-env`。既存ROS環境とは分離 |
| 初回モデル | 既存YOLOv8n重みを初期値とする単一クラスの開発用試作 |
| 保存 | 小容量の集計・来歴・コード・代表資料は`Experimental_results/2026-10-12/`。録画・dataset・checkpoint・venvはGit対象外 |

コース画像の外周二重白線の内側を右境界候補とする意図を確認した。左側は二重線でない箇所もあり、認識対象の定義は未決定。距離校正の床十字確認は別の未完了課題として残し、YOLO着手の条件にはしない。

## 2. 学習・データ作成パイプライン

- `setup_cone_yolo.sh`：専用venvへ環境導入。
- `start_cone_yolo.sh`：env/train/val/testの共通起動。
- `src/cone_dataset.py`：録画からのPNG抽出、録画group別split、label/review/hash検査、PC間のpath更新。
- `src/annotate_cone_dataset.py`：GUI枠付け、人の再確認、枠CSVの厳密な取込み。画面表示にのみ枠を描き、保存PNGは無加工。
- `src/run_cone_yolo.py`：GPU使用を要求し、CPUへ自動fallbackしない。実行条件・入力/label hash・環境版・metricsを保存。
- 開発用2splitを明示したdatasetはtrain/valだけで着手可能にした。一方、独立testがない状態のtest実行はGPU/model読み込み前に拒否する。
- 未確認画像を空labelの背景へ自動変換しない。形式が正しくても人の確認後にlabelが変わっていれば再確認を要求する。録画groupや画素hashのsplit漏洩、範囲外枠、link、上書きも検査する。

根拠：[準備資料](../Experimental_results/2026-10-12/cone_yolo_preparation/README.md)、[A/B受入れ・ラベル作成](../Experimental_results/2026-10-12/cone_ab_intake/README.md)。各段階の「学習未実施」はその時点の履歴で、終業時点の到達点は本日報と学習・val報告を優先する。

## 3. 録画受入れと人のラベル確認

受領録画：`cone_train_block_a_r01_20261012_153804_108.tar.xz`、`cone_nasi_block_a_20261012_154213_645.tar.xz`、`cone_train_block_b_r01_20261012_155114_513.tar.xz`、`cone_nasi_block_b_r01_20261012_155435_017.tar.xz`。原本は`/home/robo25/Downloads/`にある。

| 項目 | 結果 |
|---|---:|
| 録画本数 | 4 |
| raw全逐次デコードframe | 11,916 |
| 元400枚版 | train A 205枚／val B 195枚 |
| 初回bootstrap | 73枚、109枠 |
| bootstrap train A | 35枚、53枠 |
| bootstrap val B | 38枚、56枠 |
| 人のGUI確認記録 | 73/73枚 |
| 初期枠からの変更 | 0件 |
| 元400枚版の未確認 | 327枚 |
| コーン皆無のnegative | 0枚 |
| 独立test | 未取得 |

Cパターンの別背景を用意しづらいため、今回はA/Bの開発用試作へ限定した。「なし」録画にも後方に黄色コーンがあり、ユーザーに対象物を確認した。赤がないだけでnegativeとして扱うとラベル漏れになるため、黄色もtraffic_coneとして正解枠へ含めた。

73枚の人の確認済みexportを受領し、manifest・dataset定義・全label・レビュー時hash・座標・件数を検査して整合性PASS。GPU側data.yamlのroot path差はPC移動によるものとして確認した。GPU PCの画像本体は確認exportに含まれず、共有manifestに一致する解析PC側の無加工PNGを検査した。元datasetを勝手に上書きしていない。

根拠：[入力inventory](../Experimental_results/2026-10-12/cone_ab_intake/input_inventory.json)、[人の確認受入れ](../Experimental_results/2026-10-12/cone_ab_intake/human_review_receipt.md)。

## 4. GPU環境で発生した問題と対応

1. venv作成時にensurepipがなく失敗し、依存導入も未完了のためcv2 importも失敗した。GPU PC側でvenv構築・依存導入を進めた。
2. torch 2.14.1+cu130と既存driverの不整合でCUDA使用不可となった。共用PCのdriverを変更しない方針で、専用venv内のPyTorchを2.7.1+cu118へ変更した。
3. 変更後もCUDA unknown errorが残り、LD_LIBRARY_PATHを外しても解消しなかった。ユーザーがGPU PCを再起動した。
4. 再起動後に`PASS_GPU_MODEL_LOAD_AND_SYNTHETIC_FORWARD`を確認した。その後の学習・valでも同GPU・同torch環境の記録を受領した。

CUDA unknown errorの根本原因は確定しておらず、「再起動後に利用可能となった」という観測と区別する。driver更新は行っていない。GPU確認PASSは実コーン検出精度のPASSではない。

Ultralytics設定保存先が/tmpへ退避する警告は未解決の別課題。今回の学習やmetrics保存は完了しているが、恒久的な保存先は次回整理できる。引数なしのsetup再実行は依存版を再更新し得るため、今の動作する環境へ不用意に実行しない。

## 5. 初回学習と明示的val

| 条件 | 内容 |
|---|---|
| 学習 | epochs=50、batch=8、imgsz=960、device=0、workers=0、seed=0 |
| dataset | ab_bootstrap_v01。train A、val Bを録画groupで分離 |
| 明示的val | 同じbest.pt、同じmanifest/reviews/data.yaml/全label hash、split=val |
| 実保存checkpoint | GPU PCの`runs/cone/train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt` |
| 保存名の留意 | 要求name=modelと実保存name=yolov8nが異なった。後続コマンドは確認済みの実在pathを使用 |
| 学習CSVの累積時間 | epoch50で76.4385秒（約1分16秒）。起動・最終処理を含むコマンド全体時間ではない |

| 指標 | 学習終了後の報告値 | 今回の明示的val |
|---|---:|---:|
| Precision | 93.818% | 93.775% |
| Recall | 64.286% | 64.286% |
| mAP@0.50 | 94.136% | 94.134% |
| mAP@0.50:0.95 | 77.870% | 77.233% |

best.ptのSHA256とdataset/labelの来歴は一致。mAP50–95は約0.636 percentage points低く、指標が完全一致したとは扱わない。この小差の原因は集計ファイルのみでは特定できていない。

Precisionは検出枠の正しさ、Recallは正解対象を拾えた割合の指標。mAPは別の集計であり、「94%のコーンを必ず拾う」と解釈しない。赤・黄混合の単一クラス集計なので、赤だけの見逃し率はまだ不明。少数・開発用valで、独立testの精度ではない。

val archiveはprovenance・metrics・環境freezeの3ファイルで、bestディレクトリは空。画像別予測枠、confidence、正解との対応、推論時間は含まれず、どの画像を見逃したかは未診断。解析PCではcheckpointをデシリアライズしていない。

根拠：[学習報告](../Experimental_results/2026-10-12/cone_ab_bootstrap_training/README.md)、[val報告](../Experimental_results/2026-10-12/cone_ab_bootstrap_validation/README.md)、[val整合性検査](../Experimental_results/2026-10-12/cone_ab_bootstrap_validation/verification.json)。

## 6. 接続切れの確認

VS CodeのCodex拡張で`stream disconnected before completion`が頻発するとの報告を受けた。ローカルログでも同種のサーバー処理エラーと自動retryを確認した。学習/CUDAとは別の問題で、利用上限超過やネットワークだけが原因とは断定していない。

登録済み拡張版は26.1007.21434だが、ログのstackには26.930.61225のwebview pathが残っており、更新後のウィンドウ再読み込みを提案した。実際に再読み込みが行われたかは未確認。最後のテストでは返信が正常に表示され、ユーザーから「問題なさそう」と報告された。**今回の送受信は成功したが、恒久的な解消は未確認**。

OpenAI関連の対処確認にはopenai-docsスキルを使用し、公式の復帰案内を確認した。拡張停止・認証/ネットワーク設定変更・会話削除は実行していない。[診断メモ・新規会話への引継ぎ文](../Experimental_results/2026-10-12/cone_ab_bootstrap_validation/vscode_stream_error_notes.md)を保存した。

## 7. 検証と代表資料

- dataset42件＋runner9件、計51件PASSの当日検証記録を保存済み。未確認label拒否、画像無改変、split漏洩、不正枠・path・link・上書き拒否等を含む。変更していない学習パイプラインの成功済み検証を終業時点で再利用した。
- val受領スクリプトの実行で全7項目PASS。原本hash・チェック結果・比較CSVを保存済み。
- val受領スクリプトの構文検査・Git差分の空白検査PASS。
- GPU合成forward・50 epoch学習・valはGPU PCからの提出結果で確認。解析PCで再実行したとは扱わない。
- 未実施：画像別/confidence別診断、未知環境test、コーン皆無場面の誤検知評価、実カメラ推論FPS、コーン距離/TTC/FFB連携、白線逸脱。

代表資料は[report_assets索引](../Experimental_results/2026-10-12/report_assets/README.md)の4点。raw3枚は1280×720・全画角・無加工で、元frame/hashを記録。学習曲線は実CSV・生成スクリプト・hashで追跡できる。

1. Aの正面赤コーン：`cone_ab_a_raw_frame_000001.png`。
2. Bの別位置赤コーン：`cone_ab_b_raw_frame_002618.png`。
3. 「赤なし」でも後方に黄色コーンがある例：`cone_ab_b_nasi_raw_frame_000286.png`。
4. 50 epochの実測学習曲線：`cone_ab_bootstrap_training_curve.png`。

## 8. 次回作業

1. **追加録画・再学習は先に行わず、既存best.pt・既存B画像で画像別予測を保存する診断処理を用意する。** 現在のvalコマンドだけではその出力は得られない。未実装のコマンドを実行済みとは扱わない。
2. confidence別に正解枠との対応・見逃し・余分な検出を確認し、赤/黄、前後レンズ、対象サイズ、遮蔽を切り分ける。カメラ画像は無加工のまま保存し、診断結果は別CSV/グラフにする。
3. 今のGPU環境とbest.ptを保持し、出力runは新しい名前を使う。必要ならUltralytics設定保存先警告を局所的に整理する。
4. 診断後に追加データの必要条件を決める。コーン皆無のnegativeと未使用環境testは未取得だが、現時点で同条件を大量に撮り直さない。
5. 検出結果を床面位置・距離/TTC・既存安全ゲート・FFBへつなぐ設計は、検出と接地点の評価を分けて進める。YOLOのbbox下端を正確な接地点と無条件に見なさない。
6. 白線逸脱は境界定義の合意後に着手する。床十字による幾何評価も別課題として残る。

本日はここで終了。新しい学習・実機試験は起動しない。再開時は本日報とval報告から進める。

## 9. Git整理

前段は`a77483c`（YOLO準備）、`c39bc89`（YOLO学習）、`d3c7d99`（YOLO学習２）へ反映済み。本依頼ではval報告・受領検査・接続切れメモ・本日報・索引・代表資料の現状説明を追加し、既存origin/mainへコミット/PUSHする。
録画tar、動画、dataset画像一式、モデル重み、venv、キャッシュを追加しない。PUSHの成否・最終コミットIDは完了応答で報告する。
