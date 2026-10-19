# 2026-10-19 代表資料

当日は既存録画の再解析。カメラ原画像2枚は10/15の録画由来で、新規撮影ではない。
既存PNGをバイト同一でコピーした。全画角1280×720を維持し、注釈・合成・切抜き・リサイズ・色補正なし。
`manifest.json`に出典・session/frame・hashを記録。生成/コピー用scriptは`collect.py`。

| 資料 | 用途・根拠 |
|---|---|
| [距離方式比較](distance_method_comparison.png) | [summary.csv](../cone_distance_methods_r01/results_r01/summary.csv)から[analyze.py](../cone_distance_methods_r01/analyze.py)で生成。static080/200は面積方式の調整点なので、検証成績と混同しない |
| [遮蔽周辺の推定](occlusion_method_comparison.png) | [occlusion_rows.csv](../cone_distance_methods_r01/results_r01/occlusion_rows.csv)。raw同士の比較で、面積方式の時間ゲートは未実装 |
| [白紙基準の無加工画像](raw_paper_reference_f001481.png) | `itiawase2_20261015_183552_599` frame1481。白紙の手前左角が基準点 |
| [遮蔽時の無加工画像](raw_cone_occlusion_f001134.png) | `floor_cone_same_pose_r01_20261015_160621_378` frame1134。枠下端/見える面積が台座までを表さない例 |

原画像は説明用の参照であり、全frameの人確認済みGTではない。
結果の意味と制限は[解析README](../cone_distance_methods_r01/README.md)に記載。

## 同日後続：追加録画なしの接地点診断

後続の数値図は、各解析の出典CSVと一緒に保存した（元画像を加工したものではない）。

- [既存全7録画のbbox/色下端比較](../cone_contact_reuse_r01/full_plots_r01/all_recordings_contact_comparison.png)
- [全frameの遮蔽周辺](../cone_contact_reuse_r01/full_plots_r01/all_frame_occlusion_contact.png)
- [同一frameのpixel差](../cone_contact_reuse_r01/results_r01/same_frame_contact_comparison.png)

解釈・元CSV・生成scriptは[接地点診断README](../cone_contact_reuse_r01/README.md)。
代表4点の元ファイル/manifestは上書きせず保持する。

## 同日後続：品質判定と左右の揺れ

- [遮蔽時の保留・復帰](../cone_contact_quality_r01/results_r02/occlusion_quality_comparison.png)
- [採用率と残る距離偏り](../cone_contact_quality_r01/results_r02/coverage_and_remaining_bias.png)
- [静止左配置の左右・奥行の揺れ](../cone_contact_quality_r01/jitter_r01/left_position_instability.png)

根拠CSV・再現script・解釈は[品質判定の解析README](../cone_contact_quality_r01/README.md)。
追加録画なし。カメラ原画像の編集・新規保存なし。

## 同日後続：下端点の左偏りの再現と修正候補

- [同じ高さの点を左から打ち切る偏りの再現](../cone_bottom_ties_r01/results_r01/synthetic_tie_selection.png)
  （数値の合成輪郭グラフ。カメラ画像や正解接地点ではない）
- [Xだけ修正した案の左右・奥行比較](../cone_bottom_ties_r01/x_only_r01/x_only_xy_comparison.png)
- [改善と悪化を含めた採用率・距離偏り](../cone_bottom_ties_r01/x_only_r01/x_only_coverage_bias.png)

根拠・制限・生成scriptは[下端点診断README](../cone_bottom_ties_r01/README.md)。
左配置は改善したが中央配置の悪化と録画間の距離偏りが残る。実機接続の承認資料ではない。

## 同日後続：台座下辺/観測支持範囲の表現

- [下包絡・補助線・旧代表点の比較](../cone_support_extent_r01/results_r01/observed_support_examples.png)
- [直線不適合も含む左配置の観測範囲](../cone_support_extent_r01/extent_audit_r01/all_envelope_ranges.png)
- [下包絡の保持数と単一直線の形状判定](../cone_support_extent_r01/extent_audit_r01/observed_range_coverage.png)
- [遮蔽時の可視境界の変化](../cone_support_extent_r01/extent_audit_r01/occlusion_observed_ranges.png)

いずれも数値CSVからのグラフで、元カメラ画像の加工ではない。
「支持範囲」は画像上の観測区間。遮蔽境界にも線分が出るため、物理接地の認識成功とは扱わない。
元CSV・生成script・検証と制限は[支持範囲の解析README](../cone_support_extent_r01/README.md)。

## 同日後続：観測支持範囲の時間品質判定

- [遮蔽時の急変保留・再確認・復帰](../cone_support_quality_r01/results_r02/support_occlusion_recovery.png)
- [一本線screenと時間品質採用の違い](../cone_support_quality_r01/results_r02/support_quality_coverage.png)

元CSV・新しい独立module・限界テストは[支持範囲の時間品質README](../cone_support_quality_r01/README.md)。
初期からの誤境界やゆっくり進む遮蔽は通り得る。物理接地の証明・本番FFBへの接続は行っていない。

## 同日後続：下辺範囲の条件付き床投影

- [同じ採用frameで比較した3校正の下辺Z範囲](../cone_support_projection_r01/results_r01/conditional_support_ranges.png)
- [同じ実観測画素列を異なる校正で投影した例](../cone_support_projection_r01/results_r01/same_columns_different_geometries.png)

根拠CSV・再現script・49件の検証範囲は[下辺投影README](../cone_support_projection_r01/README.md)。
区間は観測境界を床上と仮定した投影範囲で、信頼区間や真の台座占有範囲ではない。
画像下辺の広がりとは別に録画間の距離差が残る。元カメラ画像・本番設定・FFB出力は変更していない。

## 同日後続：保存経路・座標系・物理基準の監査

- [実収録間隔と宣言fpsの区別](../cone_recording_coordinate_audit_r01/results_r01/recording_rate_audit.png)
- [同一動画の不確かなV先端候補の仮定感度](../cone_recording_coordinate_audit_r01/results_r01/same_video_reference_sensitivity.png)

根拠CSV・18件のテスト・残った最小の物理情報は[座標系監査README](../cone_recording_coordinate_audit_r01/README.md)。
10session/13,727frame/原PNG106枚/元archive5本を再照合。
保存/解析経路の座標取り違えは確認されなかったが、別録画の白紙校正をコーンへ転用できる保証ではない。
元カメラ画像の編集・新規保存、設定変更、実機出力は行っていない。

## 同日後続：仮想ピンホールと剛体変換の比較

- [同一の下辺・校正での数値比較と仮想整数画素への丸め感度](../cone_virtual_pinhole_r01/presentation_r01/pinhole_geometry_and_rounding.png)

元CSV・再現script・28件のテストは[仮想ピンホール比較README](../cone_virtual_pinhole_r01/README.md)。
現行魚眼と提案経路は数値一致。新しい物理校正を得た結果ではなく、距離の偏りも残る。
透視画像はメモリ内生成のみで保存せず、元カメラ画像は不変。
変換後YOLO再推論、ROS TF配信、実機FFBは今回行っていない。

## 同日後続：白紙・コーン同一2m録画と方式選定

- [白紙前後の画素反復性と、同じ画素の床投影](../paper_cone_2m_validation_r01/analysis_r01/paper_cone_same_column.png)
- [白紙前の未編集原画像](../paper_cone_2m_validation_r01/raw_samples/paper_cone_f000306.png)
- [コーン静置中の未編集原画像](../paper_cone_2m_validation_r01/raw_samples/paper_cone_f001019.png)
- [白紙後の未編集原画像](../paper_cone_2m_validation_r01/raw_samples/paper_cone_f001529.png)

全18枚は1280×720のdecode画素をそのままPNG保存。manifest/hashは[解析README](../paper_cone_2m_validation_r01/README.md)から参照。
同じ列の紙角と台座下辺は画素一致したが、既存幾何の床投影は名目2mに合っていない。
ピンホール化だけでは偏りが変わらない。既知ROIの色輪郭診断であり、YOLO再推論・校正採用・実機FFB試験ではない。

## 同日後続：魚眼直接測距＋TFの計算コア

- [1点の床基準による校正識別性](../fisheye_tf_preparation_r01/results_r01/one_point_identifiability.png)

固定スケールのJacobianを示す数値グラフ。実測誤差の棒グラフではない。
実装・全1,733frameの保存観測との照合・29件のテストは[TF準備README](../fisheye_tf_preparation_r01/README.md)。
実TF配信・新規校正のfit・本番FFB接続は未実施。カメラ原画像の加工/追加保存なし。

## 同日後続：独立内部校正ツールの準備

- [印刷用A3格子PDF](../fisheye_intrinsic_preparation_r01/target_a3/checkerboard.pdf)
- [合成データでの内部校正ツール確認](../fisheye_intrinsic_preparation_r01/presentation_r01/synthetic_tool_validation.png)

格子は印刷用の生成物、グラフも合成テストであって実カメラの精度ではない。
元CSV相当の合成候補JSON・再現script・39件のテストは[内部校正準備README](../fisheye_intrinsic_preparation_r01/README.md)。
実レンズK/Dはまだ未取得。本番設定、カメラ原画像、FFBは変更していない。
