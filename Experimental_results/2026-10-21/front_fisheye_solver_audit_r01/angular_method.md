# Z=0境界の監査とangular KB4比較（比較fit前固定）

最初のjoint検証はRMS0.613 / 0.755 pxと事前誤差screen内へ下がったが、train index33（r02 frame1596）の最小Zが約1.64e-9 mに張り付き、最適化のoptimalityは約2.38e5だった。xtol終了だけを十分な収束と扱わず、この候補は採用しない。元の結果・全角を残す。

前回OpenCVがcy=300の更新時に停止したのも同じframe1596。OpenCVの投影はX/Z、Y/Zのpinhole座標からatan(r)を使い、逆変換も正規化半径をπ/2へclipする。Z=0をまたぐモデルの定義域が原因候補。カメラの実画角や全角の真の方向を独立測定したわけではなく、現段階で「実レンズが必ず何度」とは断定しない。

## 別方式として比較する条件

- theta=atan2(sqrt(X²+Y²),Z)、radial=theta+k1 theta³+k2 theta⁵+k3 theta⁷+k4 theta⁹、u=fx radial X/rho+cx、v=fy radial Y/rho+cy。
- Z>0では既存OpenCV4係数の投影と一致する。Z<=0も連続に扱うangular KB4として**別schema**へ保存し、OpenCVの全画角undistortへそのまま読み込めるとは扱わない。背面の光軸そのもの（反対極）・カメラ中心は投影不可。
- 従来方式の更新ロジック修正や単なる初期値調整ではなく、投影の定義域を変える診断。通常方式と旧joint方式の失敗・境界停止は取り消さない。
- 同じ57枚、同じ46 train/11 validation、同じ初期K/Dの1条件、同じ等重みpixel二乗誤差。画像・角の削除、再精密化座標への置換、split変更なし。
- 初期姿勢は旧jointと同じ、OpenCV初期化のみ。学習は全内部係数とtrain姿勢を同時TRF最適化。解析微分を中央差分・OpenCVとの前方域一致・Z=0前後で検証。
- validationではK/Dを固定し、初期K/D=0による初期PnPの後、angular pixel誤差で各6姿勢だけを最適化する。旧方式の最終undistort→PnPとは異なるが、同じnative pixel RMSを報告する。独立環境holdoutではない。
- 既存の誤差・分布・normal spread・focal比・主点・観測範囲の単調性screenを維持。加えて、trainの列normで正規化した勾配max<1e-4、validation各poseも同じstationarity、収束、角度が反対極未満、train姿勢条件数<1e6、poseを消去した共通8変数の数値full rankを検査する。
- 「全点Z>0」は広角angularモデルの物理条件ではないため適用しない。代わりに観測角度とZ<=0の点数を明記。単調性はtrain/validationを含む観測角度範囲で診断するもので、実レンズの全視野・物理距離精度の証明ではない。
- TRF・linear loss・300評価上限・1e-9終了条件・LSMR・広いoverflow防止境界は旧jointと同じ。GPU/driver変更なし。本番・ROS・TF・FFBへは適用しない。

## 参照

- [Kannala & Brandt 原論文（著者公開PDF）](https://users.aalto.fi/~kannalj1/calibration/Kannala_Brandt_calibration.pdf)：視線角からの多項式投影。実装は今回の等方radial4係数で、論文の全非対称拡張ではない。
- [OpenCV4.5.5実装](https://github.com/opencv/opencv/blob/4.5.5/modules/calib3d/src/fisheye.cpp)：projectPointsのpinhole中間座標、undistortPointsの180°制限とclip。
- [SciPy1.11.4仕様](https://docs.scipy.org/doc/scipy-1.11.4/reference/generated/scipy.optimize.least_squares.html)：TRF、終了条件、Jacobian scaling。
