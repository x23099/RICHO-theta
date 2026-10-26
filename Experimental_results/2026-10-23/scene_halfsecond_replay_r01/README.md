# 既存動画のscene観測を0.5秒間隔へ細かくした対照

作業日：2026-10-23。追加録画・本番変更・実機駆動なしのオフライン診断。

## 何を比較したか

元の9録画・14,526frameから、従来と同じ最初のCSV時刻を基点に0.5秒ごとで最初に到達するframeを選んだ。
全978枚は元の1秒間隔492枚を含み、新規486枚だけを無加工PNGへ保存した。
画像は1280×720全画角。元492枚は旧PNGを再利用し、raw decodeとの画素一致/hashを確認した。
新PNGはGit対象外の`recordings/2026-10-23_scene_halfsecond_r01/`へ保存した。
選択planをscene解析より先に固定し、採否・距離誤差・コーンの有無でframeを選ばない。

幾何・sceneアルゴリズムは前回の[同frame ray再利用](../scene_ray_reuse_r01/README.md)と同じ。
画像の意味や採否を変える方式ではなく、入力時刻の密度だけを変えた比較である。
初期化、ROI、閾値、TTL=1秒、FIFO完了待ち、新入力処理中の保留、現在画像の品質条件は変更しない。
間隔1秒/0.5秒 × コスト0/実測3周中央値の4条件で、失敗側も含む全9録画を保持する。

## 結果・根拠

**現在の処理コストと保留条件では、0.5秒への一律高頻度化は採用しない。**
初期化は早まるが、処理中の保留が増えて、全体の診断frameは減少した。
保留条件やTTLを緩めて改善扱いにはしない。

| 4条件の比較 | 1秒間隔 | 0.5秒間隔 |
|---|---:|---:|
| 入力画像数（9録画） | 492 | 978 |
| 単画像up採用数 | 27 | 51 |
| コスト0で初期化した録画 | 1/9 | 3/9 |
| 実測コストで初期化した録画 | 1/9 | 2/9 |
| コスト0での診断frame（8録画6,876query） | 377 | 413 |
| 実測コスト＋未完了保留後の診断frame | 304 | 260 |
| 同一姿勢録画だけの実測コスト後診断frame | 304/1547 | 242/1547 |
| 同一姿勢録画で新入力処理中のquery | 280/1547 | 558/1547 |
| 同一姿勢録画で保留制御が除いた診断候補 | 6 | 143 |

計算コスト0なら全体で36frame増えるが、実測コストでは44frame減る。
同一姿勢録画だけでは62frame減り、0.80 m静止録画で新たに18frame出るので全体260frameになる。
同じコーンframeに両方式が出力する186frameでは、Z差の絶対最大は約2.65 mm。
これは新しい初期化で選ばれた2枚が変わるためで、物理距離精度が向上した意味ではない。

同一姿勢録画の初期化sourceは開始10.0265秒後→3.5256秒後。
使う4枚のsource時刻幅は8.0020秒→3.0000秒に短縮し、最小間隔も1.0013秒→0.4996秒となった。
早期の床だけの区間で初期化できるが、そこにはコーンがなく、早さがそのまま測距可用性の増加にはならない。
0.80 m録画の初期化は開始21.5197秒後と遅く、18frameの出力を録画全体の安定動作と呼ばない。
コーンなし録画は0コスト時のみ録画最終frameで初期化し、実測コストでは完了が録画終了後となるので数えない。

1秒と0.5秒の共通画像には今回の全く同じコストを与えた。
今回の1秒対照304frameは前回の別測定313frameとは異なるため、313対260をこの間隔比較の数値にはしない。
同一姿勢録画の今回scene中央値は162.757 ms（全画像3周）、p95は190.718 ms。
両間隔とも最大queue待ちは0秒だが、処理完了待ちと保留は0ではない。

全978画像を3周（2,934回）計測し、各画像の候補/upのhashは3回とも一致。
共通492枚の旧結果との差0、旧1秒/0コスト対照の6,876queryの差0。
新規27テストで、元画素/hash、時刻格子、未来情報の改変・切断に対するprefix不変、
ラベル除去、終了後の未完了入力を数えないこと、TTL、未完了保留、数値非表示を確認した。

- [解析前に固定した比較条件](method.md)
- [抽出plan](intake_r01/sampling_plan.json)／[native画像・元動画hash](intake_r01/native_sample_manifest.csv)
- [全画像のscene診断](scene_results_r01/image_diagnostics.csv)／[3周すべての処理時間](scene_results_r01/scene_stage_measurements.csv)
- [scene結果集計](scene_results_r01/summary.json)
- [録画別の初期化・出力・保留](replay_r01/session_summary.csv)／[初期化の4枚と時間幅](replay_r01/initialization_evidence.csv)
- [全queryの結果](replay_r01/frame_metrics.csv)／[同じframe同士の比較](replay_r01/matched_frame_comparison.csv)
- [条件別距離](replay_r01/condition_summary.csv)／[再生集計](replay_r01/summary.json)
- [全録画の比較グラフ](report_r01/all_recordings_cadence_comparison.png)／[同一録画の時間軸](report_r01/same_capture_cadence_timeline.png)
- [新規テスト・出典検証](verification_r01/summary.json)／[テストログ](verification_r01/test_log.txt)

## 実行方法

リポジトリrootで実行する。完成済み出力は上書きしない。
中断時のscene処理は同じsource/hashの完了session checkpointだけ再利用できる。
未完成sessionを削除して成功扱いにせず、そのまま保持して別output版へ進む。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_halfsecond_replay_r01/prepare_dense.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_halfsecond_replay_r01/analyze_dense.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_halfsecond_replay_r01/replay_dense.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_halfsecond_replay_r01/plot_dense.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-23/scene_halfsecond_replay_r01/verify_dense.py
```

## 制約

- 4枚という初期化条件を維持しても、より短い時間に集まる4枚は独立の物理証拠ではない。
  初期化までの時間短縮と、姿勢の物理的正しさ・時間的独立性を区別する。
- この方式は姿勢根拠に乏しい録画を成功にするfallbackではない。別録画のupを流用しない。
- 共通画像には同じ計測コストを使う。別runの負荷差と入力密度の効果を混同しない。
- 計時はnative PNG読取り後のscene抽出＋up推定だけ。毎回のコーン処理は0コストのまま。
  元カメラの取得/配信/保存、実機adapterやFFBを含むend-to-end再現ではない。
- source時刻と完了時刻は区別し、完了で鮮度を若返らせない。録画終了後に完成する入力で初期化を数えない。
- コーン観測があるのは8録画6,876frame。紙だけの録画には姿勢の初期化監査だけを行い、距離を作らない。
- コーン条件・設置距離・役割ラベルはゲート入力から明示的に取り除き、集計時だけ付ける。
- 物理TF、真の鉛直、床接地点、別背景/走行の一般化は未検証のまま。本番src・ROS/TF・FFB・安全機構は変更しない。

## 次に残る作業

入力をさらに細かく探索する前に、1秒間隔を対照として残し、
scene処理内のHough候補整理・平面/上方向推定などの区間別負荷を測る。
出力を増やすために未完了入力の保留を外したり、4画像を独立した物理根拠と扱ったりしない。
追加録画が必要な物理情報と、計算量の問題は分けたまま進める。
