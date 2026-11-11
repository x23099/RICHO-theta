# 間引かずに不要な光線逆算を削減：GPU r04の確認手順

2026-11-11。GPU r03では比較ONが26.54件/秒で、30件/秒の維持は未確認だった。[単純な比較頻度制限](../guarded_cadence_r01/README.md)は保存データで比較数値の機会を落とすため今回は採用せず、結果を変えない重複計算の削減を続けた。

**今回はフレーム・比較の頻度を落とさない。** bbox中心・角・拡張範囲が校正の有効域内かを調べる際、これまで捨てていた光線方向の64回反復逆算を省いた。`unproject` 前半の型・native画像サイズ・有限値・ROI・最大半径チェックを共通化し、`pixels_in_domain` は同じbool配列だけを返す。距離計算で実際に必要な光線は、従来どおり64回・同じ式で求める。

## 変更範囲と維持条件

- runtimeは `angular_fisheye_geometry.py`、`cone_distance_core.py`、`cone_colour_support_candidate.py`、`cone_support_completion_candidate.py`、`cone_upper_support_candidate.py` の5ファイル。共有観測部を通る主測距にも同じ意味の軽量化が効くが、距離式・主判定を変更するものではない。
- 閾値、bboxの丸め、床法線、校正、最大角、500ms鮮度、参照pin/load/失効、自己領域棄却、主行との再現照合は維持。近似・lookup・前フレームキャッシュ・間引き・thread数変更なし。
- 主表示・操縦・ROS・FFBへ比較値は接続しない。制御権限flagsはすべてfalseのまま。実走行での姿勢変化補正や物理精度の認定は別問題。
- GPU試験スクリプトには、今回の依存 `cone_colour_support_candidate.py` のSHA記録を1行追加した。推論・測定・周期の処理は変えていない。次回は依存コードの照合対象が24→25になる。

## このPCでの検証

| 項目 | 結果 |
|---|---:|
| 関連回帰・新規の有効域／境界テスト | 404成功、failure/error/skip=0 |
| 固定した変更前の式とのray／bool比較 | 2校正の乱数・ROI端・最大半径前後・空配列等でbit単位一致 |
| 元8画像のbaseline・proposal・理由・権限flags | 8/8完全一致 |
| CPU比較カーネルP50（逆算reference→bool専用） | 49.14→33.15 ms（32.5%短縮） |
| 同P95 | 63.98→48.62 ms |
| 同最大値 | 72.27→70.33 ms |
| 8画像のunproject呼出し | 61→1（必要な距離算出1回は維持） |
| 同radial呼出し | 3965→125 |
| GPU r03提出済み比較行を新runtimeで再計算 | 320/320一致、数値40行も同一 |
| 実子・pipe・比較threadでの元8画像再生 | 主8/8一致、比較1数値1.142471541888944m |
| 別session拒否、元画素不変、writer正常終了 | 確認済み |

正式記録は `checks_r01/summary.json`・tests.log、`bench_r01/summary.json`・timing.csv、`gpu_rows_replay_r01/summary.json`、`pipe_replay_r01/summary.json`。404成功後の測定メタデータ1行追加について、影響するCUDA試験の22テストだけを再実行し `checks_metadata_r01/` に記録した。404と22を別個の426テストとは数えない。

CPU測定は逆算reference→bool専用→bool専用→逆算referenceのABBA、各64回、warmup各8回とcProfileは測定分布から除外。既存compact・同一フレーム観測共有は両条件で有効。referenceは単独のオフライン計測プロセス内で4呼出し先だけを `unproject(...)[1]` に差し替える。元画像・元主ログ・入力SHA不変を確認した。runtimeにこの差し替えは入れない。

GPU提出行再現は模擬時計による意味の一致確認で、性能測定ではない。40数値は元14922の反復で、40地点の正解距離ではない。実子再生の終了status内の別sessionのFileNotFoundErrorは意図した拒否試験で、通常処理の失敗ではない。

**CPUの短縮率をGPU性能や通信／表示遅延に換算しない。** このPCでCUDA・カメラ・ROS・機体は起動しておらず、30件/秒の維持は次のGPU確認待ち。既存の床・高さ・取付固定の条件も緩めていない。

## 次にGPU PCで行うこと（カメラ不要）

matunuc、映像送信、ROS、走行、画面録画は不要。r01〜r03を保持し、今回の変更後だけを新しいr04へ保存する。GPUの他の重い処理は普段の方法で終了しておく。

### 1. 今回の10ファイル限定更新を反映

このPCの次の2ファイルをGPU PCのDownloadsへコピーする。

- `recordings/2026-11-11/guarded_domain_update_r01.patch`
- `recordings/2026-11-11/guarded_domain_update_r01.manifest.json`

旧compact／compute_reuse／asyncパッチは再適用しない。今回も日報・commit/pushは未依頼なので行っていない。ユーザーがGit経由で同じ更新を反映済みならパッチは重ねない。

以下はスマート引用符によるエラーを避けるため、既知のGPU絶対パスを引用符なしで記す。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
git status --short
sha256sum /home/hsr/Downloads/guarded_domain_update_r01.patch
git apply --reverse --check /home/hsr/Downloads/guarded_domain_update_r01.patch
```

SHAをmanifestの `patch_sha256` と照合する。**最後のreverseチェックがエラーなく戻ったら反映済み。`git apply` は実行せず手順2へ進む。** `--reverse` は必ず `--check` と一緒に使い、変更を戻さない。

reverseチェックが失敗した場合だけ正方向を確認する。

```bash
git apply --check /home/hsr/Downloads/guarded_domain_update_r01.patch
```

これがエラーなく戻った場合だけ適用する。

```bash
git apply /home/hsr/Downloads/guarded_domain_update_r01.patch
```

両方向とも失敗なら強制上書きせず、エラーと `git status --short` を共有する。既存の削除・未追跡ファイルは今回のために整理しない。

### 2. 同じ保存画像CUDA試験を新規r04へ保存

```bash
cd /home/hsr/yopi_ws/RICHO-theta
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/motion_withheld_20261110_171250 \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --output-dir recordings/2026-11-11/guarded_cuda_gpu_r04 \
  --experimental-rigid-mount
```

r04が既にある場合は新しい名前へ変え、圧縮時も合わせる。比較OFF→ON→ON→OFF各160回、間引き制限なし。コード変更後の速度・主／比較判定・鮮度・終了を再検証するための試験で、未変更コードの繰返しではない。

### 3. 出力フォルダ全体を提出

同名archiveがないことを確認してから実行する。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
tar -cJf /home/hsr/Downloads/guarded_cuda_gpu_r04.tar.xz \
  -C recordings/2026-11-11 guarded_cuda_gpu_r04
```

summary、全blockの主／比較JSONL、pin PNG／sidecar、参照を含めて提出する。旧rawや重みの再送は不要。こちらで主判定・比較値の維持、ON/OFFのP50/P95・超過件数・開始間隔・比較age・正常終了を確認する。`state=complete`だけで30fps・実カメラの性能合格とはしない。

## 再現スクリプト

- `check.py`：共有観測・比較・失効・幾何の関連テスト。
- `bench.py`：元8画像のCPU ABBA、完全結果一致、元画素・入力SHA不変確認。
- `check_metadata.py`：GPU試験SHA記録追加後の影響範囲だけの回帰。
- `make_patch.py`：基準 `0576314` への正向きdry-runと現在コードへの逆向きdry-runを経て、10ファイルだけのパッチ／SHA manifestを新規作成する。重み・raw・別作業・旧監査差分を含めない。

既存の `../guarded_compute_reuse_r01/replay_gpu_rows.py` をr03 intake指定で再利用し、`../guarded_async_comparison_r01/replay.py` をnative8画像指定で再利用した。出力先は上記の新規フォルダで、既存成功結果を上書きしていない。
