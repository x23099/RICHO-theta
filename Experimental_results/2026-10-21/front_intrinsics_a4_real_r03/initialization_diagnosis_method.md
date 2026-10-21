# 初期値原因の分離診断（通常fit失敗後、診断fit前固定）

通常経路の57枚・固定splitは事前分布条件を満たしたが、OpenCV 4.5.5の`CalibrateExtrinsics`がtrain配列44（r03 frame2771）で条件不良として停止した。全画像や元の失敗結果を残す。

既存のK初期値はROIの上下中央cy=359.5 px。raw画像の円形視野はこの高さを中心としていない。D=0でframe2771の最外角を換算すると約90.002°、次のtrain画像frame2786は約92.675°となる。これは本当の光線角の測定ではなく、初期モデルでの値。OpenCVはfisheyeのundistortで正規化半径をπ/2へclipする実装を持ち、初期姿勢推定の不安定要因が疑われる。

**診断は1条件だけ**：fx=fy=640/π、cx=319.5、D=0を保ち、cy初期値だけ300 pxへ変更。約300 pxはnative画像で見える前方円の中央付近という初期化の近似で、主点の実測値・固定値ではない。fit中はfx,fy,cx,cyとDを通常どおり最適化する。

- 57枚・46train/11validation・角座標を全て維持。残差を見た除外・split変更なし。
- 4係数fisheye、CALIB_CHECK_CONDを含むflags、反復終了条件、分布/誤差/法線/単調性のscreenを維持。条件不良検査を無効にしない。
- K,Dはtrainのみから求め、validationでは固定K,Dでposeだけ解く。初期値をvalidation残差で何通りも探索しない。
- 既存coreを書き換えて履歴hashを無効化せず、今回だけの別診断ファイルにfit・同じ検証式を明示する。既存初期値を与えた場合の拒否と、合成データでcoreと同じ解になることをテストする。
- この診断が良くても本番採用しない。通常fitの失敗は取り消さず、別経路の数値的候補として保存。物理距離、床TF、別録画への転用は未検証。

出典：

- [OpenCV公式fisheye校正API](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html)：USE_INTRINSIC_GUESSは初期値、CHECK_CONDは条件数の検査。
- [OpenCV 4.5.5 fisheye.cpp](https://github.com/opencv/opencv/blob/4.5.5/modules/calib3d/src/fisheye.cpp#L343-L377)：正規化半径とπ/2 clip。
- [同CalibrateExtrinsics](https://github.com/opencv/opencv/blob/4.5.5/modules/calib3d/src/fisheye.cpp#L1289-L1321)：初期姿勢・姿勢refineと条件数例外。
