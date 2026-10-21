# angular内部校正の距離・床姿勢検証（実測ラベルへのfit前固定）

## 分けて検証するもの

1. 10/21チェッカーボードから得たangular KB4のK/Dを**固定**し、既存7配置の床白紙角・同一録画紙コーン2mのpixelを距離へ投影する。内部校正だけを変えた対照では、記録済みnominal回転・実測申告高さ59cmを保持する。
2. 白紙7配置のうち既存の調整5点（C080,C130,C200,L130,R130）だけで床に対する**回転3自由度**を推定。高さ59cm、カメラ直下の原点、K/Dは固定。H100/H160と別録画をfitへ入れない。各配置中央値を1点とし、多数の静止frameを独立の測量点として水増ししない。
3. 既存コーンの6,876frameの保存済み色先端/下辺proxyを再利用し、同じ観測点で、床交点と既知全高73cmの2視線解を比較する。新しいYOLO学習・推論・閾値選択は行わない。物理接地点未確認フラグを維持する。

## 座標・モデル

- raw1280×720・前方左レンズ。角は既存の主閾値170で固定し、誤差を見て閾値を変えない。
- 床点のユーザーX右/Z前の座標を、target x前/y左/z上へ `[Z,-X,0]` と写す。optical x右/y下/z軸との回転を明示する。
- `T_paper_ground_reference_from_front_optical`は今回の**オフライン条件付き候補**。実際のbase_linkへ登録するTFや、ROSで取得した実測TFではない。UIのcar_offsetを混入しない。
- K/D逆変換は正規化画素半径から、単調な角度多項式を二分法で逆解する。OpenCVの180°clipへ戻さない。最大角は候補が観測した94.55°付近までとし、別レンズ・native外・観測角域外は無効にする。単調性は宣言域内の導関数極値で確認する。
- 基準対照は従来理想等距離＋nominal回転＋59cm。比較する新モデルはangular＋nominal回転＋59cm、angular＋紙5点回転＋59cm。条件ごとの最良方式は選ばない。
- 回転fitはnominal Rにtarget軸のRodrigues増分を左から掛ける。pixel二乗誤差、linear loss、初期0の1条件、各増分±10°、3点数値微分、終了1e-12/最大300評価。境界到達・数値rankを記録。H100/H160のpixelやラベルはfit APIへ渡さない。
- 床交点は下向き入射cos>0.03の場合だけ。観測点が本当に床上という検証は別で、床へ投影したこと自体ではfloor contactを認定しない。
- コーン高さ解は `[s_tip R r_tip - s_base R r_base] = [offset,0,0.73]` の最小二乗。offset=0を主proxy、0.1875mを「台座手前辺→中心軸」の未確認仮定案として両方保存。高さから求めた底点の高さを0へ強制しない。旧実装の角度0.1°・条件数1e6・線分残差2cmの診断基準を維持。
- コーンの前後参照は台座の車体側の辺まで。左右±0.40mは内側辺であり、軸平行台座中心の±0.5875mと白紙の角の±0.40mは混同しない。今回は前方Zの条件付き差と3D整合性を主に評価し、赤色proxyのXを台座中心の正解に昇格しない。

## 録画間転用の制限

録画metadataのnative寸法・capture報告・幾何設定・不足情報を比較し、ファイルhashを確認する。metadata一致だけでserial/firmware/内部補正/取付姿勢の完全同一を証明しない。撮影者の「高さ・傾きを意図的に変更していない」という回答を否定する根拠として扱わない。

白紙7点の2m中央値(309,378)と10/19同一録画の(313,371)は、既に別画素である。この差を校正後も隠さず確認する。別録画1点へTFを合わせ直して7点fitの検証成功と見せない。同一録画の紙前/コーン/紙後も独立3地点とは数えない。

追加撮影、本番設定、ROS送信、TF配信、FFB、安全ゲート、GPU/driver、旧結果は変更しない。検証結果は全てusable_for_ffb=false。

参照：[既存原画像/座標監査](../../2026-10-19/cone_recording_coordinate_audit_r01/README.md)、[白紙7点の確認](../../2026-10-15/paper_reference7_r01/README.md)、[紙コーン同一録画](../../2026-10-19/paper_cone_2m_validation_r01/README.md)、[既知高さproxy](../cone_known_height_pinhole_r01/README.md)、[ROS公式REP103](https://github.com/ros-infrastructure/rep/blob/master/rep-0103.rst)、[Kannala–Brandt角度モデル](https://users.aalto.fi/~kannalj1/calibration/Kannala_Brandt_calibration.pdf)、[OpenCV回転表現](https://docs.opencv.org/4.5.5/d9/d0c/group__calib3d.html)。
