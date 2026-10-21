# 2026-10-21 報告用画像

## 日報用の最終代表4点

10/21終了時点の到達点を説明する代表資料。[当日日報](../../../Daily_reports/2026-10-21_daily_report.md)を参照。以下の4点は元生成物からバイト同一で追加コピーし、従来の資料は削除・置換していない。

| ファイル | 内容 |
|---|---|
| [daily_final_raw_intrinsic_r03_f002771.png](daily_final_raw_intrinsic_r03_f002771.png) | 実格子r03、session`front_fisheye_intrinsic_a4_r03_20261021_182522_716`、frame2771。1280×720全画角・未編集 |
| [daily_final_intrinsic_solver.png](daily_final_intrinsic_solver.png) | 同じ57枚での校正方式比較。距離精度の合格図ではない |
| [daily_final_floor_validation.png](daily_final_floor_validation.png) | 未使用2点と別録画を分けた床距離検証 |
| [daily_final_scene_metric.png](daily_final_scene_metric.png) | 建物線からのup候補による1録画の距離中央値改善。遮蔽時の最大5.438 mの外れ値、高さ法の不一致は日報本文も併記 |

コピー元・SHA-256・撮影来歴は[daily_final_manifest.json](daily_final_manifest.json)、収集処理は[collect_daily_final.py](collect_daily_final.py)。カメラ画像の加工や、新しい撮影を行ったものではない。

## 作業中に保存した資料・後続解析への索引

以下の冒頭4点は、既存録画による既知寸法測距の検証資料。この比較自体は新しい撮影・実機出力ではない。後半で受領した本日のA4校正録画等は、下記の追加索引へ分けて記載する。[既知寸法の検証報告](../cone_known_size_pinhole_r01/README.md)

| ファイル | 内容・説明時の注意 |
|---|---|
| [known_width_vs_floor.png](known_width_vs_floor.png) | 設置距離に対する可視幅方式と同じ視線の床交点の比較。実測内部校正済み・本番使用可という意味ではない。 |
| [known_width_occlusion_and_yaw.png](known_width_occlusion_and_yaw.png) | 左は既存録画の遮蔽付近の推定、右は理想正方形の合成yaw感度。右を実験中の姿勢測定結果として使わない。 |
| [raw_paper_cone_2m_f001019.png](raw_paper_cone_2m_f001019.png) | 10/19の名目2.00 m条件のネイティブ1280×720カメラ画像。枠・文字・切抜き・拡大縮小・色変更なし。10/21の新規撮影ではない。 |
| [known_height_comparison.png](known_height_comparison.png) | ユーザー実測の全高73 cmによる測距比較。台座手前辺と先端軸の対応は未確認で、本番承認ではない。[高さ検証報告](../cone_known_height_pinhole_r01/README.md) |

カメラ画像の元セッションは `paper_cone_center_z2p00_r01_20261019_180411_245`、元フレーム番号1019。元の[フレーム来歴](../../2026-10-19/paper_cone_2m_validation_r01/raw_sample_manifest.csv)を参照。

3点は元ファイルからバイト同一でコピーし、SHA-256を確認した。[マニフェスト](known_width_manifest.json)。グラフは数値から新規生成したもので、カメラ画像の編集ではない。

追加の高さ比較グラフも元生成物からバイト同一で保存。[高さグラフの来歴](known_height_manifest.json)。元の3点・マニフェスト・カメラ画像は変更していない。

続く点対応検証のグラフも同日フォルダに保存：[投影方向と観測下辺の比較](../cone_plumb_support_r01/results_r02/plumb_support_comparison.png)、[遮蔽・列移動](../cone_plumb_support_r01/results_r02/plumb_support_occlusion_and_shifts.png)。これらは追加の解析図であり、上の代表4点や未編集カメラ画像は置き換えていない。数値の来歴と制限は[検証報告](../cone_plumb_support_r01/README.md)を参照。

後続の視線監査：[絶対角と角度サイズ](../cone_absolute_bearing_audit_r01/results_r01/absolute_vs_relative_bearing.png)、[床基準の角度と録画間の画素差](../cone_absolute_bearing_audit_r01/results_r01/floor_references_and_repeatability.png)。どちらも数値グラフでありカメラ画像の編集ではない。約7°は物理的取付変更の測定ではなく、未校正モデルの方向残差。[根拠・制限・テスト](../cone_absolute_bearing_audit_r01/README.md)

実A4録画r01：[格子サイズ・候補分布・全試行の数値図](../front_intrinsics_a4_real_r01/diagnosis_r01/extraction_diagnostics.png)、[大きく読めた冒頭の未編集raw](../front_intrinsics_a4_real_r01/extraction_r01/raw_frames/raw_f000001.png)、[遠方の紙の未編集raw](../front_intrinsics_a4_real_r01/raw_samples/raw_f000150.png)。元解像度1280×720・全画角を保持。session/frame/hashは[受入manifest](../front_intrinsics_a4_real_r01/raw_sample_manifest.csv)と[候補manifest](../front_intrinsics_a4_real_r01/extraction_r01/raw_frame_manifest.csv)に保存。6姿勢のみで校正未実施という結果であり、校正成功の画像ではない。[解析報告](../front_intrinsics_a4_real_r01/README.md)

実A4録画r02：[候補54枚の分布・格子サイズ・不足方向の数値図](../front_intrinsics_a4_real_r02/exports_r01/coverage_diagnosis.png)、[中央に大きく映る板の未編集raw（frame3661）](../front_intrinsics_a4_real_r02/extraction_r01/raw_frames/raw_f003661.png)、[無信号表示の未編集raw（frame472）](../front_intrinsics_a4_real_r02/raw_samples/raw_f000472.png)。54枚は校正前の候補で、上下分布不足によりK/D推定は未実行。[解析報告](../front_intrinsics_a4_real_r02/README.md)、[原画像manifest](../front_intrinsics_a4_real_r02/exports_r01/raw_frame_manifest.csv)。既存代表4点は置き換えず、写真は元1280×720全画角のまま保存。

実A4録画r03：[r02と合併した57枚の分布グラフ](../front_intrinsics_a4_real_r03/combined_candidate_r01/merged_coverage.png)、[上側に大きく映った未編集raw（r03 frame2771）](../front_intrinsics_a4_real_r03/extraction_r01/raw_frames/raw_f002771.png)。上下の範囲は23.57%→50.52%へ増えて事前分布条件を満たしたが、校正ソルバーは数値不安定で停止。K/D確定や距離精度合格の図ではない。[解析・初期値診断](../front_intrinsics_a4_real_r03/README.md)、[原画像hash manifest](../front_intrinsics_a4_real_r03/extraction_r01/raw_frame_manifest.csv)。写真は1280×720全画角のままで、グラフも元画像への描画ではない。

続く計算側の診断：[投影定義域・収束・誤差の比較](../front_fisheye_solver_audit_r01/plots_r01/solver_domain_comparison.png)、[57枚ごとの再投影誤差と角対応監査](../front_fisheye_solver_audit_r01/plots_r01/per_view_and_corner_audit.png)。同じ57枚を残したangular KB4でtrain0.329 / 姿勢検証0.436 pxの候補を得た。通常OpenCV方式の失敗や旧joint方式の境界停止を隠さず比較。図中の角はモデルの推定値で、レンズ画角やm単位の距離精度の実測ではない。[解析報告・制限・再現手順](../front_fisheye_solver_audit_r01/README.md)。カメラ原画像の編集はなし。

内部校正の実距離への転用検証：[床基準の距離・位置誤差](../angular_metric_validation_r01/plots_r01/floor_metric_validation.png)、[同じコーン端点での方式比較](../angular_metric_validation_r01/plots_r01/cone_metric_comparison.png)、[高さ法の床高さ・3D残差](../angular_metric_validation_r01/plots_r01/cone_height_consistency.png)。白紙5点で姿勢を推定し、同録画の未使用2点は平面RMSE2.17 cm。一方、別録画2 mの前後誤差は+24.75 cmで、本番承認ではない。数値グラフのみ追加し、既存代表画像・原画像は編集/置換していない。[全条件・来歴・検証報告](../angular_metric_validation_r01/README.md)。

接地点対応と転用幾何を分けた後続検証：[先端仰角と下辺全範囲の高さ条件](../angular_contact_consistency_r01/plots_and_verification_r01/tip_and_floor_necessary_conditions.png)、[同一frameでの下端選択前後](../angular_contact_consistency_r01/plots_and_verification_r01/same_frame_contact_selection.png)。下端選択で線分残差は下がるが、系列録画の先端視線は下向きとなり、73 cmの先端・59 cmのカメラという条件と整合しない。物理取付変化の証明ではなく、固定モデルの転用と端点仮説の不整合を示す図。[定量結果・29テスト・未編集原画像の来歴](../angular_contact_consistency_r01/README.md)。画像編集・本番反映なし。

建物線による独立した姿勢の手掛かり：[推定可能画像・録画の数](../scene_vertical_gravity_r01/plots_and_verification_r01/scene_up_coverage.png)、[同じコーン画素での距離・床高さ比較](../scene_vertical_gravity_r01/plots_and_verification_r01/sequence_metric_crosscheck.png)。86画像・9録画のうち1録画で条件付きup候補が得られ、床交点中央値は設置1.30 m→1.333 m、2.00 m→1.988 m。ただし2 m区間には遮蔽による最大5.438 mの外れ値が3frameあり、他8録画の推定不足・高さ法の不一致も残る。中央値だけを測距合格として説明しない。[報告・全台帳・28テスト](../scene_vertical_gravity_r01/README.md)。原画像は編集していない。
