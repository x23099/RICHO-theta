# 日報：2026-10-14

## 本日の到達点

コーン注釈の修正確認、同条件再学習比較、負例の準備、追加録画D/Eの受入れ、負例16枚による52枚版の再学習、Eのhuman GT評価、友人コーンmodelの実映像確認まで完了した。
誤検出を減らすと正例のscoreも下がる条件があり、**35/36/52枚版・友人modelのいずれも今回自動採用していない**。
白線weightsは形式・テンソル・metadataを確認したが、model定義/前処理/出力channelの情報が不足し、推論は未実施。
HSV青箱・距離/TTC・challenge relay・ROS/FFB・実機制御の変更/駆動はない。本日はここで終了とする。

## 1. 注釈品質確認と同PC再学習

前回のA難例16枚の追加では、黄色が隠れて判別しにくい画像があった。
赤黄共通のtraffic_coneを維持し、曖昧な15枚は追加保留。frame4651はユーザーが赤・黄各1枠、重複なしの2枠へ修正し、review hash一致を確認した。
元51枚版は品質保留として保持し、修正した1枚だけを追加した36枚版を作った。元35枚やBを上書きしていない。

旧RTX4070学習と環境差を混同しないため、このPCのRTX3070で35/36枚を同じ初期weights・seed0・FP32・50 epoch・batch8・imgsz960で学習した。
元checkpointはsrc/yolov8n.pt。torch2.14.1+cu130、Ultralytics8.4.175。
offline/FP32指定を追加し、自動AMP補助model取得を避けた。初回font準備位置の誤りで約755KBのfont取得が1回起きたため、後続では正しいrun内folderへlocal fontを用意した。
driver/venv依存は変更しない。

| B、confidence0.25 | TP | FP | FN |
|---|---:|---:|---:|
| 同PC35枚版 | 56 | 39 | 0 |
| 同PC36枚版 | 56 | 88 | 0 |

36枚版は非コーンと確認済みのB右端小物にも高scoreを出し、単純採用を保留。
根拠：[注釈品質確認](../Experimental_results/2026-10-14/cone_annotation_quality_r01/README.md)、[35/36比較](../Experimental_results/2026-10-14/cone_ab_retraining_comparison_r01/README.md)。

## 2. 既存録画の負例準備と追加録画

別日の箱録画3本から、時間均等で計12枚の無加工PNGを抽出した。
assistantにはコーンが見当たらなかったが、明示的な人確認は未実施なのでpendingのまま。YOLO予測0をnegativeに変換していない。
通常の壁/床中心で、両modelの0.25以上の予測が0枠だったため、棚・小物のhard negativeとしては不足の可能性があった。
原画素を保ち、確認済みnegativeだけを追加するprepare/mergeツールと合成テストを用意した。

追加撮影の申し出を受け、同じTHETA・取付高さ/角度・車体静止での短いD/E撮影手順を作成。
ユーザーからD01/D02/E01/E02/E03の5本を受領した。
E02は固定配置、E03は位置変更の追加で、両方を評価専用として保持。

| 録画 | frame数 | 記録末尾時刻 | 用途 |
|---|---:|---:|---|
| D01 | 1,104 | 36.854秒 | 棚/家具の負例、学習候補 |
| D02 | 912 | 33.240秒 | 赤い水筒を含む負例、学習候補 |
| E01 | 1,320 | 44.193秒 | 別構図のコーンなし、評価用 |
| E02 | 1,156 | 41.775秒 | 赤・黄の固定配置、評価用 |
| E03 | 1,097 | 38.500秒 | 赤・黄の配置変更、評価用 |
| 合計 | 5,589 | — | 各8枚、計40PNGを抽出 |

全raw逐次デコードとCSV連番/時刻/geometry/枚数、元file hash、無加工PNGの画素hashを検査しPASS。
全frameの目視・推論は行わず、各8枚の時間均等sampleを確認した。解像度1280×720・dual-fisheye全画角を維持。
recorded AI/FFB publish/relayは全て0。
ユーザーがD02の赤い物を水筒・非コーンと確認。基準35枚modelはその8sample全てで水筒をコーンと誤検出していた。

原録画はDownloadsのtar.xzと、`recordings/2026-10-14_cone_ingest_de/`に保持しGit対象外。
根拠：[既存負例候補](../Experimental_results/2026-10-14/cone_negative_preparation_r01/README.md)、[5録画受入れ](../Experimental_results/2026-10-14/cone_de_intake_r01/README.md)。

## 3. D16枚のhuman negative確認・52枚版

GUIで15枚のnegative保存、先頭1枚はpendingだった。
ユーザーの「全てコーンを確認できませんでした」の明示確認を根拠に、先頭1枚もnegative記録を完了（chat確認とnote記載）。
人確認済みD16枚だけを36枚版へ追加した。train52枚＝positive36/negative16、55枠。B38枚/56枠はバイト同一、Eはtrainに混ぜない。
同じ初期weights・GPU・seed・50 epoch・FP32条件で52枚を学習しbestを保存した。

| 学習終了時best検証 | 35枚 | 36枚 | 52枚 |
|---|---:|---:|---:|
| mAP50 | 98.42% | 98.88% | 99.07% |
| mAP50–95 | 78.94% | 78.31% | 83.39% |
| epoch CSV累積時間 | 151.426秒 | 154.639秒 | 188.964秒 |

単一seed・少量の開発比較であり、純粋な負例効果や学習速度benchmarkと断定しない。

| B、confidence0.25 | TP | FP | FN |
|---|---:|---:|---:|
| 36枚 | 56 | 88 | 0 |
| 52枚 | 53 | 12 | 3 |

52枚版ではD水筒の出力は0/8となったが、これは学習に使った画像への再確認。
Bの3見逃し（赤frame2101、黄3601、赤4201）は十分重なる候補があり、score0.1895/0.2300/0.1980が0.25を下回っていた。
0.50の52枚版はBでTP13/FN43と、多くの対象を失う。FPが減っただけで採用しない。
根拠：[負例追加・再学習報告](../Experimental_results/2026-10-14/cone_negative_retraining_v04_r01/README.md)。

## 4. E24枚のhuman GT確定と友人コーンmodel

ユーザーがEを24枚全て確認。positive16/negative8、計32bbox、pending0。
label/review hash、positive/negative、座標/重複、原画素が一致し、assistant参考領域からhuman bboxでの正式照合へ進めた。
色属性は原画像目視との対応で、modelのclassは赤黄共通1種類。

友人の`cone.pt`を受領。実形式はYOLO11n DetectionModel、class0=cone、記録version8.4.123、学習imgsz640、device=mps。
未知globalを検査して`weights_only=True`と既設NN classの限定許可で読込。
テンソルと検査済みcfgからmodelを新規構築し、全stateをstrict=TrueでロードしてGPU推論した。
原modelをそのまま任意pickle実行で起動せず、録画/FFBにも接続しない。
学習画像数・色の範囲・元dataの重複は検証できていない。

| 同じimgsz960、confidence0.25 | B TP/FP/FN（56枠） | E TP/FP/FN（32枠） | D false枠 |
|---|---|---|---:|
| 35枚 | 56/39/0 | 31/0/1 | 8 |
| 36枚 | 56/88/0 | 32/0/0 | 3 |
| 52枚 | 53/12/3 | 30/2/2 | 0 |
| 友人YOLO11n | 50/45/6 | 20/20/12 | 16 |

友人modelの学習サイズ640も補足確認した。confidence0.25でBはTP49/FP2/FN7と良い面がある一方、EはTP8/FP0/FN24（Recall25%）、Dはfalse0だった。
サイズを変えると同時に認識対象・誤検出が変わり、単純な差替えや「大量dataなら安心」とは判断できない。
赤黄どちらも見逃している条件があり、黄色非対応や魚眼歪みだけを原因と断定しない。
確認枚数はB38＋D16＋E24＝78、960/640各1回。元PNGは保存時も加工なし。

受領weightsは`runs/cone/received_friend_models_20261014_r01/`へバイト同一保持、Git対象外。
根拠：[human GTと友人model確認](../Experimental_results/2026-10-14/friend_models_review_r01/README.md)。

## 5. 友人白線weightsの確認と未実施事項

`shiho_lane_mask_v2_best.pth`はstandalone Ultralytics modelではなくstate_dict checkpoint。
dictキーstate_dict/epoch/best_iou、tensor542、epoch50、内部記録IoU0.6839999、最後のConv shape=(2,8,3,3)を確認した。
CPUへの制限読込は成功。ただしforward/model定義・入力サイズ/resize・RGB/BGR/正規化・出力channel対応がなく、白線の映像推論は未実施。
2channel形状だけからstructureや白線channelを推測せず、友人の推論Python/model定義/repository等を依頼した。
state_dictを使うにはmodel classを別途構築する必要があることは[PyTorch公式説明](https://docs.pytorch.org/tutorials/beginner/basics/saveloadrun_tutorial.html)も参照。
このIoUは友人環境の保存値で、自分のコースでの白線認識精度ではない。

白線逸脱の右側二重線の内側選択、左境界の扱いは未合意。mask出力ができても逸脱判定は別工程としてユーザーと相談する。

## 6. 実装・検証・Git

- negative candidate exporter/merge、原画素/hash保護、確認済み空labelだけを追加する機能は本日の先行コミットに反映済み。
- dated scriptを追加し、D/E受入れ、凍結比較、52枚学習の来歴、見逃し診断、制限checkpoint受入れ、human E評価の表/図を保存。
- 関連coneテスト145件PASS（終業時に再実行）。Python構文とdiff空白、実50 epoch/args共通、model/画像/label/review hash、human32枠、図の目視を検査。
- 前半の構文括弧ミス、集計CSV filename誤記は修正して完了。元data/modelは再書換えしない。
- Matplotlibの既存Axes3D警告は出たが2D図は正常。初回metadata検査の一時設定folder warningは、推論run内folderを用意して解消。driver/venv/global環境の修復は行わない。
- 本日の既存コミット：600c3af（YOLO４）、b7b3092（実験準備）。終業commitで残りの結果・生成script・日報をまとめてpushする。
- 原録画、dataset、学習weights、友人weights、venv、生成cache/設定はGitへ入れない。

## 7. 次回の作業

1. 友人から白線のmodel定義・推論コード・前処理・channel対応を入手して、実映像でオフライン確認する。
2. コーンは正例保持と非コーン抑制のバランスを改善する比較を続ける。自作52枚版も友人版もまだ運用採用しない。
3. 将来の比較候補として、友人weightsから追加学習する案、レンズ別入力等の前処理条件を整理する。Eはtrainに混ぜない。
4. コーン距離/接地点の妥当性、TTC、YOLO→FFB、白線境界選択はこの認識評価と別に検証する。

今すぐの追加録画や実機のターミナル起動は不要。白線コード受領が次の情報待ちで、本日の作業は終了する。
代表原画像・実CSV由来グラフ4点は[本日の資料](../Experimental_results/2026-10-14/report_assets/README.md)へ。
