# カメラなし：保存8画像を実CUDA YOLOへ通す試験

2026-11-11。前回のGPU PC試験は保存済み検出枠による再生で成功済み。**今回は保存画像から毎回新しくYOLO推論し、比較worker OFF/ONの主判定と処理時間を比べる。** matunuc、カメラ、映像送信、ROS、ハンコン、機体走行、画面録画は不要。運転用runtimeは変更しない。

## このPCでの確認

新規22テストは全て成功（failure/error/skip=0）。正式記録は `checks_r02/summary.json`・`tests.log`、r01は再生IDの比較除外を補強する前の履歴。合成predictor＋実比較threadによるABBA試験、元画素不変、参照の再生専用binding、失敗／鮮度／重みSHA／出力上書き防止等を確認。既存198テストは対象ソースSHAを照合して成功記録を再利用し、再実行数に足さない。

実8画像の事前照合は `recordings/2026-11-11/guarded_cuda_preflight_r02/summary.json`。PNG／sidecar／元ログ・profile/config・カメラ候補等を確認し、元入力を変更していない。**このPCで実YOLO／CUDA推論は実施していない。GPU PCでの性能結果は未取得。**

## 1. GPU PCへ新しい試験ファイルだけ反映

このPCの次の2ファイルを、普段の方法でGPU PCのDownloadsへコピーする。

- `recordings/2026-11-11/guarded_cuda_update_r01.patch`
- `recordings/2026-11-11/guarded_cuda_update_r01.manifest.json`

以前の13ファイル用 `guarded_async_update_r02.patch` は再適用しない。本試験はまだcommit/pushしていないので、`git pull`だけで入るとは限らない。

GPU PCで、他のYOLO学習・受信・同GPUを使う処理を通常の方法で終了してから：

```bash
cd ~/yopi_ws/RICHO-theta
git status --short
sha256sum "$HOME/Downloads/guarded_cuda_update_r01.patch"
```

SHAをmanifestの `patch_sha256` と照合し、同じなら：

```bash
git apply --check "$HOME/Downloads/guarded_cuda_update_r01.patch"
```

成功した場合だけ：

```bash
git apply "$HOME/Downloads/guarded_cuda_update_r01.patch"
```

既に同じファイルがある／エラーなら適用を止め、エラーと `git status --short` を共有する。独自変更の強制上書き、環境の再インストール、過去試験のやり直しはしない。

## 2. GPU PCで1コマンド実行

前回GPU試験で使った元ログ・自動保存画像・重みをそのまま使う。下記のパスが見つからなければ、新しく録画せずパスを確認する。引用符は半角の `"` を使う。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"

"$THETA_DISTANCE_PYTHON" Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/motion_withheld_20261110_171250 \
  --weights "$HOME/Downloads/cone_distance_v03.pt" \
  --output-dir recordings/2026-11-11/guarded_cuda_gpu_r01 \
  --experimental-rigid-mount
```

上記の出力先が既にある場合は、新しい `guarded_cuda_gpu_r02` 等へ変更し、圧縮時も同じ名前にする。過去の結果は削除・上書きしない。

モデル初期化1回・warmup8回・setup4回は別記録。測定は **OFF→ON→ON→OFF、各160回、合計640推論**。8枚を20周ずつ繰返し、上限30回/秒、遅れを取り戻す連続投入はしない。標準測定は約22秒＋事前照合／モデル起動／setup時間。測定とsetupには180秒の上限がある（モデル初期化・事前照合はこの上限の外）。進捗はblockごとに出る。画面ウィンドウが出ないのは正常。

ON blockでは同じ元画素を別の再生sessionでpin/loadする。**このbindingは保存画像試験専用で、新しい実カメラsessionへ過去参照を転用する操作ではない。**

完了時は `state=complete`、`actual_cuda_inference=true`、`actual_camera=false`。CUDAなし・重み不一致・入力不備・比較worker失敗等では停止し、保存枠やCPUへ黙って切り替えない。出力が作られた後の失敗は `summary.json` に残る。失敗時はエラーと生成されたsummaryを共有し、何度も再起動しない。

## 3. フォルダ全体を提出

GPU PCで、上の処理が正常終了してから：

```bash
cd ~/yopi_ws/RICHO-theta
tar -cJf "$HOME/Downloads/guarded_cuda_gpu_r01.tar.xz" \
  -C recordings/2026-11-11 guarded_cuda_gpu_r01
```

同名archiveが既にある場合は別名にする。`guarded_cuda_gpu_r01.tar.xz` をこのPCへ持ってきて提出する。summaryだけでなく各blockの主JSONL、比較JSONL、pin PNG／JSON、状態／参照を一緒に確認するため、フォルダを分割しなくてよい。重みや元16929行のログを再添付する必要はない。

## 結果の見方と限界

- `primary_changed_pairs` と `detector_changed_pairs`：対応する320組のOFF/ON一致確認。比較対象から除くのは時刻／sessionと、検出枠の `image` に入る再生IDのみ。座標・confidence・順序は保持し、生ログは省略しない。新YOLOの枠が過去の保存枠と違っても、それだけで失敗とはしない。
- `groups.off/on`：predictor／主処理／ログ＋tapのwall時間P50/P95、開始間隔、33.3 ms超過数。CUDA kernelだけの時間でも、通信を含む実映像遅延でもない。setup/warmupは分布から除外。
- ON各block：比較数値・参照有効行・理由別件数、最新待ちslotの上書き、tap受付失敗、writer終了を確認。主判定が全て保留でも、それだけで実行失敗ではない。
- 変動があってもGPU非決定性や温度・負荷等を切り分ける必要があり、比較workerだけが原因と断定しない。ABBAは順序影響を減らす工夫で、完全な排除ではない。

8枚は元の保留から選ばれた小標本で、自然な連続動画・全場面・定常高負荷を代表しない。実測誤差、走行中の姿勢変化、通信・表示・操縦の総遅延は確認できない。距離はカメラ直下基準の水平距離であり、車体中心／base_link／接地距離ではない。比較値は主表示・ROS・FFB・制御へ接続しない。

本試験が通った後、初めてmatunuc＋現在カメラでの静止実映像負荷確認が次段階となる。現時点では追加撮影や新しい寸法測定は依頼しない。
