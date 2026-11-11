# 比較側の二重抽出を除去：GPU PCで速度の再確認へ

> 後続更新：[二重抽出削減後のGPU提出結果](../guarded_cuda_gpu_audit_r02/README.md)を照合済み。前回との主判定640行・比較322行を維持し、比較ONは約20.0→23.9件/秒へ改善。ただし30件/秒は未達。下記の更新反映・r02実行は完了した手順の保存であり、再適用・同じ試験の再実行は不要。次は追加撮影なしで残る負荷を検討する。

2026-11-11。[前回のGPU実CUDA結果](../guarded_cuda_gpu_audit_r01/README.md)は主判定320組一致・正常終了だったが、比較ON時に約20件/秒へ低下した。今回は**比較側が同じ現在フレームの観測を2回抽出する重複だけを除去**した。カメラ・機体・ROS・CUDAをこのPCから起動していない。まだcommit/pushしていない。

## 変更と検証

`GuardedStreamComparison.compare` で比較関数が元画素から新しく得たbaseline観測を、同じフレームのbaseline距離計算にも渡す。元の主ログの観測や過去フレームは使わない。`MotionRangeEngine.measure` の呼出し単位のobserverを利用し、主測距の既存呼出しは従来どおり。engineのobserver属性を一時変更せず、frame順序・鮮度・box選択・幾何・主行との再現照合を残す。参照のpin/load/失効、自己領域棄却、既定OFF、主表示・ROS・FFBへの未接続は維持する。

| 検証 | 結果 |
|---|---:|
| CPU計算候補の元8ケースのbaseline／proposal／理由／flags | 8/8完全一致 |
| 元8ケース1周の上側補完観測呼出し数（cProfile） | 16→8回 |
| このPCの比較計算P50（旧／共有候補） | 103.88→61.78 ms（約40.5%短縮） |
| 同P95 | 127.41→78.57 ms |
| 接続後の関連テスト（今回再実行） | 276成功、failure/error/skip=0 |
| 新runtimeでGPU提出の測定比較行を再計算 | 320/320一致、数値40行も同一 |
| 元8画像の実子・pipe・比較thread再生 | 主結果8/8一致、比較数値1行1.142471541888944m |
| 上記の別session参照拒否／元画素不変／終了 | 確認済み |

正式記録は `profile_r02/summary.json`・`timing.csv`、`checks_runtime_r01/summary.json`・`tests.log`、`gpu_rows_replay_r01/summary.json`、`pipe_replay_r01/summary.json`。`profile_r01` は候補内の不要な観測コピーを除く前、`checks_r01` はruntime接続前の14新規テスト＋198テストSHA再利用の履歴。正式276は再利用を足した数ではなく実際の再実行数で、14を別に加算しない。

CPU測定は旧→共有→共有→旧の4 block、各64回、blockごとのwarmup8回を除外。8枚を反復する独立した録画後比較カーネルのwall時間で、GPU PCの処理速度改善や30fps達成を証明しない。cProfileには深い辞書コピーの負担も見えるが、計測器のオーバーヘッドとnested cumulative timeがあるので合計して割合を断定しない。

320行のruntime再計算はGPU提出の検出枠・元画素を使用し、時刻は保存された値を模擬時計で再生した。新しいYOLO推論・実時間性能・実カメラ参照の成立を示すものではない。原画像は加工・描画していない。

## 次にGPU PCで行うこと

今回の変更を反映して、前回と同じCUDA試験を新しい出力先で1回行う。今回はコード変更があるため必要な再試験であり、前回と同じ未変更コードの繰返しではない。**matunuc・カメラ・送受信・ROS・走行・画面録画・チェックボードは不要。** GPUの他の重い処理は通常の方法で終了しておく。

### 1. 今回の2ファイルをGPU PCのDownloadsへコピー

- `recordings/2026-11-11/guarded_compute_reuse_update_r01.patch`
- `recordings/2026-11-11/guarded_compute_reuse_update_r01.manifest.json`

以前の `guarded_async_update_r02.patch`／`guarded_cuda_update_r01.patch` は再適用しない。manifestは対象6ファイル・SHA・基準commitを記録。runtime2ファイルと新規テスト／資料だけで、重み・生データ・別作業は含まない。

GPU PCで：

```bash
cd ~/yopi_ws/RICHO-theta
git status --short
sha256sum "$HOME/Downloads/guarded_compute_reuse_update_r01.patch"
```

SHAをmanifestの `patch_sha256` と照合し、同じなら：

```bash
git apply --check "$HOME/Downloads/guarded_compute_reuse_update_r01.patch"
```

成功した場合だけ：

```bash
git apply "$HOME/Downloads/guarded_compute_reuse_update_r01.patch"
```

既に同じ更新がある場合、チェックに失敗した場合、別作業と衝突した場合は再適用・強制上書きをせず、エラーと `git status --short` を共有する。パッチを使う代わりにGit経由で反映済みなら、同じパッチを重ねない。

### 2. 保存画像による実CUDA試験

出力先だけを前回の `guarded_cuda_gpu_r01` から `r02` へ変更する。既にr02があれば新しいr03等を使い、圧縮時も同じ名前にする。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"

"$THETA_DISTANCE_PYTHON" Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/motion_withheld_20261110_171250 \
  --weights "$HOME/Downloads/cone_distance_v03.pt" \
  --output-dir recordings/2026-11-11/guarded_cuda_gpu_r02 \
  --experimental-rigid-mount
```

モデル初期化・warmup後、比較OFF→ON→ON→OFF、各160回。完了後の `state=complete` だけで性能合格とはしない。ON時の主処理P50/P95・開始間隔・33.33ms超過数、比較鮮度／終了、検出枠・主判定一致をこちらで確認する。失敗時は黙ってCPUや保存枠へ切り替えず、エラーと出力されたsummaryを共有する。環境の再インストールはしない。

### 3. 完了後、出力フォルダ全体を圧縮して提出

```bash
cd ~/yopi_ws/RICHO-theta
tar -cJf "$HOME/Downloads/guarded_cuda_gpu_r02.tar.xz" \
  -C recordings/2026-11-11 guarded_cuda_gpu_r02
```

同名archiveがあれば別名にする。主／比較JSONL・pin・参照・summaryを含むarchiveを提出する。前回結果r01は残す。

今回の削減だけでGPU PCの30回/秒が回復するかは未確認。十分でなければ、その結果を基にコピーの仕事量・比較頻度・資源分離を判断する。物理精度や通信・表示・操縦込みの遅延は引き続き別の検証であり、カメラ撮影を先に増やさない。
