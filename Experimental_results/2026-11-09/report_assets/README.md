# 2026-11-09 代表グラフ

カメラ元画像は変更・注釈・再保存していない。以下は録画後の条件付き再計算から作ったグラフで、新しいlive実験や精度承認ではない。

|ファイル|内容|根拠CSV|
|---|---|---|
|df33_floor_only_comparison.png|旧紙角と人の確認紙角で1/1.5/2mを比較。同じ自動支持点を維持|[df33_floor_only_replay.csv](../reviewed_coordinate_audit_r01/results_r02/df33_floor_only_replay.csv)|
|factor_separation.png|紙の床モデル変更と台座辺中央の変更を分離。32654の色点は拒否済み仮候補でlive出力ではない|[same_frame_factorial_distances.csv](../reviewed_coordinate_audit_r01/results_r02/same_frame_factorial_distances.csv)|
|corner_sensitivity.png|紙角8座標の局所感度。±0.25px中央差分で高さ・固定支持点距離への影響を比較|[coordinate_derivatives.csv](../paper_corner_sensitivity_r01/results_r02/coordinate_derivatives.csv)|
|height_stress_samples.png|各座標±0.5/1pxの256符号組合せの高さ応答。信頼区間でも誤差上限でもない|[joint_stress_samples.csv](../paper_corner_sensitivity_r01/results_r02/joint_stress_samples.csv)、[全応答](../paper_corner_sensitivity_r01/results_r02/perturbation_metrics.csv)|

生成スクリプト：最初の2枚は [確認座標の解析](../reviewed_coordinate_audit_r01/analyze.py)、後の2枚は [紙角の感度解析](../paper_corner_sensitivity_r01/analyze.py)。それぞれの `results_r02/` 出力PNGをバイトコピーしたもの。再現コマンド・仮定・限界は [確認座標のREADME](../reviewed_coordinate_audit_r01/README.md)、[感度解析のREADME](../paper_corner_sensitivity_r01/README.md) を参照。

同日の続編として、[角位置補正の比較図](../paper_boundary_stability_r01/results_r02/corner_refinement_comparison.png)、[処理条件別の距離安定性の図](../paper_boundary_stability_r01/results_r02/parameter_stability_ranges.png) も保存した。生成スクリプト・根拠CSVは [紙外周安定性README](../paper_boundary_stability_r01/README.md) から追跡可能。同日代表4点は保持し、追加図はこのリンクで参照する。

[同一sessionの別紙画像との再現性比較](../same_session_reference_audit_r01/results_r02/same_paper_frame_repeatability.png) も追加した。物理的精度の独立検証ではなく、同配置に見える紙のフレーム間比較。根拠CSV・生成スクリプトは [同一session監査README](../same_session_reference_audit_r01/README.md) を参照。
