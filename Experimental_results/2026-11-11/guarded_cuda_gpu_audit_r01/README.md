# GPU実CUDA再推論：主判定は一致、比較ONの負荷に課題

2026-11-11。提出 `guarded_cuda_gpu_r01.tar.xz` を独立照合した。**実行は正常完了し、比較OFF/ONで検出枠・主判定は320組すべて一致。ただし比較ONの30回/秒維持は、この保存画像試験では達成していない。** `state=complete` は試験の完了であり、性能合格を意味しない。実機へ進む前に、保存データで比較側の負荷対策を検討する。

開始時HEADはユーザーが整理した `84173b3`（1111v2）、worktreeはclean。本監査では運転runtime・距離判定・GPU環境を変更せず、実カメラ／ROS／車体操作・モデル起動・commit/pushを行っていない。

## 提出物と検証根拠

- 生提出物の安全な保存先：`recordings/2026-11-11/guarded_cuda_gpu_intake_r01/`。画像は元PNGをバイトのまま保存し、加工していない。
- 監査結果：[results_r01/audit.json](results_r01/audit.json)。archive・全提出ファイル・監査コードのSHAを記録。
- 主640行のタイミング：[primary_timing.csv](results_r01/primary_timing.csv)。比較322行：[comparison_timing.csv](results_r01/comparison_timing.csv)。分布はnearest-rank P50/P95。
- 元入力25ファイルをこのPCの既知パスへ対応させて再hash。重みはarchiveにないため実ファイルを再hashしたとは言わず、提出SHAが設定値と一致することを確認した。記録されたGPU PCのパスを開く処理はない。
- ベンチマーク＋依存コード24ファイルをこのPCの実ファイルと照合。GPU側のバージョン記録はRTX 4070 Laptop、torch 2.7.1+cu118、CUDA 11.8、numpy 2.2.6、opencv-python 5.0.0.93、ultralytics 8.4.175。環境全体・GPUカーネルをこのPCで直接監査したわけではない。

## 判定・画素・終了

| 項目 | 照合結果 |
|---|---:|
| 実YOLOの測定対象画像呼出し | 640回（各block160回） |
| setup／warmup（測定分布から除外） | 4回／8回 |
| OFF/ONの検出枠・主判定の一致 | 320/320組 |
| 元画素＋新しい検出枠によるCPU下流再計算 | 異なる8入力ケースを再現、全640行の署名に照合 |
| 主距離数値 | 0/640（全件 `colour_contour_reaches_roi_edge`） |
| 比較ログの直接照合 | 322行（setup2＋測定320） |
| 比較距離数値 | 40行、全て元frame14922の繰返し、1.142471541888944 m |
| ON側の参照有効な測定行 | 320/320 |
| pin画素 | 両blockとも元frame14604と一致 |
| 比較slot上書き／tap受付失敗 | 両blockとも0／0 |
| 比較writer終了 | 両blockとも正常、errorなし |

8枚はもともと保留から選んだ標本であり、主距離が0件なのは新しい故障の証拠ではない。また40行は同じ1画像を反復した結果で、40地点で距離精度を検証した意味ではない。検出枠そのものの正解を独立測定したものでもない。

比較はON各blockで、setup1保留＋測定中の輪郭境界60保留＋自己領域80保留＋数値20。時刻・主ログ行・参照JSON・pin PNG／sidecar・元画素の対応を確認した。参照は保存画像専用の再生sessionへbindingしたもので、新しい実カメラsessionへの転用許可ではない。比較数値は主表示・ROS・FFB・制御へ接続していない。

## 性能：改善が必要

| 測定値 | 比較OFF | 比較ON |
|---|---:|---:|
| YOLO呼出しwall P50 | 6.82 ms | 27.27 ms |
| YOLO呼出しwall P95 | 8.39 ms | 41.85 ms |
| 主処理wall P50 | 22.69 ms | 45.69 ms |
| 主処理wall P95 | 27.07 ms | 67.23 ms |
| 主処理＋ログ＋tap P95 | 27.51 ms | 68.12 ms |
| 測定blockの処理件数/経過秒 | 29.58件/秒 | 20.05件/秒 |
| 主処理33.33 ms超過 | 3/320（0.94%） | 201/320（62.81%） |

OFF→ON→ON→OFFの主処理P95は順に27.07／67.64／67.03／26.86 msで、両ON blockが遅く、最後のOFFで戻っている。ONとの関連は強いが、温度・CPU負荷・GIL・OpenCV thread競合・メモリ帯域等を個別に計測していないため、どれか一つを確定原因とはしない。

tap自体のP95は0.033 ms（最大0.073 ms）。「非同期だから主処理への影響はない」とは言えず、同じプロセスでの資源共有・比較側の仕事量を監査する必要がある。比較service P50/P95は43.59／64.45 ms、模擬入力時刻から比較完了までのP50/P95は93.74／177.46 ms、最大199.33 ms。全行は既存500 ms鮮度範囲内だが、それだけで30回/秒の応答を満たすことにはならない。

件数/秒は各条件の測定320件÷2 block経過秒の合計から算出した。ライブの受信FPSや操縦遅延ではない。主処理時間はYOLO呼出し＋支持範囲抽出／幾何のwall時間であり、GPU kernelだけの時間ではない。warmup初回には約1451 ms、モデル初期化には約2951 msかかっているが、上表から除外済み。

## 次に行うこと

1. カメラなしで、比較側の再計算重複・CPU処理箇所を保存画像で調べる。`GuardedStreamComparison.compare` は比較観測とbaseline再現を行い、主経路と資源を共有している。変更前に処理内訳を計測し、原因を限定する。
2. 主判定・主入力の鮮度を維持する範囲で、比較側の仕事量／実行頻度／分離方法の候補を検証する。判定緩和、画像変更、過去値保持、CPUへのYOLO fallbackで速くしない。今回の段階で運転runtimeへ対策を実装したわけではない。
3. 対策をローカルで検証した後、必要な変更だけをGPU PCへ渡して同条件で再確認する。今回と同じ未変更コードの再実行、追加撮影、寸法測定は今は不要。
4. 負荷対策後にmatunuc＋現在カメラの静止実映像を確認する。実測精度、通信／表示込み遅延、姿勢変化、現地監視下の走行評価はこの保存画像試験と別に残る。

## 再現

出力先は存在しない新しい名前へ変更する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01/audit.py \
  --archive /home/robo25/Downloads/guarded_cuda_gpu_r01.tar.xz \
  --intake-dir recordings/2026-11-11/guarded_cuda_gpu_intake_r02 \
  --output-dir Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01/results_r02
```

監査用の新規9テストは全て成功（failure/error/skip=0）。[checks_r01/summary.json](checks_r01/summary.json)とtests.logに記録。パス逸脱・link／FIFO・重複・サイズ上限・不完全／非有限JSON・主行の時刻／ID／権限改変を拒否する。既存の22／198テストを今回再実行したとは数えない。
