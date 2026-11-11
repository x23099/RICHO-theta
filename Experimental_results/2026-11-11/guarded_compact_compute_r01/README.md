# 比較worker内だけの診断コピー削減

2026-11-11。前回GPU r02は比較ONで23.86件/秒、主処理P95=55.59msだった。今回は同一フレーム内の診断コピー削減に限定した。比較頻度・thread数・process配置・主測距・鮮度条件・棄却条件は変更していない。

## 変更内容

- 通常の比較APIは、既定では今までどおり独立したdeepcopyと両bbox policyを返す。旧解析の診断結果・所有権は維持する。
- 比較streamだけが明示する `compact=True` では、実際に使うhalf-pixel policyだけを作る。毎回元画素から新規抽出した一時診断graphを同一呼出し内で共有し、使わない入れ子の深いコピーを省く。
- point/support/reasonの棄却書換えは別top-level dictに限定。主ログの観測や前フレームを借用せず、呼出し間キャッシュも設けない。
- engineの結果コピー、streamが返す結果のコピー、参照pin/load/失効、500ms鮮度、主行との再現照合、自己領域の棄却は維持。compact graphは比較worker内部だけで消費し、主表示・IPC・ROS・FFBへ渡さない。

変更runtimeは `cone_bbox_boundary_shadow.py`、`cone_self_body_shadow.py`、`cone_guarded_lower_edge_shadow.py`、`cone_guarded_stream_comparison.py` の4ファイル。主測距の既定observerや距離の式は変更していない。

## ローカル検証

| 項目 | 結果 |
|---|---:|
| 元8画像でのfull/compactのbaseline・proposal・理由・flags | 8/8完全一致 |
| CPU比較カーネルP50（full→compact） | 60.31→50.26 ms（16.7%短縮） |
| 同P95 | 74.97→61.67 ms |
| 同最大値 | 87.90→107.20 ms |
| 8ケースのdeepcopy呼出し（再帰を含む） | 128156→28794 |
| 同deepcopy外側呼出し | 589→498 |
| 元画素を新規抽出する回数 | 8→8（画像観測は省略していない） |
| 接続後の関連回帰・新規所有権テスト | 290成功、failure/error/skip=0 |
| 提出済みGPU r02の測定比較行を新runtimeで再計算 | 320/320一致、数値40行も同一 |
| 実子・pipe・比較threadによる元8画像再生 | 主8/8一致、比較1数値1.142471541888944m |
| 別session参照拒否・元画素不変・正常終了 | 確認済み |

正式記録：`bench_r01/summary.json`・`timing.csv`、`checks_r01/summary.json`・`tests.log`、`gpu_rows_replay_r01/summary.json`、`pipe_replay_r01/summary.json`。290は今回実際に実行した数で、旧276に新規14を含む。別に足し直さない。

CPU測定はfull→compact→compact→full、各64回・計256回。各block前のwarmup8回とcProfile実行はwall時間分布から除外した。カーネルは前回の同一フレーム観測共有を両条件とも有効にし、今回のcompact差だけを比較した。原画像を加工せず、主ログ・元入力SHAの不変も確認。cProfileの再帰呼出し数は独立した結果コピー数とは異なり、入れ子のcumulative timeを足して割合を断定しない。

中央値とP95は改善したが最大値は悪化した。**全フレームが速くなった証拠でも、GPU PCで30件/秒へ回復した証拠でもない。** 今回はこのPCでCPU計算を測定しただけで、実CUDA・カメラ・ROS・機体は起動していない。GPU提出行の再計算は模擬時計による意味の一致確認で、実時間性能ではない。

## 次はGPU PCで今回の変更を確認

カメラ・matunuc・映像送信・ROS・走行・画面録画は不要。GPUの他の重い処理は普段の方法で終了しておく。今回の変更はまだcommit/pushしていない。既にGit経由などで同じ更新が入っていれば、同じパッチを重ねない。

### 1. 今回のパッチとmanifestをGPU PCのDownloadsへコピー

- `recordings/2026-11-11/guarded_compact_update_r01.patch`
- `recordings/2026-11-11/guarded_compact_update_r01.manifest.json`

転送対象は今回の8ファイルだけ。以前のasync／cuda／compute_reuseパッチは再適用しない。重み・raw・別作業は含めていない。

前回のスマート引用符によるエラーを避けるため、以下はGPU PCの既知の絶対パスを引用符なしで記す。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
git status --short
sha256sum /home/hsr/Downloads/guarded_compact_update_r01.patch
```

manifestの `patch_sha256` と同じなら：

```bash
git apply --check /home/hsr/Downloads/guarded_compact_update_r01.patch
```

成功した場合だけ：

```bash
git apply /home/hsr/Downloads/guarded_compact_update_r01.patch
```

「already exists」「patch does not apply」なら再適用しない。既に入った変更かどうかは、ファイルを変更しない次のチェックで確認できる。

```bash
git apply --reverse --check /home/hsr/Downloads/guarded_compact_update_r01.patch
```

これがエラーなく戻れば反映済みで、次へ進む。`--reverse`だけで実行すると戻す操作になるため、`--check`は必ず付ける。両方向とも失敗ならエラーと `git status --short` を共有し、強制上書きしない。別作業の削除・未追跡ファイルを今回のために整理しない。

### 2. 前回と同じ実CUDA試験を新しいr03へ保存

```bash
cd /home/hsr/yopi_ws/RICHO-theta
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/motion_withheld_20261110_171250 \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --output-dir recordings/2026-11-11/guarded_cuda_gpu_r03 \
  --experimental-rigid-mount
```

r03が既にある場合は新しいr04等へ変更し、圧縮時も名前を揃える。過去r01/r02は保持する。新しいコードによる必要な再検証であり、未変更コードの繰返しではない。今回も比較OFF→ON→ON→OFF、各160回。`state=complete`だけで性能合格とはせず、主判定一致・ONのP50/P95／開始間隔／超過件数・比較鮮度・終了をこちらで照合する。

### 3. 終了後、出力フォルダ全体を提出

```bash
cd /home/hsr/yopi_ws/RICHO-theta
tar -cJf /home/hsr/Downloads/guarded_cuda_gpu_r03.tar.xz \
  -C recordings/2026-11-11 guarded_cuda_gpu_r03
```

同名archiveがあれば別名にする。summaryだけでなく主／比較JSONL、pin画像／sidecar、参照も含めたarchiveを提出する。重みや過去の大きな元ログを再添付する必要はない。

今回の削減だけで十分かはGPU PCの結果待ち。まだ余裕が不足する場合は、結果を根拠に次の処理内訳や比較頻度を検討する。距離の精度・通信／表示／操縦遅延の認定と混同せず、撮影や寸法確認を先に追加しない。
