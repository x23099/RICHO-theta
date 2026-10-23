# コーンの距離表示付き解析画像

ユーザー依頼により、**元画像を変更せず、別ファイルの解析図にそのframeの推定距離を表示**した。
これは撮影時の画面/リアルタイム動作のスクリーンショットではなく、録画後に再計算・模擬評価した結果の可視化。
AI画像生成による写真や数値の描き直しは使わず、CSVの値と元PNGを埋め込む再現可能なSVGを生成しPNGへ描画した。

## すぐ見る

[3画像をまとめて見るHTML](visualizations_r01/index.html)

| 画像 | 申告設置Z | そのframeの推定Z | 録画frame / 時刻 |
|---|---:|---:|---|
| [中央1.30 mのPNG](visualizations_r01/cone_130_distance_f000719.png) | 1.30 m | **1.326 m** | 719 / 24.022 s |
| [中央2.00 mのPNG](visualizations_r01/cone_200_distance_f001333.png) | 2.00 m | **1.974 m** | 1333 / 44.556 s |
| [遮蔽・距離保留のPNG](visualizations_r01/occlusion_hold_distance_f001134.png) | 2.00 m | **保留・数値なし** | 1134 / 37.928 s |

PNGはスライドに利用可能。画像内に「録画後の再計算」「条件付き診断値」「物理距離・接地点未検証」を明記した。
申告設置Zは**カメラ直下から台座の車体側の辺まで**。推定Zは前後方向で、斜めの半径距離ではない。
近い2例の提示を、全録画/全距離の精度保証にしない。

## 使用した結果

撮影元：`floor_cone_same_pose_r01_20261015_160621_378`（2026-10-15）。
[処理完了待ちの比較](../causal_availability_latency_r01/README.md)の
`local_three_pass_median`＋最新scene入力処理中は保留する対照を使用した。
現在PCで計測したscene時間による模擬条件で、実験当日の遅延や実機FFBの再現ではない。

数値は[元CSV](../causal_availability_latency_r01/pending_control_r01/pending_control_frame_metrics.csv)の
**同じsession・frame・scenarioのdiagnostic_z_m**を読み、表示だけ小数3桁へ丸めた。
1.30 m例は元値1.3258994138651221 m、2.00 m例は1.9743123451906057 m。
設置距離へ合わせる補正、別frameの値への置換、過去距離による補間はしていない。
この作業では距離値を再fit/再計算せず、凍結済み再計算結果を表示した。

成功例は各設置区間の距離利用可能frameを時系列順に並べ、その中央を選んだ（1.3 mは85 frame、2.0 mは138 frameの中央）。
誤差が最小のframeを選んだものではない。遮蔽例は以前から診断対象だったframe1134を固定した。

黄色点は保存された**同じframeの画像上の下端proxy**。真の床接地点を確認したマークではない。
YOLOの検出枠を新たに生成したり、接地点を人手で動かしたりもしていない。
遮蔽例では姿勢根拠と画像品質が不足しているため、数値も下端マークも描かない。

## 原画像と解析図を分離

- 無加工原画像：`originals_r01/*_raw_*.png`、1280×720全画角。
- 派生解析図：`visualizations_r01/*.svg`とPNG、1280×980。
- 元写真部分は1280×720のまま、上下に説明帯を追加。リサイズ/切抜き/色補正なし。
- SVGは原PNGのbytesをそのまま埋め込み、数値・線・点は別レイヤーに置く。
- 画像上の指示点/説明枠は**ユーザーが今回依頼した派生図だけ**に表示する。
  従来の無加工画像保存方針や既存の当日代表資料は変更しない。

| 無加工原画像 | SVG版 |
|---|---|
| [1.30 m原画像](originals_r01/cone_130_raw_f000719.png) | [1.30 m SVG](visualizations_r01/cone_130_distance_f000719.svg) |
| [2.00 m原画像](originals_r01/cone_200_raw_f001333.png) | [2.00 m SVG](visualizations_r01/cone_200_distance_f001333.svg) |
| [遮蔽原画像](originals_r01/occlusion_hold_raw_f001134.png) | [遮蔽SVG](visualizations_r01/occlusion_hold_distance_f001134.svg) |

## 検証・再現

新規13テストPASS。[検証JSON](verification_r01/summary.json)／[ログ](verification_r01/test_log.txt)。
元CSV行hash、観測行hash、raw動画の独立frame読取り、原PNG画素hash、SVG埋込bytes、表示値/参照値の区別、
マーク座標、保留の数値非表示、警告文、PNG寸法、未注釈領域の画素一致を検証した。
3枚の原画像と3枚の解析図も目視確認した。

初回rendererは複数行f-stringの構文で保存前に停止。metadataを別変数に分離してから正式実行し、
元データや選択frame、距離値は変更していない。

[原画像・元行対応manifest](originals_r01/frame_manifest.csv)／
[表示対応manifest](visualizations_r01/visualization_manifest.csv)

既存ファイルを上書きせず、`prepare_frames.py`→`render_examples.py`→`verify.py`で生成した。
再生成は別版へ出力先を変更。再検査だけなら以下。

```bash
cd ~/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 PYTHONPATH=src /home/robo25/theta-env/bin/python3 \
  -m unittest discover \
  -s Experimental_results/2026-10-23/cone_distance_visual_examples_r01 \
  -p test_visualizations.py -v
```

本番src/設定、校正/TF、判定値、ROS/FFB、安全機構、GPU/driver、実機は変更せず、追加撮影も行っていない。
