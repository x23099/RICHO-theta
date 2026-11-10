# 運転画面での走行中測距：録画レビュー r01

> 後続更新：実走行フォルダを受領し、[全55,906件と録画対応区間の解析](../driver_motion_live_analysis_r01/README.md)を完了した。以下の「ログ未受領」は画面レビュー時点の履歴。ログの再提出・追加撮影は不要。

2026-11-10。運転用映像と測距表示の同時動作、接近・離反への追従を提出画面録画で確認した。**今回の場面での動作確認であり、誤差・操縦遅延・接触距離の保証ではない。** 操縦、測距、床校正、保留条件は本レビューで変更していない。

## 提出物と方法

- 静止側：`Screencast from 2026年11月10日 15時18分38秒.tar.xz`。既に確認した約10.43秒の録画。1秒間隔10標本で0.978～0.979m、表示元frame更新を確認。
- 走行側：`/home/robo25/Downloads/Screencast from 2026年11月10日 15時31分51秒.tar.xz`。regular fileのWebM 1本のみを収録。実走行の測距JSONLは含まない。
- 走行アーカイブSHA-256：`45e43d5917340c43d4a0e703603ba0e3526f382c237d959886bfab6c3bd991f3`。
- 展開WebM SHA-256：`b423f779bd8aed85ebb3b4dfd000ed8a5ffdb1e790f31d132c3e5738509e5153`。
- 生録画／抽出先：`recordings/2026-11-10/driver_motion_screencast_r02/`（Git対象外）。
- WebMは1920×1200の**運転UI画面録画**、長さ19.942870秒。1280×720の未展開カメラ画像やセンサ原本ではない。運転UI自身の展開・描画を含む。
- FFmpegの時間サンプリングだけを使い、20 PNGを1920×1200のまま保存。追加の注釈・合成・切抜き・リサイズ・色補正なし。

抽出コマンド（同名PNGがない新しい保存先で実行）：

```bash
ffmpeg -hide_banner -loglevel error \
  -i 'recordings/2026-11-10/driver_motion_screencast_r02/Screencast from 2026年11月10日 15時31分51秒.webm' \
  -vf fps=1 -vsync vfr \
  recordings/2026-11-10/driver_motion_screencast_r02/sample_%02d.png
```

目視転記の全20標本は [screen_observations.csv](screen_observations.csv)。`desktop_timer_sec` は画面右上の録画タイマーの整数表示で、カメラ露光時刻や正確な抽出PTSではない。sourceは画面に見えるsession先頭8文字だけを転記し、完全なsessionへ推測補完しない。保留場面ではsession/frame/ageが表示されないためCSVも空欄。

## 結果

|観察項目|結果|解釈の範囲|
|---|---|---|
|開始側→接近→離反→終了側|1.007→0.833→0.683付近→0.892→1.007m|表示値が映像内の接近・離反に追従。移動距離の実測ではない|
|20標本の数値表示|19標本|全処理frameの可用率、時間ベースの表示率ではない|
|20標本の保留|1標本（タイマー17秒）|短い保留を含めて確認。全frameを確認したわけではない|
|保留理由|`colour_contour_reaches_roi_edge`|19秒側までに数値へ復帰。境界のどの側か、背景反射との連結などの内訳はスクリーン録画だけでは不明|
|標本の表示距離範囲|0.683～1.008m|この録画の出力範囲。動作可能範囲や距離精度の認定ではない|
|数値標本のreceive-age表示|18～57ms|GPU PCの画像受信から表示時点まで。露光→送信→ネットワークを含む総遅延ではない|
|数値表示のsource frame|33809→34379へ進行|受信元のframe番号。推論FPSや全frame処理の証明ではない|
|現場の評価|ユーザーから「距離変化を確認、小さな誤差で正しいと思う」との申告|独立した同時刻の実測系列は未受領。MAE/RMSE等は計算しない|

19/20は**1秒サンプリングした表示観察の内訳**であり、「常時95%成功」「保留時間1秒」「推論19Hz」と読み替えない。開始・終了の丸め表示が同じでも同じ物理位置へ戻った証明ではない。UIのTRIP/gear/速度表示を校正済みオドメトリとして扱わない。

この段階の到達点は「今回の単一コーン・接近と離反の場面で走行中のリアルタイム測距表示が動作した」。旋回、複数物体、異なる床勾配、強い揺れ、取付変更への一般化までは未確認。カメラ固定・局所平面床の仮定、接地点や車体座標系との未確定事項は変更しない。距離は制御／ブレーキ／FFBへ接続していない。

## 次の作業：追加撮影ではなく今回のログ

このPCのrepo／Downloadsを検索したところ、見つかったのは `driver_motion_bridge_r01/verification_r01～r03/pipe_replay/` の保存枠再生ログだけ。これを今回の走行実績へ混ぜない。GPU PCの実際の `--motion-output-dir` にある以下2ファイルが必要。

1. `motion_distance_frames.jsonl`
2. `motion_bridge_events.jsonl`

保存先を忘れた場合、**GPU PC**で既存ファイルを探すだけでよい（受信・撮影の再起動不要）：

```bash
cd ~/yopi_ws/RICHO-theta
find Experimental_results/2026-11-10 -type f \
  -path '*/driver_motion_live_*/*' -name motion_distance_frames.jsonl -print
```

手順どおりなら `Experimental_results/2026-11-10/driver_motion_live_日時/`。変更して起動した場合は実際の出力先を優先する。実験終了時には従来の手順で**機体を停止してから**UIを閉じる。終了summaryは補足であり、この2ログの集計開始には必須としない。まだ動作中のコピーは切れた最終行になり得るので、ログは動作終了後の整合した組を渡す。生録画や追加実測の提出を先に求めない。

## オフライン集計器

[src/report_driver_motion_logs.py](../../../src/report_driver_motion_logs.py) を追加した。実行には標準Pythonのみを使用し、OpenCV・YOLO・CUDA・ROS・ネットワーク・実機起動は不要。既存の送受信器からは呼び出さない。

```bash
python3 src/report_driver_motion_logs.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_実際の日時 \
  --output-dir Experimental_results/2026-11-10/driver_motion_live_report_r01
```

`--input-dir` は受信で既に作られた2ログのフォルダ、`--output-dir` は入力と別の未使用フォルダ。出力は `summary.json` と `frames.csv`。入力は読み取り専用、SHA-256を記録し、既存出力を上書きしない。

- sessionごとの処理件数、数値／保留と理由、処理済み結果の完了間隔、predict／支持点幾何／受信から処理完了までの経過時間を集計。P50/P95はnearest-rank法。
- 処理更新頻度は同じsessionの `(処理件数−1)/(最終完了時刻−最初の完了時刻)`。受信frame番号の差を推論回数にしない。別sessionの時計・空白時間を結合しない。
- bridge側の現在session／age採用と、GPU側が距離を計算できたことを区別する。採用された結果でも数値なしの場合がある。bridge採用はUIが実際にその結果を描画した証明ではない。
- `(session, frame)` と距離・理由・source時刻等の照合により別run混入・重複を拒否。未完成の行、不正値／NaN、非単調時刻、承認flagの混入はエラーとする。
- frame側だけに残る結果は欠損eventとして明記し、表示採用に数えない。`inference_source` を保存し、キャッシュ結果を実CUDAと誤認しない。
- GUIの保留時間率・実測誤差・露光からの総遅延はこの2ログだけでは出せないため、対応フィールドはnullのまま。

## 検証

新規10テスト成功（合成ログのみ）。空・切れたJSONL、重複、別run、nonfinite、時刻、bool型、flag、session分離、欠損event、出力上書き拒否、入力不変を確認。

```bash
python3 -m unittest discover -s tests -p test_report_driver_motion_logs.py -v
```

実在の保存枠再生10行でも動作を確認し、[cached_report_smoke_r01/summary.json](cached_report_smoke_r01/summary.json) に保存した。2つの再生sessionを分離、距離3行／保留7行、bridge受理10行。**この値・処理時間は再生テストのもの。今回の走行結果ではない。** 実走行ログの更新率・保留率・推論時間は未集計。測距本体が変わっていないため既存の134件の記録は再利用し、本報告だけのために再実行していない。

この作業では実カメラ・実機・ROS・CUDAの起動、Git commit/pushを行っていない。走行はユーザーが実施し、こちらは提出済み録画と保存ログのみを分析した。
