# 2026年8月25日 照明補正候補の比較

## 1. 結論

固定HSVの前段へCLAHE、Gray-World、Shades-of-Grayを追加しても、新環境`z=0.8 m`遮蔽を
他条件の性能を維持したまま回復できなかった。比較した全方式を不採用とする。

録画メタデータにはISO、シャッター、露出、ホワイトバランスの状態が保存されていなかった。
次はカメラ側の露出状態を記録し、可能なら露出固定のA/B録画を行う。後処理候補を増やす前に、
入力画像の変動を管理できるか確認する。

## 2. 調査した方式

- 補正なし
- HSVのVチャンネルへCLAHE
- Gray-World
- Shades-of-Gray（Minkowski power 6）
- Shades-of-Gray後にCLAHE

CLAHEは局所タイル単位でヒストグラムを均等化し、clip limitでノイズ増幅を制限する。色恒常化は
シーン統計から照明色を推定するが、局所影の補償を保証しない。本比較では前回選んだ
`raw_ground_distance`、面積しきい値`2000`、NIS`9.210`、2フレーム確認を固定した。

参考:

- [OpenCV: CLAHE](https://docs.opencv.org/4.10.0/d2/d74/tutorial_js_histogram_equalization.html)
- [Zuiderveld, Contrast Limited Adaptive Histogram Equalization](https://www.cse.unr.edu/~bebis/CS474/StudentPaperPresentations/Constrast-Limited%20Adaptive%20Histogram%20Enhancement.pdf)
- [Finlayson and Trezzi, Shades of Gray and Colour Constancy](https://library.imaging.org/admin/apis/public/api/ist/website/downloadArticle/cic/12/1/art00008)

## 3. 新環境での結果

| 方式 | 箱なし生検出 | 0.8 m正常採用 | 1.0 m正常採用 | 1.3 m正常採用 | 判定 |
|---|---:|---:|---:|---:|---|
| 補正なし | 100.0% | 0.0% | 99.7% | 99.7% | FAIL |
| CLAHE | 100.0% | 0.7% | 99.5% | 93.0% | FAIL |
| Gray-World | 100.0% | 0.0% | 99.7% | 99.7% | FAIL |
| Shades-of-Gray | 31.7% | 91.3% | 71.0% | 78.9% | FAIL |
| Shades-of-Gray + CLAHE | 45.3% | 0.4% | 70.5% | 52.2% | FAIL |

Shades-of-Grayは箱なし背景の青候補を減らしたが、青箱自体の色も変化させ、全距離で正常観測を
大量に失った。また0.8 mの最大`abs(vz)`は`0.436 m/s`で上限`0.30 m/s`を超えた。
CLAHEは暗い青箱を回復せず、1.3 mを回帰させた。

新環境で合格候補がなかったため、旧環境への追加回帰は実行していない。

## 4. 実装

- 照明補正候補をオフライン解析から選択可能にした。既定は`none`であり現行画像を変更しない。
- カメラ接続時にOpenCV/V4L2から解像度、FPS、FourCC、自動露出、露出、ゲイン、明るさ、
  コントラスト、彩度、自動ホワイトバランス等を読み取る共通処理を追加した。
- preflightのカメラ結果へ露出関連値を表示する。
- 新規録画の`metadata.json`へ`camera_capture_properties`を保存する。
- カメラプロパティは読み取りのみで、自動露出や露出値の変更は行わない。

matunuc上のV4L2確認では、公開されたUser Controlsはbrightness、contrast、saturation、hueのみで、
露出、ゲイン、ホワイトバランス制御はなかった。OpenCVの各プロパティも`-1`であり、現在の
UVCインターフェースから露出固定はできないと判断する。

初期状態は`YUYV 1280x720 10 fps`だった。一方、対応形式一覧では`MJPG 1280x720`が
60/50/30/20/10 fpsに対応し、コードが従来要求していた24 fpsは非対応だった。このため今後は
MJPG 30 fpsを明示要求し、CSVの時刻は処理遅延の影響を受けない単調時計を正とする。

## 5. 次の作業

1. MJPG 30 fpsを要求するpreflightで、reported FPSと実読み取りFPSを再確認する。
2. 10秒程度の録画で、動画FPS、CSVの単調時計、有効FPSが整合することを確認する。
3. UVCから露出固定できないため、HSV輪郭方式を延命せず、学習済み物体検出または形状を含む別検出器を
   開発データで比較する。

## 6. 成果物

- `2026-08-25_illumination_preprocessing_new.csv`
- `src/camera_capture_properties.py`
- `src/analyze_hsv_value_thresholds.py`
