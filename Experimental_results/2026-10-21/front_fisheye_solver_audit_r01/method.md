# 既存57枚・角対応とjoint最適化の比較条件（実行前固定）

## 目的と変更範囲

通常OpenCV fisheye校正が停止する原因を、撮影や画像除外に帰着させず診断する。r03合併の57枚とその46 train / 11 validationをそのまま使用し、本番coreや既存観測hashは変更しない。

- まず全57枚のnative角を監査：隣接セルの向き・格子間隔、3 px窓のcornerSubPixによる再精密化量、従来型検出器で検出できた場合の角群差。これは正解座標の測定ではなく、別手法による整合性診断。再精密化座標はfitへ代入しない。原画像に枠を描いたり編集画像を保存したりしない。
- 既存OpenCV4係数のprojectPointsとその解析Jacobianを使用。モデル、native座標、点数、等重みpixel二乗誤差は同じ。
- 通常経路は内部係数の更新後に各姿勢を再初期化する。今回の別解法はSciPy least_squaresのtrust-region reflectiveで共通8内部係数と各画像の6姿勢を同時に更新する。途中で姿勢を毎回初期化し直さない。
- loss=linear。robust loss・残差に基づく画像/点の間引き・外れ値除去・validationの再分割は行わない。
- 初期Kは前診断と同じfx=fy=640/π、cx=319.5、cy=300、D=0の1条件。OpenCVの反復0回で計算可能だった初期姿勢をtrainだけから求める。ボード原点を中心へ移すのは数値的な変数変換であり、画像座標変更ではない。fx/fy・ボード中心tzはlog変数で正値化。
- 初期化のためのOpenCV呼出しでは既存flags15を維持。joint更新は別optimizerなのでOpenCV CALIB_CHECK_CONDの更新時検査と同一ではない。収束後に全train姿勢のJacobian条件数を同じ1e6未満で追加診断する。元のcoreでCHECK_CONDを無効化する対応ではない。
- TRF、解析疎Jacobian、x_scale=jac、LSMR、線形誤差。最大300評価、ftol/xtol/gtol各1e-9。LSMR正則化あり。f=1～10000 px、主点は前方ROI、中心z=1e-6～1000 mという広い有限境界でoverflowを防ぐ。物理校正値のpriorではない。
- K,Dはtrainだけから推定。validationは固定K,Dで既存と同じundistortPoints→ITERATIVE solvePnPにより姿勢だけを推定する。validationで初期値を探索しない。
- 従来のtrain RMS<=1 px、validation RMS<=1.5 px、normal spread>=15°、主点/focal ratio/観測範囲の単調性を維持し、optimizer収束、全ボード点がカメラ前方、train姿勢条件数も確認する。合格してもoffline診断候補で、物理距離・床TFは未検証。
- 依存：既にこの解析環境へ入っているSciPy1.11.4（BSD系）、OpenCV4.5.5、NumPy。CPUのみ、GPUやdriverの更新・追加インストールなし。SciPyはこの診断モジュールだけの任意依存で、通常アプリには読み込ませない。joint方式は逐次方式より変数数と計算量が増えるためリアルタイム経路には入れない。

## 根拠

- [OpenCV4.5.5 projectPoints / Jacobian](https://docs.opencv.org/4.5.5/db/d58/group__calib3d__fisheye.html)：内部係数・姿勢の微分と4係数投影。
- [OpenCV4.5.5実装](https://github.com/opencv/opencv/blob/4.5.5/modules/calib3d/src/fisheye.cpp)：校正更新後のCalibrateExtrinsics呼出し、Jacobian列順。
- [SciPy1.11.4 least_squares公式仕様](https://docs.scipy.org/doc/scipy-1.11.4/reference/generated/scipy.optimize.least_squares.html)：TRF、疎行列、x_scale、linear loss、LSMR。

Jacobianを数値微分と照合し、合成データでの回復・validation変更でtrain解が変わらないことを検証してから、実データ候補を解釈する。
