# 2026-11-04 代表資料

本日の代表4点。実カメラ生画像は加工せず、元の1280×720 PNGをバイト同一で複写。グラフとユーザー提出のGUIスクリーンショットは生画像と区別する。

|ファイル|種類・出典|説明|
|---|---|---|
|`fixed_floor_comparison_gui_df33e833_f019541.png`|ユーザー提出GUIスクリーンショットの無加工コピー|L読込後に固定床比較値が表示された状態。生カメラ画像そのものではない|
|`fixed_floor_df33e833_multidistance.png`|集計グラフ|同一session内の実測1/1.5/2m比較。モデルごとの差と算出率|
|`upper_support_b559e424_f035562.png`|無加工のデコード済み生PNG、session b559e4240e364166935f9ede9ac3e7ae、frame35562|upper候補が旧方式の欠測を回復した実フレーム。注釈・合成・リサイズ・色補正なし|
|`upper_support_b559e424_live_comparison.png`|集計グラフ|同じフレーム・同じモデルでの旧/upper比較とreceiver-local処理経過時間|

## 来歴と再現

- GUI画像の対応記録: [live_gui_screenshot_evidence.json](../floor_reference_df33e833_r01/live_gui_screenshot_evidence.json)。ユーザーのスクリーンショットであり、カメラ生フレームの精度証明ではない。
- 3距離グラフ: [元図](../floor_df33e833_multidistance_r01/results_r01/distance_comparison.png)、[根拠CSV](../floor_df33e833_multidistance_r01/results_r01/case_model_summary.csv)、生成スクリプト `../floor_df33e833_multidistance_r01/analyze.py`。
- frame35562の元ファイル: `recordings/2026-11-04/upper_support_capture_submission_r01/upper_support_capture_r01/upper_support_evidence/decoded_b559e4240e364166935f9ede9ac3e7ae_f035562.png`。
  SHA256 `b1c786d71cec56246e9370920f89fc34cab9e691ed616c366fe5f3ea9e45bd7f`。
  対応行・候補の全記録再現・SHAは [evidence_verification.json](../upper_support_capture_analysis_r01/results_r02/evidence_verification.json)。
- upperグラフ: [元図](../upper_support_capture_analysis_r01/detail_r02/live_comparison.png)、[根拠CSV](../upper_support_capture_analysis_r01/detail_r02/active_plot_data.csv)、生成スクリプト `../upper_support_capture_analysis_r01/detail.py`。距離モデルは一覧先頭を固定使用し、精度の良さで選択していない。
- 紙寸法と59cmの別グラフは [paper_height_consistency.png](../floor_support_final_audit_r01/results_r03/paper_height_consistency.png)。[幾何CSV](../floor_support_final_audit_r01/results_r03/paper_geometry.csv) と `../floor_support_final_audit_r01/audit.py` から再現可能。

既存の `fixed_floor_comparison_terminal_df33e833.png` と `fixed_floor_df33e833_live_stability.png` は補足としてそのまま保持。上記の4点を優先して報告に使用する。
