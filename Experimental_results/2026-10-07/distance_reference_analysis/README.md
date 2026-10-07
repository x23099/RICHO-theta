# 2026-10-07 静止距離参照4条件の解析

## 結論

**4録画は解析可能。箱なしの検出0、箱あり3距離の全フレーム検出、模擬速度0、不要な通知なしを確認した。ただし「安定して検出できる」と「実距離へ正確に一致する」は別で、1.10 m条件には全方式で短めの推定が残る。**

距離はファイル名の0.90／1.10／1.30 mをユーザー申告の測定距離として使用する。後続回答で、**3条件ともカメラ直下／Kobuki中心からの距離で、高さ・傾きは変更していない**ことが確認できた（[確認記録](reference_conditions.json)）。数値結果は変更せず、CSV・グラフ・provenanceへ確認内容を反映した。箱側の測定点の詳細、設置誤差、カメラの絶対高さ・角度の数値は未記録であり、係数の採否判定には留保を残す。係数フィット・本番設定変更・ROS送信・hardware駆動は行っていない。

- 現行liveの中央値：0.9179／1.0185／1.2949 m。
- 1.10 m条件は現行−8.15 cm、凍結候補でも約−6.8 cm。単に揺れを減らすだけでは解決しない。
- 0.90 mと1.30 mの差は別方向・別の大きさで、一律オフセットで全距離を合わせる根拠はない。
- S130 bottomは今回のraw再計算で揺れが小さいが、0.90／1.30 mの申告値との差は現行liveより大きい。無条件に「候補の方が高精度」とは判定しない。
- 1.30 mも範囲内で測定できており、範囲外や不採用による統計の間引きはない。

## 入力と条件

原本はすべて`/home/robo25/Downloads/`。既存safe extractorでパス・リンク・展開サイズを確認し、一時領域へ展開。アーカイブと原本録画は変更していない。

| 原本 | SHA256 |
|---|---|
| `record_reference_distance_reference_no_box_r01_20261007_174742_202.tar.xz` | `5235b9117228b0d00ea6997ebda954fb897e200a7262261956bb9ba753153978` |
| `record_reference_distance_reference_center_z0p90_r01_20261007_174846_806.tar.xz` | `b15e5b828a636fc529e6b48f66b4aadbd9882b00cea1ad7507bcdde582fc6b57` |
| `record_reference_distance_reference_center_z1p10_r01_20261007_174945_175.tar.xz` | `23c81c23432184f5feedf28a15f70cbddef0b207dc3db73a11b09dcb57095957` |
| `record_reference_distance_reference_center_z1p30_r01_20261007_175040_153.tar.xz` | `1df482bb389d8f30d35d637a1bc40ef5a39f3723da711276dd94301b6ce82ef5` |

各session名は原本から拡張子を除いた名前と一致する。`record_reference_distance_reference_...`という接頭辞の重複はラベル名として保持し、解析上の問題はない。

| 条件 | frame数 | 録画時間 | 実効fps | live検出／有効測定 |
|---|---:|---:|---:|---:|
| 箱なし | 321 | 10.754秒 | 29.816 | 0／0 |
| 0.90 m | 618 | 20.717秒 | 29.811 | 618／618 |
| 1.10 m | 613 | 20.749秒 | 29.523 | 613／613 |
| 1.30 m | 742 | 24.785秒 | 29.917 | 742／742 |

計2,294 frame。各sessionのCSV／raw／bev／detectionは全件一致し、3動画は逐次全フレームデコードでも一致。frame連番・time単調・time aliasの整合はPASS。全4本でv12 JSONの全キーとmetadataの差0。取得は1280×720、MJPG、要求30 fps。

全録画でODOM available、線速度・角速度0、cmd線速度・角速度0。liveは全frame CLEAR、FFB active0、publish失敗0。raw再計算3方式も全frame CLEAR・virtual active0。両PC bagは今回の静止参照には必要としていないため未提出であり、publish成功だけからadapter到達や実振動まで評価したとはしない。

[整合性・タイミングCSV](integrity.csv)、[検証](verification.json)。live処理時間の中央値は約29.9～30.8 ms。1.10 mのfpsがやや低くても、記録の欠落・動画CSVの不一致はない。

## 生画像の独立レビュー

検出値・距離・候補比較を読む前に、各録画の最初・中央付近・最後の3点、計12点を生画像で確認した（[目視手順](review_protocol.md)、[ラベル](manual_review.csv)）。箱なし3点は対象なし、箱あり9点は箱全体と下端が見える。静止配置と整合するが、この12点だけで全frameの可視性・物理的静止・実測値を証明したとは扱わない。

- [箱なし frame150・4.986988秒](../report_assets/distance_reference_no_box_raw_frame_0150.png)
- [1.10 m条件 frame289・9.995527秒](../report_assets/distance_reference_z1p10_raw_frame_0289.png)

全画角1280×720の無加工PNG。注釈・合成・切抜き・リサイズ・色補正なし。[レビューframeのピクセルhash](review_frame_manifest.csv)と保存PNGのBGRピクセルを照合した。

## 距離の偏り・ばらつき

評価対象は前後方向の**Z**。平面斜距離や車体前端からの距離とは混ぜない。現行liveと、保存rawへ同じ凍結設定を適用したbaseline／S130 nearest／S130 bottomを比較した。

集計は事前に決めた「全録画」「2秒以降」の両方を保存し、以下は初期化の影響を分けた2秒以降。点数は0.90 m558、1.10 m553、1.30 m682、箱なし261 frame。全検出座標を使い、範囲外や不採用でも除外しない。採用座標・filtered track・X座標は別列へ保存した（[全統計CSV](distance_summary.csv)）。

| 申告Z | live：中央値（差） | baseline再計算 | S130 nearest | S130 bottom |
|---|---|---|---|---|
| 0.90 m | 0.9179 m（＋1.79 cm） | 0.9399 m（＋3.99 cm） | 0.9281 m（＋2.81 cm） | 0.9298 m（＋2.98 cm） |
| 1.10 m | 1.0185 m（−8.15 cm） | 1.0298 m（−7.02 cm） | 1.0322 m（−6.78 cm） | 1.0323 m（−6.77 cm） |
| 1.30 m | 1.2949 m（−0.51 cm） | 1.2980 m（−0.20 cm） | 1.3073 m（＋0.73 cm） | 1.3169 m（＋1.69 cm） |

差の符号は推定中央値−申告Z。測定起点と高さ・傾きの変更なしはユーザー確認済み。設置誤差の数値と箱側の測定点詳細は未記録。

| 申告Z | live IQR | baseline IQR | nearest IQR | bottom IQR |
|---|---:|---:|---:|---:|
| 0.90 m | 0.010 cm | 0.794 cm | 0.534 cm | 0.006 cm |
| 1.10 m | 0.010 cm | 2.052 cm | 0.028 cm | 0.007 cm |
| 1.30 m | 0.070 cm | 0.353 cm | 0.086 cm | 0.000 cm |

IQRは第75−第25百分位の幅。小さなIQRや0は「その範囲の出力が同じ／近い」というだけで、ミリ未満の測距精度を保証しない。輪郭・pixel選択の離散化、CSV丸め、同じ配置での時間相関を含む。1本の多数frameを多数の独立実験として扱わず、信頼区間も算出していない。

1.10 mのlive絶対誤差p95は申告値に対して8.18 cm、bottomは6.78 cm。1～2 cmの設置不確かさを仮に見込んでも差は残るが、実測メモがないため現時点で計測誤差と配置誤差を分離しきれない。

[全体距離タイムライン](static_distance_timeline.png)、[申告距離と中央値・符号付き差](static_distance_bias.png)。グラフのP5–P95は時間方向の分布幅であり、真値や平均の信頼区間ではない。描画元は[距離時系列CSV](distance_timeline.csv)と統計CSV。

## 検出・追跡・凍結条件

箱なしはlive・raw再計算3方式すべて0／321検出。箱ありでは全方式が全frame検出・範囲内だった。raw再計算の有効測定数は各録画のframe数−1で、初回のreacquisition確認によるもの。2秒以降は全方式100%採用となる。liveは録画開始前から追跡が動いている一方、raw再計算はframe1から追跡を初期化するため、その差を異常と扱わない。

凍結候補3方式×2,294=6,882行。[比較provenance](frozen_comparison/provenance.json)で10/06の設定・候補実装hashと一致することを検証。新録画に合わせた調整はなし。rawは保存時にMJPG圧縮されており、liveの元ピクセルと同一ではない。距離や横位置のbaseline/live差を、そのまま本番の改善幅としない。

S130のsegmentation中央時間はオフライン環境で約16.8～18.2 ms、baseline約6.4～7.7 ms。異なる方式を順次実行した解析PCの値で、Kobuki PCのlive FPSや追加処理時間を証明する値ではない。

## 次の判断

後続の[接地点／床面投影の追加診断](geometry_diagnosis.md)を実施した。校正変換は記録と一致し、1.10 m条件は目視下端を投影しても約1.018 mとなった。接地点候補変更だけでは偏りが解消しない。測定起点一致・高さ／傾き変更なしの回答を反映し、共通高さと共通offsetの単独仮説も条件付きで確認した。本番係数は変更していない。

1. 今回の3条件の測定起点はカメラ直下／Kobuki中心と確認済み。申告距離を保持し、1.10 mを勝手に1.00 mへ読み替えない。
2. 高さ・傾きは変更なしと確認済み。「試行ごとに取り付けを変えた」を原因扱いしない。変更なしと、固定の設定値が実姿勢に正確に一致することは別である。
3. [下端の幅方向診断](bottom_support_diagnosis/README.md)も完了。1.10 mでは左・中央・右の各中央値が約1.031～1.039 mで、選択領域だけを変えても偏りが残った。一部の右端1点が1.10 m以上になる例も記録したが、支持点の約0.70%で、そこだけを選んで合わせる根拠にはしない。次は独立した床面基準点・下端ラベル・絶対姿勢の測定情報による固定モデルの評価。今回3点だけに合わせた補正は入れず、今すぐ同条件を丸ごと録り直す要求はしない。
4. 今回3配置だけへ係数を合わせて、同じ配置で精度を採点しない。方式採用には別配置・別収録での独立評価と処理時間確認を残す。

今回の静止参照4本は取得済みとして整理できる。1.10 mの差があることは収録失敗という意味ではなく、検出成功と距離の偏りを切り分ける材料が増えた。

### 過去4配置との比較も完了

[過去録画の再評価](historical_distance_comparison/README.md)で、8/07の4配置・1,050フレームを再利用した。当時の座標と標本数24項目が再現し、現行baselineのZ中央値誤差MAEは1.53 cm。凍結S130 bottomは横位置MAEが1.47→3.24 cmと悪化したため、自動採用しない。過去4点では今回の中央1.10 mの短めの偏りが一律に出るわけではなく、単純な共通offset導入の根拠にもならない。原CSVは旧BEVでODOMなしのため元動画から距離だけを比較し、TTC／実FFBを評価した扱いにはしていない。

## 再現・検証

[analyze_distance_reference.py](analyze_distance_reference.py)が整合性・全動画デコード・統計・2Dグラフ・manifest・[assessment.json](assessment.json)を生成する。[test_analysis.py](test_analysis.py)の5 testsで、空検出を距離0としないこと、符号付き差とMAE、不採用座標の保持、欠測座標検知等を確認した。全解析と5 tests PASS。本番src／設定は変更しておらず、本番unit testsは再実行していない。

原本を既存のsafe extractorで展開し、ROOT以下を`no_box/`、`z0p90/`、`z1p10/`、`z1p30/`の各ディレクトリとし、それぞれの中に提出sessionを配置して実行する：

```bash
python3 src/compare_offline_box_contacts.py \
  --input ROOT/no_box --input ROOT/z0p90 --input ROOT/z1p10 --input ROOT/z1p30 \
  --detector-config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --output-dir Experimental_results/2026-10-07/distance_reference_analysis/frozen_comparison \
  --variants baseline seeded_s130_nearest seeded_s130_bottom \
  --freeze-from Experimental_results/2026-10-06/box_contact_candidates/provenance.json

MPLCONFIGDIR=/tmp/theta_matplotlib python3 \
  Experimental_results/2026-10-07/distance_reference_analysis/analyze_distance_reference.py \
  --session-root ROOT

MPLCONFIGDIR=/tmp/theta_matplotlib python3 -m unittest discover \
  -s Experimental_results/2026-10-07/distance_reference_analysis -p test_analysis.py -v
```

代表PNGは既存`Experimental_results/2026-10-06/v12_occlusion_screening/export_review_frames.py`で、箱なしframe150／1.10 mのframe289を各sessionから抽出する。対応するPNG・抽出manifestは同日のreport_assetsに保存済み。これらの一致も解析スクリプトで検証する。MatplotlibのAxes3D環境警告はあるが、今回の2Dグラフは保存・目視確認できた。
