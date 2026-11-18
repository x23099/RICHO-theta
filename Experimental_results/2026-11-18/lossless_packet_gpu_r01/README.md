# GPUPC：保存4画像でPNG経路と既存CUDA測距を一括実測

最新: **GPUPC提出r01を受領・監査済み**。[実測報告](submission_report_r01.md)。全40対で画素/判定不変、初片→測距完了中央値49.09ms/最大52.97ms、PNG開始から全体92.09/98.95ms。新11を含む308テスト成功。**同じGPU比較の再試験は不要**。実通信・映像共存・元鮮度/FFBの認定ではない。

以下は実行時に使った再現手順。準備段階では新21を含む関連297成功/失敗skip0/12.70秒、実保存4原画・実PNG・既存幾何＋テスト用検出結果80測定40対を確認した。[準備監査](verification_r01/audit.json)、[固定実行manifest](verification_r01/run_manifest.json)はそのまま保持する。

目的は、前段の解析PC CPU値を使った仮想回線モデルに対し、GPUPCのPNG encode/検査/fragment/復号＋既存CUDA測距の時間と判定を実測すること。実通信・実機・FFBの採用試験ではない。

## ユーザーの作業（GPUPCのみ）

追加撮影、映像送信・受信、画面録画、ハンコン操作、機体走行、matsunucは不要。GPUを使う他の測定は終了してから実行する。通常の環境や依存パッケージは変更しない。

### 1. 今回の追加分をGitでGPUPCへ反映

今回のrunnerとverification_r01/run_manifest.jsonを含めて反映する。パッチ適用は不要。Gitのpush/pull自体はこの準備作業では行っていない。

存在確認（GPUPCの絶対パス、引用符なし）:

```bash
cd /home/hsr/yopi_ws/RICHO-theta
ls Experimental_results/2026-11-18/lossless_packet_gpu_r01/run.py Experimental_results/2026-11-18/lossless_packet_gpu_r01/verification_r01/run_manifest.json
```

両方のファイルが表示されること。Gitで同期できるのはコードと小さい結果JSONであり、recordingsの原画や重みは同期されないが、今回の4枚と重みは以前GPUPCで存在を確認したものを使う。

### 2. 事前確認

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-18/lossless_packet_gpu_r01/run.py check \
  --weights /home/hsr/Downloads/cone_distance_v03.pt
```

`state: READY_NOT_MEASURED`、`CUDA_tensor_test_passed: true`、画像4件とそれぞれのROIが表示されたら次へ。ここではモデルを読み込まず、出力ディレクトリやarchiveも作らない。CUDAテンソル演算までは実行する。**エラーなら本計測へ進まず、その全文を送ってください。** CPUへのfallbackやdriver再導入はしない。

チェック内容:

- 固定manifestと実コード・config・profileのSHA一致
- 重みが既存configのSHAと一致
- 保存4PNGの名前・ファイルSHA・1280×720 BGR画像
- CUDA利用可能性と実テンソル演算、環境version

### 3. 本計測（成功した事前確認と同じターミナル）

```bash
./yolo-env/bin/python3 Experimental_results/2026-11-18/lossless_packet_gpu_r01/run.py run \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount \
  --output-dir recordings/2026-11-18/lossless_packet_gpu_r01 \
  --archive /home/hsr/Downloads/lossless_packet_gpu_20261118_r01.tar.xz
```

モデル1個で4枚を実CUDA推論する。各画像6warmup除外＋元/PNG/PNG/元の5反復、計24warmup除外・80測定・40対。計測本体はサンプル間で180秒予算を確認する（モデル起動時間や実行中のGPU呼出しを強制停止するtimeoutではない）。

完了時に `state: complete`、`images: 4`、`measured_samples: 80`、`paired_samples: 40` とarchiveのパスが表示される。

### 4. 提出

**Downloadsのlossless_packet_gpu_20261118_r01.tar.xzを1つ送ってください。** 手動の圧縮や追加ファイルは不要。

archiveにはsummary.json / samples.jsonl / pairs.jsonl / per_image_summary.json / run_manifest.jsonの5点だけを含める。原画像、重み、Ultralytics設定やfont、画面録画は含めない。結果はGPUPCのrecordings/2026-11-18/lossless_packet_gpu_r01にも残る。

既存output/archiveがあれば上書きせず停止する。再試行が必要なら、まずエラーを確認してから、**outputとarchiveの両方をr02など別名へ変更**する。元ファイルの削除・`--force`・パッチ再適用は不要。

## 原画と対象範囲

runnerはリポジトリのrecordingsとExperimental_resultsを上限付きで探索し、byte SHAが一致する原本を選ぶ。symlinkをたどらない。画像はcrop/resize/描画/再保存しない。PNG化/復号はメモリ内のみ。

| 原画（native 1280×720） | 固定ROI xyxy |
|---|---|
| decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png | 200,0,280,720 |
| decoded_24aad0a8d31d46eeb33ef252b0d18475_f028980.png | 270,0,350,720 |
| decoded_24aad0a8d31d46eeb33ef252b0d18475_f037696.png | 270,0,350,720 |
| decoded_24aad0a8d31d46eeb33ef252b0d18475_f044793.png | 270,0,350,720 |

ROIは検出結果を見て変更しない。5186に270..350を適用した過去の案内誤りを再発させない。重複コピーがあっても同じ既知SHAを1枚ずつ使う。

見つからない場合は、必要なファイル名が列挙され、CUDA/モデル起動前に停止する。原本が別フォルダにある場合はcheckとrun両方に同じ `--search-root /絶対パス/保存フォルダ` を追加できる。この指定は標準探索を置き換えるため、必要なら複数指定する。不足を新撮影や別フレームで埋めず、まずエラー内容を確認する。

## 時間・判定の読み方

- encode_ms: PNG encode、native/profile/出力上限検査とpacket化。
- sender_prepare_ms: PNG packetの送信前検査と初片生成。**GPUPC上で実行した値**であり、matsunuc側の速度を測ったことにはならない。
- reassembly_validate_ms: 初片到着から有界再構成/packet検査。無通信で実コードを通す時間。
- decode_validate_copy_ms: 実PNG復号・画素SHA・受理期限・readonly copy。
- predict_sync_ms: CUDA同期を含む既存YOLO推論。
- support_geometry_ms: 既存の支持点/床幾何処理。
- receiver_stage_ms: packetでは**初片→幾何計算完了の実経過**。元画像では推論＋幾何の時間。packetの値にはstage間の必要なhash検査等も入る。
- full_local_pipeline_ms: 同じGPUPC内でencode開始→幾何計算完了。packetの旧共通統計名sender_encode_plus_receiver_stage_msも同じ実経過を格納し、sender_prepareを省略しない。

受理の初片200ms、payload2MiB/header8KiB/fragment16KiBを緩めない。再構成/復号までに期限を超えれば失敗summaryを残し、成功archiveを作らない。CUDA推論/幾何終了時に200msを超えた場合は診断値として記録し、receiver_first_to_geometry_within_200ms=false、集計over_200msへ計数する。**遅い診断値をライブ側へ戻す処理はない。**

元画像/PNG画像を両方とも毎回実CUDA推論し、画素は全SHA一致を必須にする。pairごとに距離差・理由・支持点・検出の差を記録する。GPU推論の差が出ても、それを隠すためにROI/HSV/幾何/manifestを変更しない。固定入力の推論反復差とPNG画素変化を区別する。

profileは既存の固定取付・平面床仮定の**未認定**profile。絶対距離真値との新比較、露光/odom源時刻・実通信/5・10Hz連続処理・運転映像共存・車体TF/接地・FFBを認定しない。candidateはoffline受理用の合成capture/no-odom fixtureで、元撮影の運動・カメラ露光を再構成していない。PC時計同期は使わない。

## 準備の検証範囲

[check.py](check.py)で解析PCの実保存4原画と実PNG経路、既存幾何を使用し、過去の保存bboxを明示的なテスト用predictorとして80測定40対を確認した。新GPU推論ではない。[synthetic_summary](verification_r01/synthetic_summary.json)と[samples](verification_r01/synthetic_samples.jsonl)はGPU結果と混同しない。元画素不変/決定論的fixtureの元判定・保留維持を確認しただけで、絶対精度を保証しない。

新21テスト: 実PNG/候補/原画不変、元/PNG双方の推論呼出し、ABBA/warmup除外、保留、変異predictor/権限拒否、期限後の受理fallback禁止/推論後期限フラグ、固定ROI、4原本探索/不足/リンク、manifest差分、重み照合、CUDA fallback禁止、出力/ログ上限、成功時だけのresult-only packとSHA/上書き拒否。旧276も再実行し計297成功。開始時HEAD894e7b4、clean。旧コード/原本/過去結果は変更せず、Git操作・実機/ネット/GPU起動なし。
