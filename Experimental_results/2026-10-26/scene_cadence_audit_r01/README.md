# 場面姿勢のサンプリングずれを修正（2026-10-26）

## 結論

追加録画なしで、10/26に追加した実行用engineと過去検証の間にあった、
**1秒間隔の解釈の不一致**を発見・修正した。必要線数や角度の条件は変更していない。
最終の監査は `results_r02`、修正後の録画再計算は `cone_distance_replay_r05`。

- 旧：前回選んだ画像の実source時刻から1秒後。frameの端数時間が累積していた。
- 新：最初の処理画像のsource時刻を原点に、1秒・2秒・3秒…の固定格子。
  その目標以上の最初の利用可能な画像を使う。
- busy中はscene futureを増やさず、古い画像のcatch-upキューも作らない。
  復帰時は、その時に利用可能な新しい画像で複数の過期限目標を1回にまとめて処理する。
- 場面の1秒期限は引き続き**使用画像のsource時刻**から数える。
  目標時刻・処理完了時刻への付け替えや、距離の補間はしない。
- 接続sessionが変わると原点も初期化する。

これは**同じPC内でどの画像を選ぶか**の問題。NTPのずれ、通信遅延、カメラの露光時刻の問題ではない。

## 実データ照合

9録画の元CSV、全14,526 frameを読み、過去に固定した1秒格子と全件照合した。
元CSV9本のハッシュも過去のsampling planと一致した。

| 確認 | 結果 |
|---|---:|
| 過去の固定格子で選んだframe | 492 |
| 修正後が選んだframe | 492 |
| frame・source時刻・目標時刻の不一致 | **0** |
| 旧rolling方式が選んだframe | 481 |
| 旧r03の実ジョブ台帳との不一致 | **0（4条件）** |

中央1.3 m録画の最後の対応点では、旧frame642に対して固定格子はframe629。
同じ標本番号でsource時刻が**417.106 ms（13 frame）**ずれていた。
約256秒の白紙録画では、最後の対応点のずれは約4.49秒。
これは角度校正や画像内容の違いから計算した値ではなく、同じ元CSV上の標本選択差。

[全frame選択の照合](results_r02/paired_sampling.csv)／
[録画ごとの集計](results_r02/session_sampling_summary.csv)／
[サンプリングずれのグラフ](results_r02/sampling_drift.png)／
[入力・出力hash](results_r02/summary.json)

## 修正後にも残る初期化不足

別録画の中央1.3 mは、修正前の有効姿勢画像1枚から、修正後は2枚へ戻った。
ただし2枚学習＋2枚後続検証の計4枚に届かず、651 frameの距離出力は依然0。
「サンプリング修正で全録画の測距が成功した」とは扱わない。

その22個の固定frameは、以前のconsensus監査とも同じ画像である。
`2026-10-22/scene_rejection_audit_r01/results_r02/all_frame_consensus.csv`では次の内訳だった。

| 最初の方向に一致した平面 | 画像数 | 状態 |
|---|---:|---|
| 4本 | 1 | 必要6本に不足 |
| 5本 | 19 | 必要6本に不足 |
| 6本 | 2 | 条件付き方向を採用 |

したがって、この録画の不足を、画像が届かない・YOLOが動かない・初期化待ち表示だけの問題とは説明しない。
静止して同じ像が続いても、独立した方向根拠が増えるとは限らない。
6本を5本へ下げたり、旧ROI拡張で増えた重複/コーン由来の線を再採用したりはしていない。

## 修正後の再計算

最終版r05は同じ3録画の2,530 frame。
中央範囲は前回同様、明示的な `--target-roi 270 0 350 720`。範囲外の監視や本番対象選択は未完成。

| 録画 | 修正前r03の出力 | 修正後r05の出力 |
|---|---:|---:|
| 同一姿勢の床→コーン録画：1,547 frame | 279 | **326** |
| 別の中央1.3 m：651 frame | 0 | **0** |
| 中央コーンなし：332 frame | 0 | **0** |

同一姿勢系列のsceneは51回→52回となり、有効方向はどちらも17枚。
どの画像を使うかが変わるため、学習に使われるupや出力区間も変わる。
なお、各実行で測定したCPU所要時間も機能検証用の仮想完了時刻へ含む。
323件だった中間r04と最終326件の差のように負荷で件数は変わり得るため、
**増加47件すべてを修正だけの効果と断定せず、実機の改善率にも使わない。**
確定した修正根拠は、固定済み492個のframe選択との完全一致である。

最新の推定画像・距離数値は[最終再計算レポート](../cone_distance_report_r03/README.md)を参照。
カメラ・ネットワーク・新規CUDA推論・走行・ROS/FFBは今回も実行していない。
全結果の物理距離確認・FFB使用許可はfalseのまま。

## コード・検証

- `src/scene_sampling_clock.py`：原点固定格子、busy/欠落目標の処理、極端な時刻の表現不能を無限ループせず拒否。
- `src/cone_distance_core.py`：scene開始に共通clockを使用。画像判定・初期化のしきい値は維持。
- `src/run_cone_distance_replay.py`：目標時刻・飛ばした目標数・clockソースのhashを追加記録。
- `src/audit_scene_cadence.py`：9録画の旧/新標本と旧r03実ジョブを照合。
- 新規clock15件＋既存engine30件＋RTC26件＋支持範囲24件の**計95件PASS**。
- Python構文、シェル構文、`git diff --check`もPASS。成功記録は `verification.json`。

変更前のr03 core/runnerは `cone_distance_report_r01/source_snapshot`、
最初の格子版r04のclockは `cone_distance_report_r02/source_snapshot`へ、元SHA256と一致するソースを保存した。
結果を上書きしたり、変更前結果を現行コードの証明にすり替えたりしていない。
監査results_r01と再計算r04は途中記録で、最終参照は監査results_r02＋再計算r05。

再現：

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  -m unittest discover -s tests -p test_scene_sampling_clock.py -v
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  src/audit_scene_cadence.py \
  --output-dir Experimental_results/2026-10-26/scene_cadence_audit_next_r01
```

既存出力は上書きしない。利用者の学校PC操作や撮り直しは今すぐ必要ない。
追加の閾値調整を続けず、姿勢の根拠が不足する入力では距離を出さない制約を維持する。
