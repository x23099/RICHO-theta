# 2026-08-26 独立holdout失敗原因診断

## 結論

独立holdoutのFAILは、斜距離面積ゲートそのものではなく、互いに独立した2要因で発生した。

1. 箱なし試行では、カメラ直下に写る黒いゴムマット上端が青色領域として抽出された。
   この誤候補は実物の青箱と異なり、幅が高さより明確に大きい横長輪郭である。
2. FPS不合格は、欠番や長時間停止ではなく、33.3 msのフレーム予算を数ms超える処理が
   継続した結果である。UIスレッド内で3本のMJPGを同期保存する現在の構成には余裕がない。

本番設定`src/bird_eye_config.json`は変更していない。今回のholdoutは判定後に診断用データへ
移行したため、ここから得た条件を実装する場合は、新しい独立録画で再検証する必要がある。

## 対象

- holdout: `/home/robo25/Downloads/recoding/202608261410.tar.xz`
- SHA-256: `f4e5346d41da819422d9539c97e216a7a4de8a0b12fc82b6aecfb1e1cd438fab`
- 比較用の過去箱なし: `/home/robo25/Downloads/recoding/08251330.tar.xz`
- 判定時commit: `a5cc7c7`
- 固定候補: `raw_ground_distance + normalized_area_min=2000`
- HSV: `H=90..140, S=70..255, V=30..255`, illumination=`none`

## 1. 箱なし誤検出

### 1.1 発生箇所

生映像を輪郭とHSVマスク付きで確認した。候補は人物や室内の青い物体ではなく、前側魚眼の
下部中央に写る黒いゴムマットと灰色床の境界である。MJPG画像上で暗い境界の一部が青系に
量子化され、形態学的close後に細長い輪郭として残っていた。

今回の箱なし録画を再エンコード済み`raw.avi`から再計算すると387/818フレーム（47.31%）、
前日別位置の箱なし録画では853/853フレーム（100%）で同じ領域が検出された。ライブCSVの
754/818フレーム（92.18%）との差は、カメラ入力をMJPG AVIへ再圧縮した前後で閾値近傍の暗色
画素が変化したためである。頻度は変化するが、発生位置と横長形状は共通している。

### 1.2 形状比較

`src/diagnose_candidate_shapes.py`で次を比較した。

- 誤候補: 2つの箱なし録画、計1,240観測。
- 真の候補: 過去と今回の24セッションについて、各セッションの中央値から0.15 m以内にある
  `visible`または`reappearing`観測、計14,002観測。

| 指標 | 箱なし誤候補 | 安定した青箱 |
|---|---:|---:|
| 輪郭面積範囲 | 300.0–2,287.0 px | 476.5–3,590.0 px |
| 幅÷高さ 最小 | 1.545 | 0.565 |
| 幅÷高さ 中央値 | 2.600 | 0.737 |
| 幅÷高さ 最大 | 5.800 | 1.393 |
| `幅÷高さ <= 1.5`を満たす数 | 0/1,240 | 14,002/14,002 |

面積範囲は重なるので固定面積を上げるだけでは安全に分離できない。一方、`max_aspect_ratio=1.5`
は今回確認した誤候補を全除外し、安定表示と再出現の真の候補を全保持した。完全遮蔽中に残る
横長断片も除外されるため、遮蔽時の外れ値抑制とも整合する。

HSVの簡易スクリーニングでは、今回の映像に限れば`V>=40`で箱なし0%、左右1.2 mの箱100%と
なった。ただし`V>=50`では箱輪郭が崩れてゲート判定がFAILし、過去には暗所性能がV値へ敏感な
録画がある。したがって色閾値変更より、対象物の幾何に基づく横長除外を第一候補とする。

なお現行の校正範囲・正規化面積ゲートは、ライブ箱なし試行で誤候補を全棄却し、追跡・警告を
0件に保った。今回の問題は安全出力への誤採用ではなく、事前条件で要求した生検出0件を満たせ
なかったことである。

## 2. FPS低下

`src/diagnose_recording_timing.py`で単調時計の隣接差を解析した。

| 試行 | 実効FPS | dt中央値 | dt p95 | 40 ms超 | 判定 |
|---|---:|---:|---:|---:|---|
| 箱なし | 30.007 | 32.409 ms | 37.693 ms | 0.98% | PASS |
| 左0.9 m | 29.303 | 34.770 ms | 40.178 ms | 5.33% | FAIL |
| 右0.9 m | 29.204 | 34.095 ms | 42.257 ms | 10.85% | FAIL |
| 左1.2 m | 29.903 | 33.478 ms | 39.518 ms | 4.15% | PASS |
| 右1.2 m | 29.736 | 33.401 ms | 40.120 ms | 5.62% | PASS |
| 中央1.2 m遮蔽 | 29.059 | 34.034 ms | 43.805 ms | 15.81% | FAIL |

全試行でCSV欠番なし、`time_sec == monotonic_time_sec`、動画ヘッダ30 fps、3動画のフレーム数と
CSV行数一致、ODOM有効率100%だった。最大停止は74.707 msであり、秒単位の停止やI/O停止では
ない。不合格試行では中央値自体が約34 msへ移り、短い超過が継続している。

`bird_eye.py`は30 fps時に`QTimer`を33 msで駆動し、同じUIスレッドで次を直列実行する。

1. カメラread、BEV remap、白線処理。
2. HSV抽出、輪郭処理、接地点推定、追跡・描画。
3. `raw.avi`、`bev.avi`、`detection.avi`のMJPG同期書き込み。
4. 2画面のQt表示。

既存録画120フレームを用いた参考ベンチでは、3本の`VideoWriter.write`合計が平均
19.68–20.27 ms/frame、青接地点検出が箱なし平均4.35 ms、箱あり平均4.64–4.72 msだった。
この時点で33.3 ms予算の約73–75%を消費し、BEV・白線・Qt表示・camera readの余裕が約8 msしか
ない。青箱ありで輪郭点が増える差と、遮蔽時の動き・描画負荷がこの余裕を超えたと考えられる。

したがってカメラの30 fpsネゴシエーションやODOM欠損ではなく、同期処理パイプラインの予算不足が
主原因候補である。ただし録画時の区間別処理時間はまだCSVへ記録されていないため、どの段階が
何ms増加したかの確定には実機テレメトリ追加が必要である。

## 3. 次の実装候補

優先順は次のとおりとする。

1. 開発用設定に`blue_ground_contact_max_aspect_ratio=1.5`を追加し、候補選択前に横長輪郭を除外する。
   過去全録画、特に`visible`、`reappearing`、部分遮蔽で回帰確認する。本番設定はまだ変えない。
2. `update_frame`へ`read/remap/blue/write/display`の区間時間を追加し、録画CSVまたは別CSVへ保存する。
3. 3動画同期保存を、まず`raw`必須・派生2動画任意に分離して30 fpsを再測定する。その後、必要なら
   bounded queueを使う非同期writerを検討する。キュー満杯時の方針と欠落数は必ず記録する。
4. 上記を実装後、今回とは別の短い開発録画で確認し、最後に新しい独立holdoutを取得する。

最小の次回実機確認は、同じマットで箱なし10秒、別床で箱なし10秒、青箱0.9 m・1.2 mを各10秒、
遮蔽2回とする。形状条件とFPS改善を同一の新規録画で混同せず、raw-onlyと3動画保存のA/Bを分ける。

## 4. 再現コマンド

形状比較:

```bash
python3 src/diagnose_candidate_shapes.py \
  --no-target-input Experimental_results/2026-08-26_historical_no_target_observation_replay.csv \
  --no-target-input Experimental_results/2026-08-26_no_target_observation_replay.csv \
  --target-input Experimental_results/2026-08-25_holdout_observation_replay.csv \
  --target-input Experimental_results/2026-08-25_raw_ground_distance_observation_replay.csv \
  --target-input Experimental_results/2026-08-25_environment_shift_observation_replay.csv \
  --target-input Experimental_results/2026-08-26_raw_ground_distance_holdout_observation_replay.csv \
  --max-aspect-ratio 1.5 \
  --output Experimental_results/2026-08-26_candidate_shape_diagnosis.csv
```

FPS診断はアーカイブを一時展開したルートに対して実行する。

```bash
python3 src/diagnose_recording_timing.py \
  --input /tmp/theta-diagnose-0826-g56NHL \
  --output Experimental_results/2026-08-26_recording_timing_diagnosis.csv
```

関連成果物:

- `Experimental_results/2026-08-26_candidate_shape_diagnosis.csv`
- `Experimental_results/2026-08-26_recording_timing_diagnosis.csv`
- `Experimental_results/2026-08-26_no_target_observation_replay.csv`
- `Experimental_results/2026-08-26_historical_no_target_observation_replay.csv`
