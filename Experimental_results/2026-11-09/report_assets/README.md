# 2026-11-09 代表資料（終了時点の選定4点）

最終の代表は下記4点。前半の2グラフ、後半の実撮影PNG1枚、走行向け経路の既存画像再生CSVを選んだ。元画像は変更・注釈・再保存せず、PNGはDownloadsの提出原本から同じファイル名でバイトコピーしSHA一致を確認した。図は条件付きの録画後再計算で、物理精度の承認ではない。PNGもWebRTC復号画像であり、無圧縮センサRAWではない。CSVは保存YOLO枠の再利用であり実機走行・新規CUDA推論ではない。

|代表ファイル|内容と出典|根拠|
|---|---|---|
|df33_floor_only_comparison.png|旧紙角と人の確認紙角の1/1.5/2m比較。既存の自動支持点を維持|[元CSV](../reviewed_coordinate_audit_r01/results_r02/df33_floor_only_replay.csv)、[生成コード](../reviewed_coordinate_audit_r01/analyze.py)|
|corner_sensitivity.png|紙角8座標に対する高さ・距離の局所感度|[元CSV](../paper_corner_sensitivity_r01/results_r02/coordinate_derivatives.csv)、[生成コード](../paper_corner_sensitivity_r01/analyze.py)|
|decoded_159c37ad534a4ac0b96ca69791713567_f055094.png|P4、車体右20cm・前方1.40mのE。原本 `/home/robo25/Downloads/` の同名PNG、同session、frame55094、1280×720。画像上の左右を車体左右と取り違えない|[最新レポート](../wide_floor_geometry_r01/continuation_report.md)、[解析入力SHA](../wide_floor_geometry_r01/results_r01/input_provenance.json)|
|motion_range_cached_replay.csv|既存10画像＋同frameの保存YOLO枠を走行向けengineへ通した全結果。3枚出力・7枚保留。CPU時間はライブ遅延ではない|[元CSV](../cone_motion_evaluation_r01/verification_r02/cached_replay_metrics.csv)、[生成コード](../cone_motion_evaluation_r01/verify_existing_data.py)、[37テストの記録](../cone_motion_evaluation_r01/verification_r02/summary.json)|

途中の代表だった `decoded_159c37ad534a4ac0b96ca69791713567_f020063.png` も補足として保持する。P0、固定L字床4点、session `159c37ad...`、frame20063、1280×720。原本はDownloadsの同名PNGで、[提出来歴](../wide_floor_reference_capture_r01/p0_outer_corner_intake.md)と[解析入力SHA](../wide_floor_geometry_r01/results_r01/input_provenance.json)から追跡できる。CSVは元ファイルのバイトコピーで、カメラ画像の新規生成・加工はしていない。

以下は**前半時点の図一覧・補足資料**。既存のfactor_separation／height_stress_samplesを削除せず残すが、終了時点の代表4点へ追加カウントしない。

|ファイル|内容|根拠CSV|
|---|---|---|
|df33_floor_only_comparison.png|旧紙角と人の確認紙角で1/1.5/2mを比較。同じ自動支持点を維持|[df33_floor_only_replay.csv](../reviewed_coordinate_audit_r01/results_r02/df33_floor_only_replay.csv)|
|factor_separation.png|紙の床モデル変更と台座辺中央の変更を分離。32654の色点は拒否済み仮候補でlive出力ではない|[same_frame_factorial_distances.csv](../reviewed_coordinate_audit_r01/results_r02/same_frame_factorial_distances.csv)|
|corner_sensitivity.png|紙角8座標の局所感度。±0.25px中央差分で高さ・固定支持点距離への影響を比較|[coordinate_derivatives.csv](../paper_corner_sensitivity_r01/results_r02/coordinate_derivatives.csv)|
|height_stress_samples.png|各座標±0.5/1pxの256符号組合せの高さ応答。信頼区間でも誤差上限でもない|[joint_stress_samples.csv](../paper_corner_sensitivity_r01/results_r02/joint_stress_samples.csv)、[全応答](../paper_corner_sensitivity_r01/results_r02/perturbation_metrics.csv)|

生成スクリプト：最初の2枚は [確認座標の解析](../reviewed_coordinate_audit_r01/analyze.py)、後の2枚は [紙角の感度解析](../paper_corner_sensitivity_r01/analyze.py)。それぞれの `results_r02/` 出力PNGをバイトコピーしたもの。再現コマンド・仮定・限界は [確認座標のREADME](../reviewed_coordinate_audit_r01/README.md)、[感度解析のREADME](../paper_corner_sensitivity_r01/README.md) を参照。

同日の続編として、[角位置補正の比較図](../paper_boundary_stability_r01/results_r02/corner_refinement_comparison.png)、[処理条件別の距離安定性の図](../paper_boundary_stability_r01/results_r02/parameter_stability_ranges.png) も保存した。生成スクリプト・根拠CSVは [紙外周安定性README](../paper_boundary_stability_r01/README.md) から追跡可能。既存図は保持し、終了時点の代表は冒頭の4点を参照する。

[同一sessionの別紙画像との再現性比較](../same_session_reference_audit_r01/results_r02/same_paper_frame_repeatability.png) も追加した。物理的精度の独立検証ではなく、同配置に見える紙のフレーム間比較。根拠CSV・生成スクリプトは [同一session監査README](../same_session_reference_audit_r01/README.md) を参照。
