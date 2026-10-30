# 左右枠接触の候補を比較ログへ追加・連続フレーム回帰

作業日: 2026-10-30。実機・通信・ROS・FFB・GPU推論・追加撮影・Git commit/pushは実施していない。

## 結論

前段の[左右方向の支持範囲補完候補](../cone_lateral_completion_r01/README.md)を、**明示指定した場合だけ受信側の比較ログへ記録できるようにした**。候補点から未確認の距離を新たに表示する変更ではない。

- `--support-completion-shadow`を追加。既定OFF。既存の`--colour-support-shadow`とは独立。
- `distance_frames.jsonl`の`support_completion_shadow`へ、当該フレームの候補点・支持列・補完試行/取得・保留理由を保存する。
- 選択した同一フレームの実YOLO枠も保存する。過去の点を欠測フレームへ持ち越さない。
- 標準の`report`コマンドは、候補点と追加取得を従来の距離件数から分けて集計する。
- 元の輪郭・品質判定・姿勢・校正・幾何・鮮度条件は変更しない。新候補は元の判定へ流入しない。
- 候補処理にもCPU時間はかかる。実機ではその時間も既存の500 ms鮮度上限へ含め、上限延長や古い画像の再使用はしない。実GPUでの追加負荷は未測定。

実装箇所: `src/cone_distance_core.py`、`src/cone_distance_worker.py`、`src/run_cone_distance_live.py`、`src/summarize_cone_distance_live.py`。候補抽出本体`src/cone_support_completion_candidate.py`は前段から変更していない。

## 連続録画の比較

最終結果は[summary.json](contiguous_replay_r02/summary.json)、[session集計CSV](contiguous_replay_r02/session_counts.csv)、[全フレームログ](contiguous_replay_r02/replay_frames.jsonl)。[グラフ](contiguous_replay_r02/support_availability.png)は数値ログから生成したもので、カメラ画像を編集したものではない。

10/15の原録画6本、計3,596フレームを順に復号した。`raw.avi`/`metadata.json`/`detections.csv`のhashと、保存済み推論の全フレーム台帳・時刻・閾値・重みhashを照合。新たなYOLO推論や学習は行っていない。画像上の支持範囲は原画素から再計算した。

| 条件 | 全フレーム | 色分離候補の点あり | 新候補の点あり | 従来判定の不一致 |
| --- | ---: | ---: | ---: | ---: |
| 中央1.30 m | 651 | 651 | 651 | 0 |
| 中央2.00 m | 632 | 632 | 632 | 0 |
| 左1.30 m | 628 | 628 | 628 | 0 |
| コーンなし | 332 | 0 | 0 | 0 |
| 右1.30 m | 631 | 628 | 628 | 0 |
| 中央0.80 m | 722 | 722 | 722 | 0 |
| 合計 | 3,596 | 3,261 | 3,261 | 0 |

- 点の消失0、既存点の座標変更0。コーンなし332フレームで新たな点は出していない。右条件の残る3フレームは複数候補として双方保留。
- 元と同じ時系列品質ゲートを**独立したオフライン評価用**に両候補へ適用した結果、双方3,248フレームで画像上の連続性条件を通った。実接地や距離の合格件数ではない。この独立ゲートを実行時の距離判定へ接続していない。
- 隣接する点の変化量の最大値は双方約4.47 px。静止条件での画像上の変動であり、物理距離誤差ではない。
- **この6本には左右枠接触の補完が試行されるフレームがなく、試行・追加取得とも0。** 従来点を壊さない回帰根拠にはなるが、補完が必要な場面の連続安定性を確認したとは言えない。

### 比較時計と姿勢の制限

本比較は支持点ログの非干渉性に限定した。双方へ原録画時刻+10 msの同じ論理時計を与え、**背景姿勢推定は起動していない**。姿勢未初期化のため、双方の距離出力は0件。これを実測処理遅延、通信遅延、GPU負荷、リアルタイムFPS、測距精度や「実機測距成功」として扱わない。

自動テストでは別途、姿勢初期化済みの場合でも新候補を本判定へ流入させないこと、比較処理が遅ければ従来の鮮度条件で保留することを確認した。

初回実行`contiguous_replay_r01/`は欠測区間の終端集計に空の逆転区間を出す不具合があり、最終結果には使わない。終端・全欠測・空・中間欠測の4テストを追加し、同一入力で全フレームを再実行したr02が上記の結果。原録画や候補条件の変更ではない。

## 現USBキャプチャの保存2画像

[結果JSON](current_pair_r01/results.json)。既存のCPU再推論bboxを再利用し、赤コーンへ明示ROI `(270,0,350,720)`を適用した。独立した静止画として別sessionで処理し、時間的な連続観測に見せかけていない。

| 元フレーム | 色分離候補 | 新候補 | 補完による追加取得 | 本判定の距離 |
| --- | --- | --- | --- | --- |
| 1259 | 枠端接触で保留 | `[299,385]` | あり | 保留 |
| 1655 | `[300,385]` | `[300,385]` | なし・既存点維持 | 保留 |

これは現在のキャプチャの画素を、新しい**エンジン→ログ**経路へ通せる根拠。GPU受信時のbboxそのものや連続フレーム検証ではない。約1.5 mという床タイルからの概算を校正・閾値調整・正解判定へ使っていない。

## ソフトウェア検証

[最終検証](verification_r02/verification.json)、[211テスト一覧](verification_r02/tests.csv)、[実行ログ](verification_r02/tests.log)。211件PASS、失敗0・エラー0・skip0。

- 未指定時の既定動作を凍結前コードと比較。
- 候補点が取れても姿勢を初期化せず、距離出力を許可しない。
- 元の色分離比較ログ、枠選択、画像の画素を維持。
- 候補処理の例外を元の検出失敗に置換しない。
- 実workerスレッドからJSONへ保存し、標準reportで候補だけを分離集計。
- 新候補が`controlling_distance=true`、`physical_metric_verified=true`などを名乗るログ、支持列にない点をreportで拒否。
- 終了未完了のログを、候補点があっても実機合格にしない。
- 従来の校正・姿勢・幾何・通信・支持品質など12ファイルはGit基準から変更なし。
- 過去の入力/コードhash346件を照合。意図して変更した4ソースは変更前の全量保存版`source_snapshot/`に照合し、不一致0。変更後の4ファイルのhashも別途記録。過去資料のhashを書き換えて「変更なし」に見せてはいない。

試験ログの故障注入によるエラー表示は、テスト失敗とは別。実カメラ等を起動した記録ではない。

## 再現（解析PC・実機不要）

出力先は未使用名へ変更する。元録画や保存済み検出は上記のローカル保存場所が必要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/cone_completion_logging_r01/replay_contiguous.py --output-dir Experimental_results/2026-10-30/cone_completion_logging_r01/contiguous_replay_r03
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/cone_completion_logging_r01/check_current_pair.py --output-dir Experimental_results/2026-10-30/cone_completion_logging_r01/current_pair_r02
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/cone_completion_logging_r01/verify.py --output-dir Experimental_results/2026-10-30/cone_completion_logging_r01/verification_r03
```

## 後日、比較ログを採る場合だけのコマンド

**今すぐの追加撮影依頼ではない。** 実機時の検証用に記載。GPU PC（`hsr-Alienware-m16-R2`）側:

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
./start_cone_distance.sh receive --weights "$HOME/Downloads/cone_distance_v03.pt" --target-roi 270 0 350 720 --colour-support-shadow --support-completion-shadow --output-dir Experimental_results/2026-10-30/cone_distance_completion_shadow_r01
```

日付・出力名は実施時に未使用名へ変更。既存のhash照合済み重みを使用し、hashチェックを回避しない。送信側は従来の映像専用コマンドのまま。別の受信プロセスと同じ5002番ポートを同時使用しない。Sキーで保存する原画像も従来と同じ無加工。

正常停止後に同じGPU PCで集計:

```bash
./start_cone_distance.sh report --input-dir Experimental_results/2026-10-30/cone_distance_completion_shadow_r01 --output-dir Experimental_results/2026-10-30/cone_distance_completion_shadow_report_r01
```

新しい項目が増えるのはログと集計であり、画面の距離を強制表示するスイッチではない。新候補からの測距本採用、背景姿勢不足の解消、実測基準との対応、実GPUでの負荷・連続動作は残る。**現状は静止診断の開発段階であり、走行・FFBへ進める承認ではない。**
