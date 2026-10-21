# 前方魚眼・実A4 r02：候補54枚、上下分布不足により内部校正保留

## 結論

同じ20.0 mm格子を平らな板へ貼ったことを撮影者に確認した。r01の6枚から、前方レンズの非重複候補は**54枚**へ増えた。しかし角群が画像の横長の帯へ偏り、事前に固定した分布基準に達しない。**内部校正ソルバーは実行していない。新しいK/D・TF・距離精度の結果はない。** 判定は `NO_FIT_INSUFFICIENT_OBSERVATIONS`。

既存の54枚を廃棄して撮り直す必要はない。同じ撮影モード・取付で、特に画像上側の観測を補う方針とする。[不足部分だけの撮影手順](capture_upper_supplement.md)。合併できる撮影状態かの確認、対象識別、固定したtrain/validationの選定、校正・距離検証は次工程。

## 入力・受入

- アーカイブ：`/home/robo25/Downloads/front_fisheye_intrinsic_a4_r02_20261021_173517_156.tar.xz`
- ローカルsession：`recordings/2026-10-21_front_intrinsic_a4_intake_r02/front_fisheye_intrinsic_a4_r02_20261021_173517_156/`
- 対象：9×6内角、1マス20.0 mmの移動する手持ち格子のみ。窓の固定模様と後方レンズは使用しない。
- [受入結果・hash](intake_summary.json)、[受入wrapper来歴](intake_wrapper_provenance.json)、[撮影者確認](user_confirmation.json)。

| 項目 | 結果 |
|---|---:|
| raw / BEV / detection / CSV | 各4,480フレーム、整合PASS |
| 最終CSV時刻 | 159.924 s |
| CSV時刻由来の平均記録レート | 28.010 fps |
| 生画像サイズ | 1280×720 |
| 5フレーム間隔の全区間検査 | 896フレーム |
| 完全格子未検出 | 695 |
| 格子間隔不足（中央値8 px未満） | 67 |
| 既採用画像との近重複 | 61 |
| 無信号参照と一致した検査画像 | 19 |
| 非重複候補 | 54 |

54枚は画像上の重複判定を通った候補であり、54個の独立した3D姿勢や、全角の人手検証完了を意味しない。[代表画像の目視確認範囲](target_review.json)。

## 内部校正前の分布検査

判定条件は抽出前に[method.md](method.md)へ固定した既存基準。良い残差が出るまで抽出条件やsplitを変える処理は行っていない。

| 検査 | r02 | 既存基準 | 判定 |
|---|---:|---:|---|
| 候補画像数 | 54 | 20以上 | PASS |
| train / 姿勢検証用split | 44 / 10 | 5枚ごとに1枚を検証用 | 固定 |
| train角群の横方向範囲 / ROI幅 | 85.785% | 35%以上 | PASS |
| train角群の縦方向範囲 / ROI高 | 23.573% | 35%以上 | 不足 |
| train格子中心の3×3区画数 | 3 | 4以上 | 不足 |

train角群の上下端は **y=225.100～394.823 px**、縦の範囲は169.723 px。基準はROI高720 pxに対する252 pxであり、画面中央付近を左右に移動するだけでは不足する。これは「距離誤差が何cmだった」という結果ではなく、歪み係数を求める前の観測分布検査である。

[分布・格子サイズの数値グラフ](exports_r01/coverage_diagnosis.png)。元画像へ点を重ねた画像ではなく、角座標から生成した数値グラフ。3×3区画線はROI上の検査区画であり、円形の実際の視野境界ではない。

### 既存映像の救済確認

上側または下側にある「完全格子は見つかったが小さい」フレームの前後±20フレームを、既抽出フレームを除いて追加検査した。選択は内部校正・残差評価前に[selection.json](dense_limits_audit_r01/selection.json)へ保存。

- 追加検査168枚：完全格子未検出129枚、格子間隔不足39枚。
- 基準を満たす新しい非重複候補：**0枚**。
- 検出器、8 px基準、12 px近重複基準、前方ROIを変更していない。
- 全未抽出フレームを検査したという意味ではない。全区間5フレーム間隔の検査と、不足領域付近の毎フレーム検査の結果。

[追加検査CSV](dense_limits_audit_r01/attempts.csv)、[結果・ソースhash](dense_limits_audit_r01/summary.json)。

## 無信号表示と対象の区別

元映像のframe377～472（CSV時刻14.994639～25.441412 s）の96フレームが、目視確認した[frame472のNo Signal表示](raw_samples/raw_f000472.png)と一致した。平均画素差1.0以下を用いた参照一致であり、USB抜去、カメラの故障、信号復帰後の内部設定変更まで診断した結果ではない。無信号区間を格子検出に使っていない。

[全4,480フレームの信号監査](exports_r01/signal_audit.csv)、[区間CSV](exports_r01/no_signal_intervals.csv)。受入の動画・CSV整合PASSだけでは、有効映像が全区間存在するとは言えない。

紙を後方へ持って回った区間は右の円に映るため、前方レンズのK/Dへ加えない。窓の固定格子は点群全体が背景領域内かで除外し、大きな前景紙がその領域を覆うだけで除外しない。代表採用画像で手持ち板であることを確認したが、全54枚の全54角を目視サブピクセル確認した結果ではない。

## CSV書出しエラーと回復

最初の[extract.py](extract.py)は、全検出完了・[完全なobservations.json](extraction_r01/observations.json)保存後に、採用フレームだけに存在する列のCSV書出しで停止した。`extraction_r01/attempts.csv`は**途中までの不完全ファイルなので集計に使用しない**。

抽出ソースのhashと原画像を変更せず、[recover_exports.py](recover_exports.py)で全行の列名の和集合を指定し、別フォルダ`exports_r01/`へ896行を回復した。動画を再デコードして信号監査を完了し、54枚のPNG hash・decoded BGR hash、入力ファイルhash、再計算した分布が一致することを検証した。角検出のやり直し・候補選別の変更はしていない。

正式なCSVは[exports_r01/attempts.csv](exports_r01/attempts.csv)、[54枚の未編集画像manifest](exports_r01/raw_frame_manifest.csv)。回復状況と出力hashは[recovery_summary.json](exports_r01/recovery_summary.json)。最初のCSVと抽出scriptは証跡のため残した。`extract.py`を再実行する通常経路が修正済みという意味ではない。

## 検証と再現

既存出力の上書きは禁止。以下は実施済みコマンドで、再実行すると既存出力検査で停止するものがある。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r02/recover_exports.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r02/audit_sparse_limits.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r02/calibrate.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r02/test_analysis.py -v
PYTHONPATH=src /home/robo25/theta-env/bin/python3 -m unittest discover -s tests -p 'test_fisheye_intrinsic_calibration.py' -v
PYTHONPATH=src /home/robo25/theta-env/bin/python3 -m unittest discover -s tests -p 'test_fisheye_floor_geometry.py' -v
```

- 局所検証7件PASS：任意列CSVの回復、native参照の寸法、信号区間の分離、窓と前景板の区別、追加検査の選択、実54枚がソルバー前に拒否されること。
- 既存内部校正テスト15件PASS、床面幾何テスト15件PASS。合計37件PASS。
- [候補作成の実行記録](candidate_r01/run_summary.json)：事前分布不適合により `intrinsic_solver_attempted=false`。
- matplotlibの3D拡張警告は出たが、今回の2Dグラフ生成・テストは完了。
- 生画像の切抜き・描画・拡縮・色変更なし。本番設定・TF・FFB・GPU/driver変更なし。実カメラやハンコンは起動していない。Gitのcommit/pushは今回依頼されていないため未実施。

## 次工程

1. r02を残したまま、[前方画像上側の補足収録](capture_upper_supplement.md)。取付・出力座標系が同じかを確認する。
2. 追加録画の角抽出と対象確認。fit前に合併・splitと分布を確定する。枚数や分布だけで合格を保証しない。
3. 内部K/Dをtrainのみで推定し、固定K/Dで検証用姿勢の再投影と歪みの妥当性を確認する。
4. 合格後も床基準・既知寸法コーン・camera→floor TFの距離検証は別途行う。校正ボードの姿勢を床TFと取り違えない。
