# 2026-11-11 日報の代表資料3点

| 資料 | 内容・出典 |
|---|---|
| [gpu_primary_p95.png](gpu_primary_p95.png) | 実CUDA保存画像試験r01〜r04の、比較OFF/ON時の主処理P95。30fps相当の33.33msを参考線として併記。実カメラの性能認定ではない。 |
| [gpu_throughput.png](gpu_throughput.png) | 同じ4回の測定block件数÷経過秒。上限30回/秒、条件ごと320行、warmupは除外。 |
| [decoded_4c34c8c3d6d44949afb2e921e819e563_f014922.png](decoded_4c34c8c3d6d44949afb2e921e819e563_f014922.png) | 試験8画像のうち、比較値約1.14247mが得られた元14922。11/10撮影の無加工1280×720 PNGを原バイトのまま複製。画像上には数値を追加していない。独立した正解距離の証拠ではない。 |

グラフ根拠は [gpu_performance.csv](gpu_performance.csv)。4回の監査JSON `../guarded_cuda_gpu_audit_r01`〜`r04/results_r01/audit.json` から抽出した。各runは同じ8画像の反復で、別々の40地点を測った試験ではない。主処理P95・処理速度・実通信遅延を混同しない。

元PNGの保存先は `recordings/2026-11-10/driver_motion_171250_intake_r01/motion_withheld_20261110_171250/`。session `4c34c8c3d6d44949afb2e921e819e563`、frame14922、media_time_sec=497.3734。撮影時刻は11/10の元録画内時刻で、本日の新規撮影ではない。PNG SHA、復号BGR SHA、sidecar／indexとの照合、生成コード・入力・出力のSHAは [manifest.json](manifest.json) に記録する。

本日matunuc／カメラは使用不可。画像に注釈・合成・切抜き・リサイズ・色補正は行っていない。グラフだけを新規生成した。raw画像群や重み・venvはGit対象にしない。

再生成は既存の結果を上書きせず、未使用の出力先で行う。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-11/report_assets/build.py \
  --output-dir Experimental_results/2026-11-11/report_assets_repeat
```
