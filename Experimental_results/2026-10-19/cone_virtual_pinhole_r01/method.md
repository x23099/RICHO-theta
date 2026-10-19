# 仮想ピンホール経路の比較：実行前に固定

既存7録画の同じ実観測下辺180,980列を、既存の3幾何候補で比較する。
新しいYOLO推論・校正fit・ROS/TF配信・FFB接続は行わない。
比較対象は距離精度改善の主張ではなく、座標変換の整合と画像格子への丸めの影響。

## 独立した二経路

1. 現行：`ground_contact.py`の等距離魚眼ray→床交点。
2. 提案経路：OpenCV `fisheye.undistortPoints`→仮想透視画素→K逆行列の光線→
   ROS軸の剛体変換→床平面との交点。

元の等距離仮定と同じ条件で比較するため、前レンズの仮定Kは
fx=fy=radius/(π/2)、cx/cyは既存の有効中心、OpenCV魚眼Dは4要素0。
これは**実測内部校正を新しく得たものではない**。魚眼D=0は理想等距離モデルで、通常ピンホールの無歪みと混同しない。

仮想カメラは960×960、水平/垂直FOV90°、fx=fy=480px、cx=cy=479.5px。
各レンズの正面方向を向き、光学中心を動かさない。画角を結果に合わせて調整しない。
画像面に入らない列は除外理由を残し、一部だけ切って全下辺の範囲を出さない。
主比較は浮動小数画素を保持。補助比較として仮想画素を最近傍整数へ丸めるが、
これは離散化感度であり、変換後YOLOの誤差や再学習成績ではない。

## TF相当の計算

仮想光学軸はROS optical（X右/Y下/Z前）。床基準はROSの向き（X前/Y左/Z上）、原点はカメラ直下。
既存の姿勢/高さをこの軸の4×4剛体変換へ換算し、回転の直交性・det=+1を検証する。
この床基準を実測済み`base_link` TFと称さず、実機TFやROSの時刻lookupを実行したとも扱わない。
現行独自軸のX右/Y上/Z前を、そのままROS TFの回転行列として配信しない。

床との交点、下向きray閾値、前方、水平距離0.2～4mは現行の診断条件を維持。
欠測/遮蔽の時間品質は既存r02のまま。候補値と観測値を分け、全frameを保持する。
数値同等性の確認許容値は1e-9m。物理測距の合格閾値ではない。

OpenCVの逆mapとremapで実際の透視画像もメモリ内に生成するが、保存しない。
元カメラ画像を加工したファイルは作らず、元解像度/画素は不変で保持。
同じ下辺の変換比較と、透視画像で再検出した場合の評価は明確に分ける。

根拠：
- OpenCV魚眼モデル/補正: https://docs.opencv.org/4.5.0/db/d58/group__calib3d__fisheye.html
- ROSピンホール画素→ray: https://github.com/ros-perception/vision_opencv/blob/rolling/image_geometry/include/image_geometry/pinhole_camera_model.hpp
- tf2剛体変換/座標系: https://github.com/ros2/geometry2/blob/rolling/tf2/README.md

これらは前の提案検討で参照した一次資料。実行環境はOpenCV4.5.5。
全出力 `floor_contact_verified=False, usable_for_ffb=False`。
