# 赤コーンYOLO学習・評価の準備（2026-10-12）

## 到達点と範囲

ユーザーがGPU搭載PCで学習可能と確認したため、赤コーンを主対象とする学習準備を実装した。第1段階は単一クラス`traffic_cone`。人・青箱の追加学習は初回の必須条件にしない。コーン専用モデルを学習すると、そのモデルがCOCOのperson等も自動的に保持するとは扱わない。

白線は、添付コースの外周二重線の内側など「どれを左右境界とするか」を実装前に相談する。白線逸脱機能は今回実装していない。既存の青箱・距離・TTC・FFB実装も変更しない。床十字の距離確認は並行する別課題で、YOLOデータ作成の着手条件ではない。

**まだ実赤コーンの学習・検出精度の結果はない。** 準備コードの検証と、実モデル／実データの評価は区別する。GPU PCの性能を再質問して足止めせず、同PCで実行できるスクリプトを用意した。こちらの解析Pythonにはtorch／ultralyticsがなく、解析PCのnvidia-smiもdriverへ接続できなかったため、GPUでの実行確認はGPU PCで行う。この観測をGPU PCの性能不足と解釈しない。

## 構成

| ファイル | 役割 |
|---|---|
| [setup_cone_yolo.sh](../../../setup_cone_yolo.sh) | リポジトリ内`yolo-env/`へ独立環境を作る。ROSのtheta-envを変更しない |
| [start_cone_yolo.sh](../../../start_cone_yolo.sh) | `env/train/val/test`を共通起動。GPUがなければCPUへ勝手に切り替えない |
| [cone_dataset.py](../../../src/cone_dataset.py) | 元録画全画角のPNG抽出、録画グループ分離、ラベル確認、データ検査、PC移動時のpath更新 |
| [annotate_cone_dataset.py](../../../src/annotate_cone_dataset.py) | ローカルGUIで正解枠を付ける。画面にだけ枠を描き、保存画像は編集しない |
| [run_cone_yolo.py](../../../src/run_cone_yolo.py) | 学習済みYOLOv8nを初期値に学習／検証。入力・label hash、実行条件、package版本を保存 |
| [requirements-yolo.txt](../../../requirements-yolo.txt) | YOLO用依存。torchのCUDA buildはGPU PCに対応したものを先に導入 |
| [recording_plan_template.csv](recording_plan_template.csv) | 録画session・group・split・抽出frame間隔を明示する雛形 |
| [収録手順](capture_procedure.md)／[収録専用設定](cone_capture_config.json) | FFB publish／relay／AI無効で、まず学習用rawを取得 |

## 入力・正解・評価を固定するルール

1. 最初のモデルは**元dual-fisheye画像全体**を入力にする。1280×720の元rawを無加工PNGとして保存し、画像側の切抜き・補正・描画はしない。YOLO内部のletterbox等はモデルの処理。学習と推論でこの入力定義を揃える。将来前方crop等へ変える場合は別実験として分離する。
2. 前後両レンズに写るコーンをすべてラベル付けする。後方検出をどう危険判定へ使うかは、後続の位置推定接続で決める。
3. 赤色HSVから自動で正解枠を作らない。初回は人が確認したclass 0の枠を使う。床台座も含む可視コーン全体を囲み、完全に隠れた物体の枠を推測して追加しない。
4. 撮影前にtrain／val／testの収録ブロックを分ける。同じ録画や同じ撮影ブロックの隣接frameを別splitへ分けない。valは開発確認、testは最後の評価に残す。
5. 画像を抽出した直後のstatusはすべて`pending`。ラベルファイルを勝手に空で作らない。コーンなしは明示的なnegative確認後だけ空labelを保存する。未確認を背景扱いする事故を防ぐ。
6. コーンあり・なし、他の赤い物体、背景・距離・左右位置の違いを入れる。単に同じ位置の類似frameを大量に集めても独立した情報は増えない。
7. `check`は全画像／labelの整合性を確認するが、正解の取り漏れや類似場面の漏洩を自動で証明しない。完全一致する動画・pixel hashと宣言groupの漏洩は拒否する。別encodeで似た場面、group申告ミスは人の確認が残る。
8. class 0以外、非有限値、範囲外box、positive／negativeとlabelの不一致、追加の未登録画像／label、画像改変は学習前に拒否する。各splitのpositive最低1枚は整合性の最低条件で、十分な学習量の保証ではない。
9. レビュー時点のlabel SHAをreviews.csvへ保存する。有効な形式のままlabelを修正しても、明示的にレビューし直すまで学習を拒否する。既存labelの修正は外部editor／ラベルツールで行い、`cone_dataset.py review`で再確認する。

## 1. GPU PC：独立環境

### A/B提出後の変更

ユーザーよりC用の場所が用意しづらいと共有されたため、[A/B受入れ報告](../cone_ab_intake/README.md)で試作をtrain／valの2splitに分離した。3splitは最終評価まで揃える場合の構成であり、試作の着手条件ではない。明示`--development-only`のdatasetではtestを未取得として保持し、testコマンドでvalを流用しない。以下の3split説明は通常モードの記録で、今回A/B試作には受入れ報告の手順を優先する。

その後、黄色コーンも対象と確認し、73枚・109枠の初回用`ab_bootstrap_v01`を作成した。枠はassistantの視覚レビューで、人の独立品質確認は残る。現在のGPU PCへの移行・初回学習は[bootstrap手順](../cone_ab_intake/gpu_bootstrap_procedure.md)を優先する。元400枚版も維持し、未確認327枚を背景として学習させない。

このリポジトリの最新版をGPU PCへ取得し、**そのリポジトリrootで**実行する。ハンコンPCと同じPCでも、`yopi_ws`のFFBリポジトリ内ではなく、カメラ側リポジトリのrootを使う。今回の新規ファイルは未コミット／未pushであり、PC間反映は別途必要。

```bash
./setup_cone_yolo.sh
./start_cone_yolo.sh env \
  --output-dir runs/cone/environment_r01
```

setupはPython venvだけへpip installする。既存のROS環境をactivateしたままでも、install先は明示した`yolo-env/bin/python3`。`env`はCUDA tensor演算、ローカルのYOLOv8n重みload、合成黒画像1枚のGPU forwardまで確認する。これは実コーンの精度評価ではない。

CUDA buildを明示する必要がある場合は、[PyTorch公式selector](https://pytorch.org/get-started/locally/)でGPU PCのOS／Python／driverに対応するwheelを確認し、`./setup_cone_yolo.sh --torch-index-url https://download.pytorch.org/whl/cuXXX`へ**実在する選択値**を指定する。`cuXXX`を文字どおり実行しない。GPU性能に問題がなくても、driverとPython wheelの対応は実行環境で確認する。

初回モデルは既存の`src/yolov8n.pt`を再利用し、別のモデル世代への移行を増やさない。[Ultralytics公式install](https://docs.ultralytics.com/quickstart/)は特定CUDAを使う場合にPyTorchを先に導入する手順を案内している。実際に解決されたpackage版は各runの`environment_freeze.txt`へ保存する。

## 2. 録画から無加工画像を作成

[収録手順](capture_procedure.md)でraw sessionを取得し、アーカイブなら既存の安全展開手順で展開する。ここではsessionディレクトリを入力にし、新しいアーカイブ展開処理を重複実装していない。

雛形を別名へコピーして、各行の`session_dir`へ実際のsession絶対pathを入力する。同じblockの複数sessionは行を増やして同じgroup_id／splitにする。`end_frame`空欄は最後まで、`stride_frames=30`は約30frame毎で、実時刻の1秒とは限らない。

```bash
source yolo-env/bin/activate
python3 src/cone_dataset.py prepare \
  --plan /path/to/filled_recording_plan.csv \
  --output-dir datasets/cone/v01
```

新規datasetだけを作成し、既存結果を上書きしない。全rawフレームを逐次デコードしてCSV件数・metadata解像度を確認し、抽出frameの画素一致とPNG／source hashを保存する。同じsplit内で完全一致したpixelは重複として省き、別splitの完全一致は拒否する。

雛形はsession pathが空なので、このままprepareへ渡すとエラーになる。入力コーンの実データを生成したことにはしない。

## 3. ラベル付け

デスクトップ画面が使えるPCで：

```bash
python3 src/annotate_cone_dataset.py --dataset datasets/cone/v01
```

- `P`：枠を付ける。各コーンをドラッグし、Enter／Spaceで次の枠へ、Escで選択完了。その後`Y`で全可視コーンの確認を確定する。
- `N`：コーンなし。前後両レンズにないことを確認し、追加の`Y`でnegativeを確定。
- `S`：保留、`Q`：終了。保留は学習不可のまま残る。
- 既存labelがある場合は上書きせず、その内容を確認してから受け入れる。表示GUIが使えなければ任意のラベル付けツールでYOLO形式を出力し、`cone_dataset.py review --dataset DATASET --image images/train/FILE.png --status positive --note '確認内容'`等で明示レビューする。

GUIは画像を画面へ表示して枠を指定するだけ。保存されるのは正解のtxtとreviews.csvであり、raw PNGへ注釈・色補正を加えない。一般的なYOLO形式は`class x_center y_center width height`の正規化座標。[公式形式](https://docs.ultralytics.com/datasets/detect/)

```bash
python3 src/cone_dataset.py check --dataset datasets/cone/v01
```

PASSはデータ整合性のPASSで、モデル精度のPASSではない。negativeをまだ持たないsplitは警告を出す。未知ファイルや未確認labelが残れば先に解消する。

datasetを別PCへコピーした場合は画像・label・manifest・reviews・dataset.jsonをまとめて保持し、`python3 src/cone_dataset.py relocate --dataset datasets/cone/v01`でdata.yamlのroot pathだけを更新してからcheckする。既存の原本を上書きしない。

## 4. GPU PC：初回学習と評価

```bash
./start_cone_yolo.sh train \
  --dataset datasets/cone/v01 \
  --output-dir runs/cone/train_v01 \
  --epochs 50 --batch 8 --imgsz 960 --device 0

./start_cone_yolo.sh val \
  --dataset datasets/cone/v01 \
  --weights runs/cone/train_v01/model/weights/best.pt \
  --output-dir runs/cone/val_v01 --device 0
```

epochs50／batch8／imgsz960は初回の試作条件で、GPU性能・データ量に最適と確認した値ではない。OOMなら記録を残してbatchを下げ、新規run名で再試験する。元画角を維持しつつYOLO内部で960に整形する条件を記録する。左右／上下反転や大きい回転を入れず、固定カメラ方向の最初の基準を作る。`plots=False`でlabel入りカメラ画像を結果資料として自動保存しない。

valを見て開発判断をした後、条件を凍結してから最後に：

```bash
./start_cone_yolo.sh test \
  --dataset datasets/cone/v01 \
  --weights runs/cone/train_v01/model/weights/best.pt \
  --output-dir runs/cone/test_v01 --device 0
```

trainはtestを使わない。testを見て調整を繰り返した場合、そのtestは最終の独立評価として扱えなくなる。[公式train](https://docs.ultralytics.com/modes/train/)

runごとに入力・label・model hash、条件、GPU名、package freezeとmetricsを保存する。YOLO生成のtrain／val／test label cacheだけは直前に無効化し、元txtを必ず読み直す。消すのは再生成可能な`labels/{train,val,test}.cache`だけで、画像・正解txtは削除しない。

この段階はモデルの検出評価で、推論の実FPS・物体追跡・距離精度・FFBをまだ保証しない。結果が出たら録画上の見逃し／誤検出、距離・左右・背景別の性能と処理時間を確認し、その後dry_runの警告経路へ接続する。

## Git・検証

コード、依存ファイル、準備手順はGit対象。`yolo-env/`、`datasets/cone/`、`runs/cone/`はGit対象外。原録画・学習用PNG・重いモデルrunはDrive等へまとめ、manifest／hash・小さい集計結果を実験日付フォルダへ保存する。

[データテスト](../../../tests/test_cone_dataset.py)と[runnerテスト](../../../tests/test_run_cone_yolo.py)で合成動画・mock GPUを使い、原画素保持、split漏洩拒否、未確認拒否、label形式、cache扱い、test分離、CUDAなし拒否、上書き拒否を確認する。mock GPUテストは実GPUの証明ではない。GPU環境・OpenCV GUI・Ultralytics実APIの統合確認・実データ学習は未実施として残す。

[verification.json](verification.json)に新規26＋9件、既存preflight21＋runner13件、計69 tests PASSとソース／設定／初期重みhashを保存した。shell構文、Python構文、文書リンク、3項目だけの収録設定差分、FFB／challenge不要・relay起動なしもPASS。元から存在する`src/bird_eye.py`と`src/evaluate_ground_contact.py`の未コミット変更は本作業で編集せず保持した。今回の準備ファイルも未コミットで、Git操作は実施していない。
