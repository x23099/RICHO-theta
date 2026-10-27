# 録画で検証できる共通測距処理とGPU受信への接続（2026-10-26）

> 同日後続でsceneサンプリングのずれを修正した。最新は
> [cadence監査](../scene_cadence_audit_r01/README.md)と[最終再計算](../cone_distance_report_r03/README.md)。
> 以下は修正前r03当時の記録。変更前ソースは[source_snapshot](source_snapshot/README.md)に保存。

## 結論

学校のカメラ・ハンコン・Kobukiへ接続しなくても行える実装と検証を実施した。
**現時点で利用者の実機操作・追加録画は不要。**

- カメラ受信と録画再計算の両方から使える測距処理を実装した。
- YOLOは物体枠を与えるだけ。距離には現在画像の色輪郭・実際の下側支持範囲を使用する。
- 自sessionの過去フレームだけで場面姿勢を初期化し、最新の場面が未処理・拒否・期限切れなら距離を出さない。
- GPU受信向けに推論workerと場面workerを分離した。ネットワーク受信loopへ推論を直接追加していない。
- 結果は使用した画像・session・frameと組にして表示し、新しい画像へ古い距離を重ねない。
- 欠測の補間や前の距離の維持は行わない。FFB・ROS・車体操作へは接続しない。

ただし、**実カメラでのリアルタイム測距の完成・合格ではない**。
今回の数値検証は保存済みYOLO枠の再利用であり、新規GPU推論・実通信・カメラ受信の実行確認は未実施。
さらに、独立した録画で場面姿勢が初期化できず、距離を全く出せない例が残った。

## 実装の位置

| ファイル | 内容 |
|---|---|
| `src/cone_distance_core.py` | 入力契約、対象範囲、輪郭、支持範囲、因果的な場面完了管理、床交点、表示用コピー |
| `src/cone_scene_diagnostic.py` | 検証済み場面線抽出・鉛直仮説・PastOnlyPoseを新srcへ移植 |
| `src/cone_distance_diagnostic_config.json` | 既存校正候補・床変換候補・モデルのSHA256と固定条件 |
| `src/cone_distance_worker.py` | 容量1入力の処理worker、1個までの場面future、明示的なローカルCUDAモデル |
| `src/run_cone_distance_replay.py` | 元動画・元時刻・保存済み検出枠からの順序再計算 |
| `src/run_cone_distance_live.py` | 前回のRTC Receiverを再利用する、測距付きの別GPU受信エントリーポイント |
| `src/summarize_cone_distance_replay.py` | 完了後にのみ基準距離・区間を添えて集計・画像化 |
| `start_cone_distance.sh` | `replay` / `receive` の起動入口 |

通常の `start_theta_receive_rtc.sh` / `start_theta_stream_rtc.sh` と、前回の映像専用
`--diagnostic` モードは今回変更していない。測距受信は別エントリーポイント。
測距受信へ送るときも、matunuc側は前回と同じ映像専用 `--diagnostic` 送信を使う。
旧WebRTCの車体操作を含むコードや `bird_eye.py` の本番FFB経路は変更していない。

## 数値結果：最終検証はreplay r03

3つの元録画・4条件、延べ4,077フレームを処理した。同じ録画の範囲違いを独立録画とは数えない。

| 条件 | 元フレーム | 条件付き距離出力 | 補足 |
|---|---:|---:|---|
| 同一姿勢の床→コーン録画：明示的な中央範囲 | 1,547 | 279 | 中央範囲を利用者の診断条件として宣言 |
| 同じ録画：全前方レンズの対照 | 1,547 | 36 | 中央コーン区間は複数コーンのため全て見送り。36出力は背景コーン側 |
| 別録画の中央1.3 m：中央範囲 | 651 | 0 | 場面22回中、採用1回。自session姿勢を初期化できない |
| 中央コーンなし：中央範囲 | 332 | 0 | 中央範囲の候補なし。背景にもコーンがないという意味ではない |

中央範囲は、**bbox中心**がnative画像の `x=270～350, y=0～720` にある物体を対象にする
明示的オプション。輪郭の切り抜き範囲や校正を変えるものではない。
従来の中央コーン比較と同じ対象範囲を宣言したもので、距離基準に合わせた自動選択・追跡ではない。
デフォルトは全前方。複数コーンがあれば勝手に一つを選ばない。
**範囲外の障害物を監視できるとは主張しない。本番FFBの対象選択規則として採用していない。**

完了した中央範囲の再計算へ、既存の評価区間を後から対応付けた結果：

| 既存評価区間 | 全フレーム | 出力フレーム | 出力値の中央値 | 基準値との差の中央値 |
|---|---:|---:|---:|---:|
| 中央1.3 m | 218 | 91 | 1.3279 m | +0.0279 m |
| 中央2.0 m | 548 | 155 | 1.9784 m | −0.0216 m |

出力できたフレームだけの値であり、全フレームの精度・検出再現率ではない。
出力しなかった区間を取り除いて「連続測距が完成」とは扱わない。
評価区間・基準距離は `phase_summary.csv` を作る後処理にのみ使用し、測距engineへ渡していない。
対象は床面仮定上の前方成分であり、車体前端までの最短距離や測量済み接地点ではない。

場面線抽出のしきい値、2枚学習＋2枚後続検証、2度の整合性、最終場面sourceから1秒の期限は変更していない。
新しい場面が処理中なら結果が判明する前から見送る。
処理完了時刻をsource時刻へすり替えて姿勢を延命しない。

replay r03では場面1処理のCPU中央値は約86～132 ms、検出枠再利用＋支持範囲・測距処理の中央値は
対象条件で約4.5～5.9 msだった。GPU推論、カメラ読出し、ネットワーク遅延は含まない。
場面の完了可否は「元時刻＋その場で測定したCPU所要時間」の機能検証用仮想時刻で反映する。
並行負荷で採用フレーム数が変わり得るため、実機FPS・通信遅延の再現実験ではない。

## 画像とグラフ

- [距離と見送り理由の時系列](distance_and_withholding_timeline.png)
- [1.3 m区間：距離表示付きの再計算画像](visualizations/cone_130_recomputed_f000613.png)
- [2.0 m区間：距離表示付きの再計算画像](visualizations/cone_200_recomputed_f001000.png)
- 元画像：[1.3 m区間](originals/cone_130_raw_f000613.png)、[2.0 m区間](originals/cone_200_raw_f001000.png)

元画像は全画角1280×720のまま、注釈・リサイズ・色補正なしで保存した。
数値入り画像は別ファイルで `RECORDED RECOMPUTATION` と明示した。
各評価区間で最初に数値が出たフレームを選び、最小誤差の画像を選んでいない。
画像・CSV・スクリプト・元録画の追跡は `summary.json` に保存。
MatplotlibのAxes3Dが利用できない警告は出たが、今回の2Dグラフの生成は完了。環境変更はしていない。

## 学校へ行かずに再実行する場合

**いま利用者が実行する必要はない。既にこちらで下記の再計算を実施済み。**
元録画と保存済み検出結果があるPCで、cv2/numpyの既存環境を使う。GPUは不要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
export THETA_DISTANCE_PYTHON=/home/robo25/theta-env/bin/python3
OPENBLAS_NUM_THREADS=1 ./start_cone_distance.sh replay \
  --session recordings/2026-10-15_floor_cone_same_pose_intake_r01/floor_cone_same_pose_r01_20261015_160621_378 \
  --saved-run Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/inference_r01 \
  --target-roi 270 0 350 720 \
  --output-dir Experimental_results/2026-10-26/cone_distance_replay_next_r01
```

再実行時は新しい出力先にする。既存の結果を削除・上書きしない。
`--saved-run` のモデルSHA256・しきい値、元録画のraw/metadata/CSVハッシュ、全frame/time/枠件数を照合する。
保存済みの距離CSVを表示するのではなく、元動画の現在画素から支持範囲・場面・交点を再計算する。

集計再現（出力は新規の別名へ変更する）：

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 src/summarize_cone_distance_replay.py \
  --replay-root Experimental_results/2026-10-26/cone_distance_replay_r03 \
  --scope-json Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/scope.json \
  --output-dir Experimental_results/2026-10-26/cone_distance_report_next_r01
```

## 後日：実カメラを接続できるときだけ

まだこの操作をしなくても、ソフトウェアの検証は進められる。
実機時は車体静止・FFBなし。通常受信UI/映像専用受信と同じ5002番ポートを二重起動しない。

GPU PCで、今回のsrcと同じvenvに **cv2/numpy/aiortc/av/aiohttp/torch/ultralytics** があることを確認する。
依存不足があっても共有環境やドライバを勝手に更新しない。
モデルはv03の学習済み `best.pt`、SHA256は設定内の `3a6e124a…ae5997b` と一致するものを使う。

```bash
# GPU PC：更新したRICHO-thetaのルート。実際のvenv配置を確認して指定する。
export THETA_DISTANCE_PYTHON="$(command -v python3)"
./start_cone_distance.sh receive \
  --weights runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt \
  --target-roi 270 0 350 720 \
  --output-dir Experimental_results/2026-10-26/cone_distance_live_r01
```

matunuc側は前回の `src/start_theta_stream_rtc.sh --diagnostic --receiver-ip <GPU_PC_IP> --device /dev/video0 --fps 30`。
受信は最新入力だけを処理し、場面futureは同時1個まで。新しい接続では初期化し直す。
使用画像の受信から500 ms超の結果、切断後や別sessionの結果は距離を表示しない。
`S` で無注釈の受信デコード画像を保存できるが、VP8後の画像なのでカメラ生画像とは区別する。
`distance_frames.jsonl` と `live_summary.json` を保存する。

## 検証と残課題

新規30テスト、既存RTC 26テスト、支持範囲24テストの計80テストがPASS。
場面抽出・姿勢推定の移植は元関数10個のAST一致で確認し、保存済み実画素2枚の場面判断も完全一致した。
切断中の処理終了、古いscene ticket、複数物体、処理遅延、コピー表示、未来証拠からの非干渉も検証した。

実カメラ・実通信・新規CUDA推論・走行・FFBは今回実行していない。
別録画では自session場面の初期化ができず出力0という課題があるため、次は既存データで
**姿勢の初期化が成立しない理由と、測定対象の明示方法**を優先して整理する。
測量済みカメラTFや床接地点対応が検証済みになったわけではない。
`physical_metric_verified` / `floor_contact_verified` / `usable_for_ffb` は常にfalseのまま。

開発途中の `cone_distance_replay_r01` / `r02` は探索ログとして残し、最終検証値・再現対象はr03のみとする。
コードの変更前ハッシュを含む探索ログを、現行コードの検証証明として再利用しない。
