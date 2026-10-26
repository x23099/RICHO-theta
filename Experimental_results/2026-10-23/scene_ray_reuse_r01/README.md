# 同一frameのray再利用によるscene処理削減

作業日：2026-10-23。既存録画だけのオフライン開発実装。本番への適用ではない。

## 結論と対象

最初のCanny画素集合で計算した魚眼rayを、そのframeのHough候補でも再利用する。
frame間cache、画像変換、近似、補間は使わない。旧実装の平面評価・重複除外・up推定を維持する。
元の1280×720画像、本番src、校正、TF、ROS/FFB、安全機構、GPU/driverは変更していない。

固定1秒間隔の9録画492枚で、旧実装と候補の全候補行と最終up辞書の完全一致を確認した。
失敗例も含めて比較し、27枚という単画像up採用数は変わらない。これは物理的正しさの証明ではない。

16,944候補の再逆投影（延べ784,176点）を除き、各frameの最初の逆投影だけにした。
測距の初期化・保留・鮮度は変更せず、同じ入力の計算時間だけを変えた比較である。

## 定量結果

| 今回の同一PC・同一52画像・各3周 | 元実装 | 同一frame再利用 |
|---|---:|---:|
| 計測回数 | 156 | 156 |
| scene処理平均 | 265.070 ms | 150.361 ms |
| scene処理中央値 | 265.698 ms | 150.839 ms |
| scene処理p95 | 297.050 ms | 164.429 ms |
| 観測最大 | 346.130 ms | 180.119 ms |
| 完了待ち＋新入力未完了保留後の診断frame | 264/1547 | 313/1547 |

156対応ペアの速度比中央値は1.7617倍、計測順は元実装先78組・候補先78組。
中央値同士の比較で約43.2%短縮。物理距離の精度は改善していない。
再生の0コスト対照は377frameで旧結果と一致。今回の両方式ともその部分集合であり、
未完了入力中の出力は0件。処理時間だけを変えると49frame回復し、64frame分はなお0コスト対照に届かない。

前回の別計測を使った265frameとは異なり、今回の元実装対照は264frame。
再測定の時間差に伴うため、前回265と候補313を直接対応比較の結果にはしない。
全方式のscene入力の最大queue待ちは0秒だが、計算完了を待つ時間は0ではない。
約151 msは30 FPSの1frame約33 msを超える。scene処理を毎frame実行できる、という結果ではない。

新規37テストの正式結果を保存する。以前の125テストは今回再実行せず、
前回closeoutと各source/output hashを再照合して再利用する。元の失敗試行2件は失敗記録のまま保持する。

## 再現コマンド

リポジトリrootから実行する。既存出力を上書きしないため、正式保存後の同じコマンドは停止する。
再測定する場合は新しいstudy/output名で条件と出典を保持する。仮想環境の更新・実機接続は不要。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_ray_reuse_r01/run_comparison.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_ray_reuse_r01/replay_paired_costs.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_ray_reuse_r01/plot_comparison.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_ray_reuse_r01/verify_study.py
```

## 出典と結果

- [測定前に固定した条件](method.md)
- [別実装](cached_curve_geometry.py)：frame内の元indexだけを保持。入力が変われば逆投影をやり直す。
- [全492画像の比較](results_r01/equivalence.csv)／[完成結果・環境・hash](results_r01/summary.json)
- [52枚×3周×2方式の全計測](results_r01/scene_stage_measurements.csv)／[156組の対応比較](results_r01/paired_measurements.csv)
- [同じ完了待ち・保留条件での再生集計](replay_r01/replay_summary.csv)／[全query](replay_r01/frame_metrics.csv)
- [数値グラフ](report_r01/paired_cost_and_availability.png)
- [正式テスト・hash確認](verification_r01/summary.json)／[テストログ](verification_r01/test_log.txt)

## 制約・残る課題

現在のrobo25 PCでOpenCV/OpenBLAS各1thread、native PNG読取りを除くscene抽出＋up推定の測定。
従来の別測定の267 msだけを対照にせず、今回の同じ52画像で元実装と交互に測った。
元実験機のカメラ取得・YOLO・CSV・配信・FFBを含むend-to-end遅延ではない。

完了待ち対照は従来通りFIFO・scene入力1秒間隔、source時刻に対するTTL=1秒。
最新sceneが未完了なら数値を保留する。計算完了でsource時刻を更新しない。
queryごとのコーン処理時間は0とした模擬対照で、稼働FPSを示さない。
設置距離・条件ラベルは再生後の集計にだけ使い、姿勢推定・保留へ渡さない。

同値性が確認できた範囲は9録画492枚。性能比較はそのうち成功録画の52枚だけ。
真の鉛直、床接地点、物理TF、別背景や走行での一般化が未確認なのは従来と同じ。
本結果だけでコーン測距をハンコンへ接続したり、保持期限・閾値を緩めたりしない。
