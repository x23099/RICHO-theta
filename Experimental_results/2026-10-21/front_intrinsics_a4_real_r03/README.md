# 前方魚眼・実A4 r03：上下分布不足は解消、校正計算は数値不安定で保留

## 結論

**r03は役に立っている。r02の54枚へ上側の3枚を追加でき、57枚で事前の画像分布条件を満たした。** 全体を撮り直す・すぐr04を撮る段階ではない。

ただし、通常経路のOpenCV内部校正は条件不良の例外で停止した。初期主点の高さを変える原因分離診断では初期姿勢まで求められるようになったが、その後の係数更新で再び停止した。**採用できるK/Dはまだ得られていない。距離誤差や床TFを測定できた結果ではない。** 次は既存57枚で計算・観測点の整合性を監査し、追加撮影が必要かはその後に判断する。

## 1. 入力・受入結果

- アーカイブ：`/home/robo25/Downloads/front_fisheye_intrinsic_a4_r03_20261021_182522_716.tar.xz`
- ローカル保存：`recordings/2026-10-21_front_intrinsic_a4_intake_r03/front_fisheye_intrinsic_a4_r03_20261021_182522_716/`
- [受入結果・元ファイルhash](intake_summary.json)、[受入script来歴](intake_wrapper_provenance.json)、[native原画像manifest](raw_sample_manifest.csv)。
- r02の不足を補う同じA4・20 mm・9×6内角の板固定撮影として解析。新たな格子寸法・平面性の実測を受けたわけではない。
- r02と要求1280×720/30 fps、V4L2の実取得報告（MJPG等）、device、全保存parametersは一致した。metadata一致だけで内部光学状態の完全一致を証明するものではない。
- 背景の見え方が変わっていても、カメラの取付姿勢・背景の違いだけで内部K/Dが変わったとは断定しない。床に対するTFは別問題。

| 項目 | r03の結果 |
|---|---:|
| raw / BEV / detection / CSV | 各3,268フレーム、整合PASS |
| 最終CSV時刻 | 109.188615 s |
| CSV時刻由来の平均記録レート | 29.926 fps |
| 全区間5フレーム間隔の検査 | 654枚 |
| 完全格子未検出 | 633枚 |
| 格子間隔中央値8 px未満 | 17枚 |
| 近重複 | 1枚 |
| r03の採用候補 | 3枚 |
| 既存No Signal画面との参照一致 | 0フレーム |

No Signal参照一致なしは、あらゆる信号異常がなかったことの証明ではない。[全フレーム信号参照監査](extraction_r01/signal_audit.csv)。

## 2. 追加できた画像と合併

3枚はr03 frame **2761 / 2771 / 2786**、CSV時刻92.086 / 92.421 / 92.920 s。格子間隔中央値は12.127 / 11.965 / 10.611 px。いずれもnative全画角画像を個別確認し、前方・左レンズの手持ち板であることを確認した。右の円や固定窓模様は使っていない。

- [frame2761](extraction_r01/raw_frames/raw_f002761.png)
- [frame2771](extraction_r01/raw_frames/raw_f002771.png)
- [frame2786](extraction_r01/raw_frames/raw_f002786.png)

元1280×720全画角を維持し、枠・注釈・切抜き・拡縮・色変更なし。[原画像hash manifest](extraction_r01/raw_frame_manifest.csv)、[確認範囲](target_review.json)。各角の人手サブピクセル確認済みとはしていない。

合併はr02の54枚を先に保持し、r03の3枚を時間順に追加。全先行画像との対称性込みRMS12 pxの重複検査を維持し、合併時に除外された画像は0枚。source sessionとframeを別々に記録し、単一動画の連番へ偽装していない。r02内のtrain/validation splitも維持した。

| 事前分布検査 | r02のみ | r02+r03 | 基準 |
|---|---:|---:|---:|
| 候補画像数 | 54 | 57 | 20以上 |
| train / 姿勢検証用 | 44 / 10 | 46 / 11 | 採用順5枚に1枚を検証用 |
| train角群の横方向範囲 / ROI幅 | 85.785% | 85.785% | 35%以上 |
| train角群の縦方向範囲 / ROI高 | 23.573% | **50.522%** | 35%以上 |
| train格子中心の3×3区画数 | 3 | **4** | 4以上 |

上端はy=31.066 pxまで増え、従来の下端y=394.823 pxと合わせて363.757 pxの縦範囲となった。**画像分布のscreen通過は校正精度の合格ではない**。上側3枚のうちframe2761は検証用、残る2枚はtrainに分割されている。検証用画像は同じ撮影系列からの姿勢検証で、別環境の独立holdoutではない。

[合併した角群・分布の数値グラフ](combined_candidate_r01/merged_coverage.png)、[合併データとfit前固定split](combined_candidate_r01/merged_observations.json)、[画像対応CSV](combined_candidate_r01/selected_view_manifest.csv)、[合併時の全判定](combined_candidate_r01/merge_decisions.csv)。

## 3. 通常校正の停止

[fit前固定した手順](method.md)どおり、既存4係数fisheye、既存flags・初期値・基準を変更せず実行した。

```text
CALIB_CHECK_COND - Ill-conditioned matrix for input array 44
in CalibrateExtrinsics
```

trainの配列44は、合併index55、**r03 frame2771**に対応する。`CALIB_CHECK_COND`を無効にしたり、その画像を残差から削除したりしていない。[通常経路の実行記録](combined_candidate_r01/run_summary.json)：`SOLVER_REJECTED_NO_APPROVED_INTRINSICS`。

この例外だけから、撮影者が失敗した・紙が曲がっている・画像が不要だ、と断定しない。OpenCV内部校正は非線形推定であり、入力と初期化、姿勢推定、更新の条件を切り分ける。

## 4. 初期値と更新段階の分離診断

通常経路の初期Kは、前方ROI全体の中央cy=359.5 pxを主点の初期値としていた。しかしnative画像の円形視野は上下に偏っており、ROIの中央が光学主点である保証はない。

D=0の初期モデルでのみ、r03上側の角を換算すると次の値になる。

| r03 frame | split | 通常初期cy=359.5の最大角 | 診断初期cy=300の最大角 |
|---|---|---:|---:|
| 2761 | pose validation | 89.978° | 73.263° |
| 2771 | train | 90.002° | 73.344° |
| 2786 | train | 92.675° | 76.008° |

**本当の視線角を測定した値ではなく、未校正の初期モデルでの換算値**。OpenCV実装はfisheyeの逆変換で正規化半径をπ/2へclipするため、初期モデルが境界付近になることは不安定要因として疑われる。[OpenCV 4.5.5の実装](https://github.com/opencv/opencv/blob/4.5.5/modules/calib3d/src/fisheye.cpp#L343-L377)

そこで、[別に固定した診断条件](initialization_diagnosis_method.md)として、**cy初期値だけを300 pxへ変更して1回試した**。約300 pxは原画像の円形視野を参考にした初期化の近似で、校正済み主点や固定主点ではない。K/Dは通常どおりtrainだけから最適化する。画像57枚・split・4係数・flags・誤差基準・条件数検査は全て維持。主点を含む初期値はさらに最適化されるパラメータという扱いは[OpenCV公式仕様](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html)に従う。

結果は再度条件数例外、今度はtrain配列27、**r02 frame1596**。[別診断の実行記録](initialization_diagnosis_r01/run_summary.json)。初期値変更だけでは校正完了に至らなかった。

さらにvalidationを使用せず、同じtrainと初期Kで反復回数上限だけ0 / 1 / 2にして、停止段階を確認した。

| 更新上限 | 結果 | 解釈 |
|---|---|---|
| 0 | 初期姿勢まで計算可能、残差1.251746 px | 内部係数は更新していない。**校正結果として採用不可** |
| 1 | 配列27の姿勢再計算で例外 | 最初の内部係数更新後に不安定化 |
| 2 | 同じ配列27で例外 | 継続しても同じ段階で停止 |

[反復段階のCSV](iteration_step_audit_r01/step_results.csv)、[条件と来歴](iteration_step_audit_r01/specification.json)。0回の残差を校正後RMSとして使わない。更新値が返っていないため、どの係数の更新が唯一の原因だったかまでは断定できない。初期値以外に、角検出、周辺画像の姿勢初期化、パラメータの識別性やモデル適合性も引き続き診断対象。

## 5. 保存したもの・未実施

- 完全なr03観測JSON、654行の検出CSV、3枚の未編集PNG、元画像・元動画hash。
- 複数session対応の57枚の合併データ、固定split、分布グラフ。
- 通常経路と別初期化診断の**両方の失敗結果**。成功結果として置き換えていない。
- 局所テスト8件PASS：合併session/frame保持、r02 split維持、分布再計算、hash衝突拒否、全体重複排除、native PNG/hash、初期角換算、診断式と既存coreの合成データ解の一致。
- 元の内部校正core、本番設定、ROS/TF、FFB、GPU/driver、原画像は変更していない。K/D候補の自動適用や実機駆動もしていない。
- 本番用K/D、検証画像の校正後RMS、物理距離誤差、camera→floor TF、別録画への転用は**未評価**。
- Git commit/pushは今回依頼されていないため未実施。以前のr01/r02成果も保全した。

## 6. 再現コマンド

repo直下、解析用Python環境で実行。実施済みの出力先への上書きは拒否する。intakeや抽出のやり直しは不要で、現在の凍結JSONから診断できる。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r03/intake.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r03/extract.py
MPLCONFIGDIR=/tmp/theta_intrinsic_mpl /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r03/merge_and_fit.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r03/initialization_diagnosis.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r03/audit_iteration_step.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_intrinsics_a4_real_r03/test_analysis.py -v
```

## 7. 次に進めること

**まず追加撮影ではなく、既存57枚による計算側と角座標の監査を続ける。**

1. 周辺画像の角並び・格子対応と、初期モデルでの姿勢解の整合性を調べる。画像や残差の都合で検証データを学習側へ移さない。
2. 更新で不安定になる係数、スケール、姿勢初期化を診断し、安定な最適化手段が必要かを判断する。変更する場合は別方式として通常経路と比較し、既存の失敗を残す。
3. 固定K/Dの姿勢検証に通る候補が得られてから、既存の床基準・73 cmコーンで物理距離を照合する。床TFは独立に扱う。

分布screenが通ったため「今後も絶対に追加撮影が不要」とは保証しない。ただし現時点の例外だけを理由に、撮影を繰り返してもらう根拠はない。
