# scene処理の区間別負荷診断

2026-10-23、既存画像だけのオフライン計測。元実装と全候補/upが完全一致する計測用コピーを別保存した。
本番src・画像・校正・TF/ROS・FFB・安全機構・実機・環境は変更していない。

## 結論

同じ52枚×3周で最も重いのはbin内の画素選別で、平均49.656 ms、平均wall時間157.401 msの31.55%だった。
次はこの選別の重複走査を減らす候補が優先となる。SVDやup推定が全体の大部分を占めるという結果ではなかった。

| 計測区間 | 平均ms | 平均wallに対する割合 |
|---|---:|---:|
| bin内での実画素選別 | 49.656 | 31.55% |
| 逆投影・角度制限・座標準備 | 32.390 | 20.58% |
| Hough | 20.039 | 12.73% |
| gap分割・形状条件 | 11.876 | 7.55% |
| 平面評価 | 11.750 | 7.46% |
| 候補への点距離/index | 10.361 | 6.58% |
| up推定・法線準備 | 8.273 | 5.26% |
| Canny等の画素準備 | 5.710 | 3.63% |
| 平面の重複票除外 | 4.886 | 3.10% |
| 候補行の組立て | 0.825 | 0.52% |
| 区間外・計測集計等の残差 | 1.636 | 1.04% |

区間は重複せず、各行の区間合計＋残差がwallに一致する。中央値を足した値ではない。
計測なし中央値155.733 ms、計測あり157.159 ms。
156対応ペアの増分中央値1.288 ms、比中央値1.00887（約0.89%増）だった。
計測なしのライブ時間としてこの内訳をそのまま扱わない。

全9録画978枚を1周で診断し、前回の全候補/up hashと完全一致。
その後、同一姿勢録画の1秒格子52枚を各3周、計測なし先78組・計測あり先78組で比較した。
全9録画の1周集計と、成功録画52枚の3周集計を別母集団として保存する。
新規20テストを用意し、元の27テストは変更のないsource/output hashで再利用する。
初回の図生成は保存先directoryの作成漏れで最初の保存前に停止した。
計測結果には影響せず、出力先を明示作成する修正後に正式生成・検証した。

ここでは高速化を実装したとは主張しない。仮に選別処理を0 msにしても他区間は約107.75 ms残るので、
この区間だけで30 FPSへ到達するという予測もできない。実装した短縮率は別の対応測定で確認する必要がある。

## 保存物

- [測定前に固定した条件](method.md)
- [計測用コピー](profile_curve.py)／[実行スクリプト](run_profile.py)
- [全978画像の区間別計測](results_r01/all_image_profile.csv)
- [52枚×3周の計測なし/あり対応比較](results_r01/paired_measurements.csv)
- [区間別集計](results_r01/stage_summary.csv)／[出典・環境・完成結果](results_r01/summary.json)
- [時間内訳と計測増分の図](report_r01/scene_stage_budget_and_instrumentation.png)
- [9録画それぞれの内訳](report_r01/all_recordings_stage_budget.png)
- [正式検証](verification_r01/summary.json)／[テストログ](verification_r01/test_log.txt)

## 再現

完成済み出力は上書きしない。リポジトリrootから、新しい出力版で測定する場合に使う。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_stage_profile_r01/run_profile.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_stage_profile_r01/plot_profile.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_stage_profile_r01/verify_profile.py
```

PNG読取り・hash確認・JSON/hash出力・CSV保存は計時外。現在PCで各1threadのscene処理のみの測定。
元カメラ取得、YOLO、配信、実機adapter、ハンコンを含むend-to-endの遅延測定ではない。
距離の物理的正しさやFFBへの昇格を認定しない。
