# 既存57枚による校正停止の診断：広角angular方式で候補作成

## 結論

**追加撮影なし・全57枚のまま、内部校正の数値候補を得た。** 学習用46枚の再投影RMSは **0.328918 px**、K/D推定に使わなかった11枚の姿勢検証RMSは **0.435897 px**。元の分布条件・誤差基準を下げたり、画像・角を除外したりしていない。

ただし、これは**画像上の角の再現性がよいオフライン候補**。実距離でのcm誤差、床に対するカメラTF、別録画への転用、実機FFBはまだ検証していない。本番へは適用していない。最終候補は[angular結果](angular_results_r01/summary.json)、詳細な[候補JSON](angular_results_r01/angular_diagnostic_candidate.json)。

## 何が原因候補だったか

前回の通常OpenCV校正はr03 frame2771で条件数例外、cy初期値を変えた場合も係数更新後にr02 frame1596で停止した。

今回はまず、同じOpenCVの4係数投影を保って、内部係数と画像姿勢を同時にtrust-regionで更新する別解法を試した。誤差自体は0.613 / 0.755 pxまで下がったが、**r02 frame1596の1点がカメラZ=0境界へ張り付き、十分に収束していなかった**。終了コードやRMSだけでは採用できないと判断した。

OpenCVのfisheye投影は中間でX/Z、Y/Zを使い、逆変換には180°視野の制限・clipがある。[OpenCV4.5.5公式実装](https://github.com/opencv/opencv/blob/4.5.5/modules/calib3d/src/fisheye.cpp)

そこで、視線角を`atan2(横方向の半径, Z)`で直接表すangular KB4へ投影の定義域を変更した。Z=0の前後でも連続し、Z>0では元の4係数投影と一致する。角度多項式は同じ4係数で、係数を増やして誤差を小さくしたのではない。[Kannala–Brandtの著者公開論文](https://users.aalto.fi/~kannalj1/calibration/Kannala_Brandt_calibration.pdf)

この方式では、数値解の勾配も十分小さくなり、観測点の一部を光軸から90°より外側に推定できた。**モデルの定義域と逐次更新が不安定化に関係したことを支持する結果**だが、実カメラの全視野や物理的光線角を独立に測定した証明ではない。

## 方式比較

| 方式 | train RMS | 姿勢検証RMS | 状況・採否 |
|---|---:|---:|---|
| 通常OpenCV、元初期値 | 未取得 | 未取得 | 条件数例外で停止。元結果を保持 |
| 通常OpenCV、初期cy=300 | 未取得 | 未取得 | 更新後の姿勢推定で停止。元結果を保持 |
| OpenCV投影＋joint TRF | 0.613162 px | 0.754876 px | Z=0境界停止。**採用しない** |
| angular KB4＋joint TRF | **0.328918 px** | **0.435897 px** | 十分な収束・事前誤差screen等を満たすオフライン候補 |

旧jointの`results_r01/summary.json`では限定的な事前screenが全trueだが、追加監査で境界停止が判明したため採用しない。旧ファイルの値や判定を後から成功・失敗へ書き換えてはいない。上表と本報告がその後の解釈を記録する。

関連図：[投影定義域・収束・誤差の比較](plots_r01/solver_domain_comparison.png)、[画像ごとの誤差と角監査](plots_r01/per_view_and_corner_audit.png)。全て数値から生成した図で、カメラ原画像への描画・編集ではない。

## 入力と固定条件

- 入力：[r02+r03の57枚と固定split](../front_intrinsics_a4_real_r03/combined_candidate_r01/merged_observations.json)。元r02=54枚、r03=3枚。
- 46 train / 11 pose validation。K/Dはtrainのみから求める。validationではK/D固定で各画像の姿勢6変数のみ推定。同一撮影系列の内部検証であり、独立した環境holdoutではない。
- 1280×720、前方左レンズ、9×6内角、20 mm格子。元native角とPNGは変更なし。
- 初期Kはfx=fy=640/π、cx=319.5、cy=300、D=0の1条件。validation残差で初期値を探索していない。
- 全点同じ重みのpixel二乗誤差。robust loss、残差による削除、再精密化座標への差し替えなし。
- 基本条件：[旧jointの実行前条件](method.md)、[angular方式の実行前条件](angular_method.md)。
- 最適化は既存環境のSciPy1.11.4 TRF/LSMR、CPU、解析Jacobian。GPU・driverの変更、追加インストールなし。[使用したSciPy版の公式仕様](https://docs.scipy.org/doc/scipy-1.11.4/reference/generated/scipy.optimize.least_squares.html)

## 角の対応を調べた結果

全57画像の角を対象に、セルの向き・格子間隔、3 px窓のcornerSubPix、従来型チェッカーボード検出器との比較を行った。[全監査CSV](results_r01/corner_audit.csv)

| 項目 | 結果 |
|---|---:|
| セル向きの折返しなし | 57 / 57画像 |
| cornerSubPixによる画像ごとの移動RMSの中央値 | 0.198084 px |
| 同・最大 | 2.088271 px |
| 従来型検出器でも全角を検出できた画像 | 25 / 57画像 |
| 従来型と元SB角群の差RMSの中央値（検出25枚） | 0.191039 px |
| 同・最大 | 2.108945 px |

一部の再精密化量が大きい画像もあり、全角が正解座標だと断定していない。古典検出器で未検出の画像を誤検出扱いにもしない。**監査座標はfitへ使用せず、元のSB座標を全て維持した。** 全画像の全角について、人がサブピクセル精度で確認したという意味でもない。

## 得られたangular候補

native1280×720、左レンズ座標の内部行列：

```text
K = [[190.682847,   0.000000, 319.830444],
     [  0.000000, 190.247263, 317.613558],
     [  0.000000,   0.000000,   1.000000]]
D = [-0.04034744, 0.03556701, -0.01382497, 0.00106715]
```

これは**`kb4_atan2_angular`**という別schema。OpenCVの4係数と前方域の投影形は一致するが、全視野を既存の`undistortPoints`へそのまま渡して互換と扱わない。

| 候補検査 | 結果 |
|---|---:|
| train / validation aggregate RMS | 0.328918 / 0.435897 px |
| 画像ごとの最大RMS（train / validation） | 0.730128 / 0.989812 px |
| 法線方向の最大広がり | 89.8428° |
| 推定された観測角の最大 | 94.5504° |
| 90°を超える推定角の点 | 23 / 全3,078角 |
| その点を含む画像 | 合併index27,33,37,56の4枚（全てtrain） |
| 列normで正規化した勾配max | 9.2864e-6（追加基準1e-4未満） |
| poseを除去した共通8変数の正規化profile条件数 | 454.380、数値rank8 |
| 最適化評価回数 | 16、ftol終了 |

最大角は**推定モデル内の角度**であり、物理的なレンズ画角189.1°を測ったと解釈しない。数値rankや再投影誤差も、機器の取付・物理寸法・録画間転用の不確かさを含む精度保証ではない。

観測範囲でのradial単調性、各姿勢の数値条件、validation姿勢の収束、画素再現誤差など12検査が全true。ただし`usable_for_ffb=false`、`physical_floor_distance_verified=false`を維持。

## 検証・来歴

- 新しい2方式のJacobianを中央差分で照合。angular方式はZ=0前後の連続性・微分、Z>0でのOpenCV一致、合成K/D回復をテスト。
- 検証用角だけを変更してもtrainで求めたK/Dがバイト同一であることをテストし、validationから内部係数へ漏れていないことを確認。
- 関連テスト38件PASS：新規8、既存内部校正15、床面幾何15。
- SciPy未導入を模擬した2テストモジュールのskip分岐もPASS。SciPyがない実機PCの通常preflightに、診断用依存を強制しない。
- 凍結結果に使ったテスト原本は[source snapshots](source_snapshots/README.md)へ保存。optional import guard追加後のテストと区別し、当時のhashを検証できるようにした。
- [成果物検証](verification.json)：30ソース、9出力hash、57枚のnative PNGと固定splitを確認。原画像・原座標・coreの過去結果は保全。
- `git diff --check`も実施。本番アプリ、ROS、TF、FFB、GPU/driver、旧内部校正coreは変更していない。Gitのcommit/pushは今回依頼されていないため未実施。

## 再現

以下は実施済みコマンド。出力先の上書きは拒否する。生録画の再抽出や撮り直しは不要。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/run.py
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/run_angular.py
env MPLCONFIGDIR=/tmp/theta_intrinsic_mpl /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/plot.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/verify_artifacts.py
env OPENBLAS_NUM_THREADS=1 PYTHONPATH=src /home/robo25/theta-env/bin/python3 -m unittest discover -s tests -p 'test_fisheye_*py' -v
```

通常アプリは新しい診断モジュールをimportしない。SciPy未導入環境でこの診断を明示実行するには別途依存が必要だが、こちらでは環境を変更していない。

## 次の作業

1. この候補のモデル種別・native座標・観測角範囲を明示したまま、既存の床基準・既知寸法コーン録画で照合する。現時点では追加撮影不要。
2. 録画間で内部光学状態が同じかの監査と、カメラに対する床のTF推定を分離する。チェッカーボードの姿勢を床TFに流用しない。
3. 実測距離との誤差と独立条件での妥当性を確認してから、前方の必要画角をピンホール画像へ変換する経路や距離/TTCへ接続する。カメラ画像を報告用に編集することとは別の処理として扱う。
4. FFBへつなぐのはその後。今回得たK/Dを既存JSONへ直接上書きして実機起動しない。
