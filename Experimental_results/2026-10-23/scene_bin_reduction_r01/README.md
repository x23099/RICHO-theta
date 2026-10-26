# 同じ代表画素を選ぶbin削減候補

2026-10-23、既存画像だけの開発実装。結果を変えずに計算の重複を減らす試作で、本番への反映ではない。

## 変更内容

[区間別負荷診断](../scene_stage_profile_r01/README.md)で最も重かったbin内の選別を対象にした。
従来はbinごとに候補index配列を走査して最短距離の画素を選んでいた。
native Canny画素はy/x順で、候補indexも元順を保つため、bin境界ごとにまとめて最小値を取り、
その最小値に等しい最初の元indexを選ぶ実装へ置き換えた。
近似値や許容誤差で同点を判定せず、旧argminの同点規則・bin順・画素順を保持する。

画像、幾何、ROI、候補数、平面/upの閾値、初期化、TTL、未完了保留は変更しない。
実画素を間引く、画像を縮小する、距離を補間する高速化ではない。

## r01とr02を区別する

初版r01は全978画像で一致し、中央値156.602→130.606 msの対応比較が完了した。
ただし補助関数のnp.diffによる順序検査は、unsigned逆順入力でoverflowにより拒否できないことを追加テストで再現した。
native経路の小さいsigned index/binには発生しないが、入力契約として補強する必要がある。
旧sourceと完成結果は書換えず、r02では要素同士の比較で順序を確認し、非実数distanceも拒否する。

正式候補は[guarded_curve_geometry.py](guarded_curve_geometry.py)、
時間比較の正式結果は[results_guard_r02](results_guard_r02/summary.json)とする。
r01の時間をr02の実測時間として流用しない。元の[results_r01](results_r01/summary.json)も比較履歴として保持する。

r02の最初の全画像検証は800枚を超えたところで終了コード143で中断し、完成結果は生成されなかった。
終了原因は特定しておらず、テスト失敗とは断定しない。
再実行では100枚ずつsource/spec/結果hash付きcheckpointを保存できるようにし、完成前の中断を成功扱いにしない。

## 正式r02の結果

全9録画978画像の全候補/upが旧結果と完全一致し、単画像up採用51枚も不変。
同じ成功録画の1秒格子52枚を各3周測り、元候補先78組・新候補先78組、156対応ペアを保存した。

| 今回のr02対応付き比較 | ray再利用対照 | bin削減r02 |
|---|---:|---:|
| scene中央値 | 144.028 ms | 118.128 ms |
| scene平均 | 143.013 ms | 118.547 ms |
| p95 | 154.726 ms | 129.806 ms |
| 観測最大 | 179.012 ms | 214.919 ms |
| 同じ完了待ち＋未完了入力保留後の診断frame | 313/1547 | 325/1547 |

対応ペア速度比の中央値は1.2112倍。中央値同士で約18.0%短縮。
今回の0コスト対照は377frameで旧結果と一致。現在コーン処理を0コストとした模擬再生で、12frame回復した。
未完了入力中の出力は両方式0。TTLや初期化を緩和せず、距離値を補間していない。
今回の対照313は今回の実測コストから算出した値で、以前の別測定の313を流用したものではない。

一方、観測最大時間は214.919 msとなり対照より悪化した。原因は未特定で、中央値/p95改善を最悪時間保証としない。
再生には測定3周の中央値を使ったため、この遅い1回まで含む最悪側の運用可用性を保証していない。
毎frame 30 FPS、実機遅延、物理距離精度、FFBへの昇格をこの結果から認定しない。
また、bin区間自体のr02区間計時は未実施であり、全体の短縮をそのままbin単独の測定値と呼ばない。

新規34テスト。r01のunsigned逆順の検査漏れも旧sourceを変更せず再現し、r02で拒否することを確認する。
全画像一致、500例の同点比較、型/順序/数値境界、対応測定の均衡、checkpointのspec/結果hash、
0コスト対照、TTLと未完了保留、保留時の数値非表示、物理/FFB未昇格を検証する。
区間別負荷診断の20テストはsource/output hashを確認して再利用し、今回の再実行数に重複計上しない。

## 根拠

- [比較前に固定した条件](method.md)／[r02入力検査の補強](guard_r02_method.md)
- [r02全978画像の比較](results_guard_r02/equivalence.csv)／[同じ52枚×3周の対応計測](results_guard_r02/paired_measurements.csv)
- [実測コストを使った1秒入力の再生](replay_r01/replay_summary.csv)／[全query](replay_r01/frame_metrics.csv)
- [数値グラフ](report_r01/guarded_bin_cost_and_availability.png)
- [正式検証](verification_r01/summary.json)／[テストログ](verification_r01/test_log.txt)

同点・符号付き0・空配列・非連続index/bin・極端な有限値・固定seed500例で旧選別と同じindexを返すか確認する。
順序不正、重複index、範囲外、unsigned逆順、巨大signed bin、複素distanceを含む入力チェックもテストする。
全9録画978画像は前回保存した全候補/upのhashと照合し、成功例だけに限定しない。

## 実行

リポジトリrootから実行。完成した結果は上書きしない。
r02の同値性途中checkpointはsource/specが完全一致し画像hashが変わらない場合だけ再利用する。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_bin_reduction_r01/run_fast_guarded.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_bin_reduction_r01/replay_fast.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_bin_reduction_r01/plot_fast.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_bin_reduction_r01/verify_fast.py
```

## 制約

時間は現在PCの各1threadでscene抽出＋up推定のみ。画像decode/hash/保存は計時外。
再生も現在コーン処理を0コストとした同じ条件付き対照で、元実験機のライブ遅延ではない。
速度が上がっても物理TF・接地点・真の鉛直の確認にはならず、距離精度改善や30 FPSを認定しない。
本番src、ROS/TF、FFB、安全機構、実機、GPU/driver、依存環境、元画像は変更していない。
