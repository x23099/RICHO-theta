# 静止リアルタイム測距ログの集計入口（2026-10-27）

## できるようになったこと

受信時に保存される`distance_frames.jsonl`と`live_summary.json`を、カメラやGPUなしで集計できる。
既存ランチャーに`report`を追加した。`receive`・`replay`の動作や、距離計算・安全判定は変更していない。

出力は次の4種類。

- `report.md`：接続session別の処理件数、条件付き出力件数、対象ROI、保留理由、処理時間。
- `processed_frames.csv`：グラフと数値の元になる処理済みフレーム一覧。
- `processing_diagnostics.png`：条件付き推定距離、受信後の経過時間、主理由ごとの件数。
- `summary.json`：全blocker、中央値・p95・最大値、入力と出力のSHA256、終了状態。

カメラ画像は作成・編集しない。グラフは数値ログから新規に生成する。

## 次回、実機の受信を終えたあと

受信プログラムが終了してから実行する。下の`INPUT_DIR`だけ、実際の受信出力先へ置き換える。
GPU PCから2ファイルを同じフォルダへコピーすれば、このPCでも実行可能。

```bash
cd /home/robo25/theta_ws/RICHO-theta
export THETA_DISTANCE_PYTHON=/home/robo25/theta-env/bin/python3

INPUT_DIR="Experimental_results/2026-10-27/cone_distance_live_r01"

./start_cone_distance.sh report \
  --input-dir "$INPUT_DIR" \
  --output-dir Experimental_results/2026-10-27/cone_distance_live_summary_r01
```

日付・入力フォルダは実際の実験日に合わせる。上の入力名は使用例で、実機受信を済ませたことを意味しない。
`THETA_DISTANCE_PYTHON`は実行PCの既存Python環境に合わせる。通常の集計には標準ライブラリ、グラフ生成には既存matplotlibを使う。
matplotlibがなければ、インストールせず`--no-plots`で表だけ生成できる。
出力先が既にある場合は上書きせず停止する。

## 持ち帰るもの

|ファイル|用途|
|---|---|
|`distance_frames.jsonl`|処理した画像のsession・番号・保留理由・条件付き距離・処理時間|
|`live_summary.json`|受信の終了状態・worker/scene jobの終了状態・モデル/設定の記録|

この2ファイルだけで今回の集計は可能。映像・元画像の提出はこの集計の必須条件ではない。
ただし、距離精度・実際の画角・見落としの検証には、別途元画像や実測値が必要。

## 正常終了と実験成功を区別する

|集計状態|意味|
|---|---|
|`FINALIZED_DIAGNOSTIC_LOG`|整合する終了記録と処理ログがある。距離精度や実機機能の合格ではない|
|`INCOMPLETE_CAPTURE`|summaryがない、異常終了、後片付け未完了、または明示的に末尾断片を除外した|
|`NO_FRAME_EVIDENCE`|処理ログにフレームがない。受信成功の証拠にはならない|

CLIの終了コード0は「集計ファイルを生成できた」という意味。実験のPASS判定ではない。
入力の破損・順序矛盾・不正な値などを検出した場合は終了コード1で停止する。

デフォルトでは壊れたJSON行を無視しない。
異常終了で最後の改行なし行だけが途中で切れている場合に限り、
`--allow-truncated-last-line`でその1行を明示的に除外できる。その結果は常に不完全な記録として扱う。
途中行の破損や、行として完結した不正JSONはこのオプションでも除外しない。

## 数値の意味と限界

- 条件付き出力率の分母は**処理・記録されたフレーム**。実際の表示時間率、すべての受信画像に対する率ではない。
- 完了頻度はログ間の処理完了頻度。カメラFPS・ネットワーク帯域の測定ではない。
- `frame_age_ms`は受信PC内での画像受信から処理完了まで。カメラ撮影から受信までの遅延ではない。
- 画像番号の隙間は記録されなかったデコード画像番号。ネットワークのパケット損失率ではない。
- 実測距離を入力していないため、距離の誤差・精度を評価していない。
- 対象ROIを保存・表示する。中央ROIを選んだ結果を前方全体の監視結果へ読み替えない。
- 受信切断中はworkerのフレーム記録がなくなるため、その間の表示状態をこのログから復元しない。

現状はpaper7基準の条件付き距離であり、`base_link`・接地位置の物理的検証やFFBの承認ではない。

## 今回の検証結果

|項目|結果|
|---|---|
|関連テスト|136件成功、失敗・エラー・skip各0（既存114件＋集計22件）|
|過去の数値解析・入力・画像の照合|68ファイル、94照合、不一致0|
|実workerログ→集計・グラフ|人工画像・注入predictor・制御時計で8件、2sessionを確認|
|構文・ランチャー|py_compile、bash -n、git diff --check成功|
|新規カメラ受信・CUDA推論・実通信・ROS・FFB|未実施|
|Git commit / push|未実施|

最終証拠は[verification_r02/summary.json](verification_r02/summary.json)と
[テスト一覧](verification_r02/tests.csv)。`verification_r01`は対象ROIの明示チェックを追加する前の中間検証として保存している。

[合成データの集計例](synthetic_smoke_r02/report/report.md)と
[グラフ](synthetic_smoke_r02/report/processing_diagnostics.png)は**ソフトウェア試験用**。
人工画像・検出枠・成功扱いのscene仮説・時計を注入しており、実カメラの距離精度や処理時間ではない。
グラフ上にも未確認predictorであることを明示した。処理時間が0なのは制御時計を進めていないためで、処理が瞬時に終わったという測定ではない。
`synthetic_smoke_r01`は表とグラフの確認中に生成した中間例。現行コードの再現には`r02`を使用する。

再現コマンド（それぞれ未使用の出力名へ変更する）。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-10-27/cone_distance_live_report_r01/verify_report.py \
  --output-dir Experimental_results/2026-10-27/cone_distance_live_report_r01/verification_r03

env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-10-27/cone_distance_live_report_r01/make_synthetic_example.py \
  --output-dir Experimental_results/2026-10-27/cone_distance_live_report_r01/synthetic_smoke_r03
```

既存matplotlib環境ではAxes3Dをimportできない警告が出るが、今回使用する2Dグラフの生成・表示内容は確認済み。
共有環境・ドライバー・パッケージは変更していない。

## 次の確認

学校での最優先は変わらず、静止した実カメラ入力をGPU PCへ送り、その場で距離／保留理由を継続表示できるかの確認。
[既存の受信手順](../../2026-10-26/cone_distance_report_r01/README.md)と
[再接続・終了時の確認点](../cone_distance_runtime_r01/README.md)を使う。
今回の追加作業のための録画やユーザー操作は、今は不要。
