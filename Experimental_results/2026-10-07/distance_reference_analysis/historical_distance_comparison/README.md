# 過去4配置の距離・横位置再評価（2026-10-07）

## 結論

追加録画なしで、2026-08-07の最終評価に用いた4配置を元動画から再計算した。当時のground-contact評価値は、座標4項目と検出／標本数の計24照合がすべて一致した（座標許容差1e-9 m）。原本取り違えや旧BEVのCSV値を使った比較ではない。

現行baselineの前方距離Zの平均絶対誤差は、この過去4配置の中央値に対して **1.53 cm**。一方、凍結候補`seeded_s130_bottom`はZ **1.69 cm**、横位置X **3.24 cm**となり、baselineのX **1.47 cm**より悪化した。下端幅方向の中央値は「安定した値」でも、従来の最近傍輪郭点と代表する場所が違う。既存の横位置補正式を流用したまま本番へ置き換える根拠にはならない。

今回10/07の中央1.10 m条件に見られる約7～8 cmの短めのZは、この過去4配置で共通に再現する現象ではなかった。ただし距離・横配置・床面・撮影時期が違うため、10/07の原因を床反射／姿勢／測定のどれかに確定する結果ではない。固定係数や高さ・傾きは変更していない。

## 入力と比較方法

- 原本：`/home/robo25/Downloads/recoding/coding_20260807_6.tar.xz`。SHA256と各sessionの5ファイルのhashは[verification.json](verification.json)。safe extractorで展開し、Gitへ生録画は追加していない。
- 参照：[2026-08-07最終評価CSV](../../../2026-08-07/2026-08-07_ground_contact_final_evaluation.csv)、[当時の保存済みモデル](../../../2026-08-07/2026-08-07_ground_contact_model.json)。公称座標はこれらの既存記録を保持。今回の回答で確認済みの10/07の測定起点・姿勢条件を、8月の録画へ遡及して断定しない。
- 数値上のカメラ幾何9項目は全sessionで現行v12設定と一致。各録画の幾何を保持し、検出器設定だけを比較用に適用した。数値の一致は実際の取り付け姿勢の一致を証明しない。
- 当時の`detections.csv`は**旧BEV方式**。フレーム番号と公称時刻の対応にだけ使用し、raw座標をground-contact値と誤認していない。
- 4方式：`historical_recipe`（当時の300 px／下位8%輪郭・aspect上限なし）、`baseline`（現行検出器）、`seeded_s130_nearest`、`seeded_s130_bottom`。後2方式の設定・実装hashとbaselineの検出器上書きは10/06の凍結値と一致確認済み。
- 座標変換は保存済みground-contact係数のみ：X=`0.607688741902197 * raw_X + 0.022595727915692983`、Z=`raw_Z`。旧BEVのZ倍率・offsetや表示用車体offsetは適用しない。係数の再推定は行っていない。
- `all`、`after_2s`、`historical_sampled`の3窓を保存。最後の窓は当時と同じ **zero-based index>=30、index%5==0**（1-based frame31,36,…）。`after_2s`は旧CSVの公称時刻>=2秒であり、実測キャプチャ時間ではない。
- 原CSVとraw／BEV／detection動画を全フレーム逐次デコード。236／214／310／290フレームがそれぞれすべて一致、計1,050フレーム。4方式で4,200行、48集計行を保存。全4方式で検出1,050/1,050。範囲外なら座標を統計から消す処理は入れていない。
- 人物による箱の遮蔽がないことを、結果確認前に各録画の最初／中央／最後の計12枚で確認：[manual_review.csv](manual_review.csv)。全動画への独立した物体正解ラベルや物理接地点ラベルではない。

## 定量結果

以下は`after_2s`。誤差符号は推定−当時の公称値。Zは前方座標であり斜距離ではない。単位cm。

|公称X / Z（m）|baseline Z誤差|S130 nearest Z誤差|S130 bottom Z誤差|baseline X誤差|S130 bottom X誤差|
|---|---:|---:|---:|---:|---:|
|−0.22 / 0.95|−2.96|−1.44|−1.38|+2.66|−2.60|
|−0.22 / 1.20|−0.67|−0.80|−0.72|+2.77|−2.58|
|+0.22 / 0.95|+0.99|+1.91|+2.26|+0.36|+4.21|
|+0.22 / 1.20|+1.50|+1.59|+2.40|−0.11|+3.57|

|方式|Z中央値誤差のMAE|X中央値誤差のMAE|2D位置誤差の平均|
|---|---:|---:|---:|
|baseline（historical_recipeと同値）|1.53|1.47|2.35|
|S130 nearest|1.44|1.45|2.22|
|S130 bottom|1.69|3.24|3.68|

各配置を等重みとして平均した値であり、フレーム数の多い録画を優遇しない。S130 nearestの小さな改善も、4点・正解配置誤差未記録・既に閲覧済みの過去評価であることから、優位性を確定する材料ではない。historical_recipeとbaselineの今回の中央値が同じでも、検出器設定が全く同一という意味ではない（aspect上限の有無等）。

なお「当時の結果の再現」は`historical_sampled`窓で照合する。上表の`after_2s`とは標本が違うため、当時のX誤差の平均と上表の数値が微小に違うのは矛盾ではない。

## 成果物

- [summary.csv](summary.csv)：48行、配置×方式×窓。
- [aggregate.csv](aggregate.csv)：12行、各配置の等重み比較。
- [frame_results.csv](frame_results.csv)：4,200行、フレーム・接点pixel・bbox・未校正座標・保存済み係数適用後座標。欠測は空欄で0 mではない。
- [historical_reproduction.csv](historical_reproduction.csv)：24項目の照合。
- [parameter_audit.csv](parameter_audit.csv)、[verification.json](verification.json)：実効値／default／入力hash／コードhash／未評価範囲。
- [誤差比較グラフ](historical_distance_bias.png)、[前方距離タイムライン](historical_distance_timeline.png)：[生成スクリプト](compare_historical_distance.py)で上記CSVと同じ数値から生成。
- [代表raw画像とmanifest](../../report_assets/README.md)：左0.95 m frame118、右1.20 m frame145。1280×720・全画角・無加工。逐次rawデコードとPNG再読込で画素一致を確認。

## 判断と次の切り分け

1. 本番の検出器／距離校正／TTC／FFB設定は維持。候補bottomの自動採用は見送る。
2. 今回の1.10 mだけへoffsetを合わせない。共通高さ・共通offset単独では3配置を同時説明しにくいという[10/07の条件付き診断](../geometry_diagnosis.md)とも整合するが、この過去録画だけで根本原因は決まらない。
3. 次は、箱前面中央の接地点と床面上の既知点を区別した独立ラベル／基準情報で、固定の魚眼→床面投影の残差を確認する。近い輪郭点・幅方向中央値の代表点定義と、距離を測る箱の面の定義を揃える。確認用画像上で、正解Zへ近くなるpixelだけを選ぶ方法は使わない。
4. 今すぐ同条件を丸ごと録り直す必要はない。既存の全フレーム・過去4点までの比較は完了。絶対幾何の確定・候補採用には、独立した床面基準点や実姿勢の測定が次の材料となる。

## 検証と限界

[test_historical_distance.py](test_historical_distance.py)の9 testsで、標本index、ラベル不一致、幾何の保持、旧BEV係数非適用、欠測、範囲外座標の保持、非有限値拒否、過去再現照合、配置の等重み集計を確認した。録画解析の24再現チェックもPASS。本番srcは変更していないため本番unit testsの再実行は行っていない。

ODOM・操作速度・monotonic時刻が原録画にない。ゼロ速度を捏造せず、追跡の採用率／TTC／通信／実FFB／処理FPSは**未評価**。30fps相当のCSV時刻を実測FPSと呼ばない。当時のholdoutは既に参照されたデータで、新規blind最終評価ではない。原ラベルの設置誤差や測定面の詳細も未記録。MatplotlibのAxes3D警告は出るが、使用した2D図は保存・目視確認対象。

## 再現

原本を`src/analyze_field_recording.py:safe_extract_archive`で安全に展開し、ROOT直下へ4sessionを配置する（`holdout.tar.xz`は別の±0.15 m／0.90,1.15 mデータなので使用しない）。リポジトリrootから：

```bash
MPLCONFIGDIR=/tmp/theta_matplotlib python3 \
  Experimental_results/2026-10-07/distance_reference_analysis/historical_distance_comparison/compare_historical_distance.py \
  --session-root ROOT \
  --source-archive /home/robo25/Downloads/recoding/coding_20260807_6.tar.xz

MPLCONFIGDIR=/tmp/theta_matplotlib python3 -m unittest discover \
  -s Experimental_results/2026-10-07/distance_reference_analysis/historical_distance_comparison \
  -p test_historical_distance.py -v
```
