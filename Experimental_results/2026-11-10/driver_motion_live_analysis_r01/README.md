# 実走行ログ解析 r01（2026-11-10）

> 後続：[一時保留20件の境界座標・輪郭監査](../support_boundary_audit_r01/README.md)。5件は閉じた支持点がfloat bbox下端を0.024～0.711px超える最終条件で保留、15件は下側の未閉輪郭。診断候補を分離したが、runtimeの保留解除は行っていない。

**提出された走行録画に対応する区間で、平均29.89件/秒の測距結果、569件中549件の数値出力（96.49%）を確認した。** 残る20件は支持点抽出時の色輪郭の探索端到達による保留。録画に表示された19個の数値は全て同じsession/frameのログと小数3桁で一致した。

これは今回の単一コーンへの接近・離反の動作確認。物理距離の誤差保証、全環境での完成、操縦の遅延測定、自動停止への採用を意味しない。今回の作業はオフライン解析のみで、測距・操縦・保留条件・床校正は変更していない。

## 入力と来歴

- 提出アーカイブ：`/home/robo25/Downloads/driver_motion_live_20261110_151151.tar.xz`。
- アーカイブSHA-256：`a733f93961197a6db7c6a65bb8d2d7fa8a12cc599bddee4adc79552a90d94b45`。
- raw展開先：`recordings/2026-11-10/driver_motion_live_intake_r01/driver_motion_live_20261110_151151/`（Git対象外）。
- メンバーを確認した上で、2つのJSONL、engine/profile/終了summary、stderrのregular file計6点のみ展開。フォントやUltralytics設定は解析に不要なため展開・実行しない。
- session：`7f33c225af3948c2aa61d66d52765c2e`、全55,906処理行、bridgeも55,906行。
- 全行の`inference_source=live_cuda_yolo`。engine記録のGPUはNVIDIA GeForce RTX 4070 Laptop GPU、torch 2.7.1+cu118。
- 重みSHA：`3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b`（既存v03と一致）。
- 床profileの実ファイルSHA、engine記録、全処理行のprofile SHAは `17a287159fcec644c373141cdbef893aa19dfced782dcf32d20b5f12dc91954e` で一致。11/9準備済みprofileのバイト列とも一致。
- config SHA：`8c614e0fc79da54a8d3bc5afb6108242ca67072e45821006a7ae2216e29a01c0`。画像寸法1280×720、未変更のnative ray basis、固定取付・局所平面床の実験用profile。
- 6入力のSHAとmetadataは [results_r01/analysis.json](results_r01/analysis.json) に記録。入力を解析前後に照合し、更新されていないことを確認した。

ログには受信器／senderの全実行ソースのhashはないため、実行コード全体の独立した同一性までは証明しない。CUDA使用は提出されたengine metadataと全処理行の記録に基づく。今回こちらでCUDAを新たに起動した結果ではない。

## 集計区間を混ぜない

|区間|source frame（両端を含む）|処理件数|数値出力|処理結果の保留率|平均処理更新頻度|
|---|---|---:|---:|---:|---:|
|全提出ログ|全55,906件|55,906|28,288|49.40%|29.66件/秒|
|15:18静止録画の表示source範囲|10031～10300|269|269|0%|29.93件/秒|
|15:31走行録画の表示source範囲|33809～34379|569|549|3.51%|29.89件/秒|

全体の処理完了時刻の幅は1,884.9866秒（約31分25秒）。静止範囲は8.9532秒、走行範囲は19.0014秒。**画面録画の最初・最後に読めたsource frameで切り出した範囲**であり、スクリーン録画の正確な開始終了PTSや実際に車輪が回っていた時間だけの抽出ではない。

全提出ログは録画外の区間も含む。全体には`no_candidate`15,117件、`grazing_or_outside_range`5,222件、`colour_contour_reaches_roi_edge`6,804件等がある。これらの時間帯の画面全体は未受領のため、対象が意図的に不在だった、全て同じコーンだった、走行試験だったとは断定しない。全体の49.40%を今回の約19秒の走行試験の保留率に置き換えない。一方で、今回の96.49%を31分間の連続成功率にも一般化しない。

平均処理更新頻度は同sessionの `(件数−1)/(最後の処理完了時刻−最初の処理完了時刻)`。受信source frame番号の差から推論FPSを計算していない。処理結果の保留率は行数ベースであり、GUIの表示保留時間率ではない。

## 走行対応区間の処理時間

|指標|P50|P95|最大|
|---|---:|---:|---:|
|YOLO predictor呼出し|7.00ms|10.06ms|16.94ms|
|支持点抽出・床幾何|4.18ms|19.09ms|97.03ms|
|GPU PCの画像受信→測距処理完了|17.18ms|34.24ms|115.41ms|
|隣り合う処理結果の完了間隔|33.25ms|49.05ms|105.58ms|

P50/P95はnearest-rank。予測呼出し時間は純粋なGPUカーネル時間ではない。受信→処理完了は、カメラ露光・キャプチャ・送信・ネットワーク・UI描画を含む総遅延ではない。これだけで「操縦遅延が増えなかった」とは認定しない。

走行対応区間569件はbridgeで全件、現在session／age条件を満たして受理。距離あり549件、距離なし20件。受理はGPU側結果がUIへ渡せる状態だったという記録で、UIが全件を実際に描画した証明ではない。

## 録画表示と実ログの照合

[前回の20標本CSV](../driver_motion_live_review_r01/screen_observations.csv)のうち数値が表示された19標本について、session先頭8文字、source frame、小数3桁の距離が全て一致した。表示receive-ageも処理完了時のframe ageより後で整合していた。各照合値は`analysis.json`の`screen_numeric_matches`。

タイマー17秒のWITHHELD画面はsource frameが表示されないため、架空のframeを割り当てない。ログ側で同じ範囲に保留が存在することは確認したが、その画面を1つの処理行へ厳密に同定したとは扱わない。

静止区間のログ出力範囲は0.978017～0.978703m。走行区間では0.682823～1.021010m。**実測との誤差ではなく出力の範囲**。ユーザーからは現場で「距離変化を確認、小さな誤差で正しいと思う」と申告されているが、同時刻の独立した実測系列がないのでMAE／RMSEは未算出。

## 残る20件の保留の内訳

全件が`colour_contour_reaches_roi_edge`。対象自体はYOLOが検出していたが、色輪郭から支持点を確定する条件を満たさなかった。ログの最初のupper contextにあるcomponent接触情報による内訳：

|探索端|件数|該当source frame|補助理由|
|---|---:|---|---|
|左端のみ|5|33965、33966、33974、34239、34240|横側拡張の候補点が元bbox外：`completed_point_outside_original_bbox`|
|下端のみ|15|34305～34307、34310～34315、34317～34322|下端接触で横側専用・上側専用の補完対象外：`not_lateral_only_contact`／`not_top_only_contact`|

全20件のselected colourはred、上端／右端の接触は0。元のYOLO bbox、探索crop、接触方向、色成分boundsは [results_r01/motion_window_rejections.json](results_r01/motion_window_rejections.json) に保存。rawログ側の`support_observation`を参照し、画面録画から色マスクを再計算していない。

このROI端は支持点抽出内部の探索cropの端であり、`--motion-target-roi`の単純な幅不足とは限らない。画面表示の単語だけでtarget ROI拡大や保留解除を勧めない。また、このログには新しいnative画像は保存されていない。元画素なしでは、見えていた実際の台座の端か、反射・他物体との接続かを再判定できない。画像を推測して下端を延長したり、距離を保持して欠測を埋めたりしない。

**次の改善対象は通信経路の作り直しではなく、支持点抽出の境界接触への対処。** まず上記ログのbbox／crop／候補点の関係をオフラインで調べる。元画素を必要とする段階になった場合だけ、既存の未展開保存画像がないか確認する。追加撮影を今の着手条件にはしない。

## 終了状態

- 送信55,906・返却55,906、JSONL各55,906行。欠損bridge event 0。metadataとの件数一致。
- 全体でage等によるbridge破棄1件。最初の処理frame 2が1,451.52msを要し、`frame_processing_too_old`で保留、bridgeでも不採用。以後の走行対応区間の遅延保留は0。
- `worker_error=null`、`io_thread_stopped=true`、`child_stopped=true`。子のexitcode −15は終了処理がSIGTERMする実装と整合し、この値だけで推論クラッシュとは判定しない。
- tap lock drop 13、publish最大0.303msは終了summaryの全run値。制御信号の往復時間やUI描画遅延の指標ではない。
- 制御channel変更なし・ROS測距出力なし・FFBなしというflagを保持。接地点認定・物理精度・取付転用・動的傾き補償の承認flagは変更していない。

## 再現と検証

```bash
cd /home/robo25/theta_ws/RICHO-theta
python3 src/report_driver_motion_logs.py \
  --input-dir recordings/2026-11-10/driver_motion_live_intake_r01/driver_motion_live_20261110_151151 \
  --output-dir Experimental_results/2026-11-10/driver_motion_live_analysis_r01/full_run_report_r02

python3 Experimental_results/2026-11-10/driver_motion_live_analysis_r01/analyze.py \
  --input-dir recordings/2026-11-10/driver_motion_live_intake_r01/driver_motion_live_20261110_151151 \
  --output-dir Experimental_results/2026-11-10/driver_motion_live_analysis_r01/results_r02
```

元データを実行せず、Python標準ライブラリだけで処理。出力先は未使用フォルダを指定する。初回結果は [full_run_report/summary.json](full_run_report/summary.json)、[results_r01/analysis.json](results_r01/analysis.json)、[走行区間CSV](results_r01/motion_window_frames.csv)。全runの大きい`full_run_report/frames.csv`は再生成できるローカル詳細資料で、Git保存時は必要性を確認して選別する。rawログ・アーカイブはGitへ追加しない。

255MBの元JSONLには各frameの詳細な画素支持情報があるため、集計器を修正し、JSON全体の妥当性と入力SHAを検査しつつスカラー項目だけをメモリ保持するようにした。測距・描画・送受信から独立したオフライン処理のみの変更。新規の投影テストを含む**11テスト成功**。追加した解析スクリプトでは全件のキー照合・時刻・false承認flag・profile SHA・終了件数・19表示値の一致・入力不変を検査し、例外なく完了。

この作業では測距本体・操縦本体のソース変更、カメラ／ROS／実機／CUDAの起動、Git commit/pushを行っていない。
