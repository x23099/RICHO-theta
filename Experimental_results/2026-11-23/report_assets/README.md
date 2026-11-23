# 2026-11-23 代表資料

今日はオフライン解析日で、カメラ画像・映像フレームは生成していない。そのため画像資料は置かず、日報の主要な判断を再検証できるJSON 3点を保存する。いずれも元ファイルのコピーで、内容は変更していない。

| ファイル | 出典 | 用途 |
|---|---|---|
| [cone_intent_grid_evaluation.json](cone_intent_grid_evaluation.json) | [cone_intent_eval_r01/results_r01/evaluation.json](../cone_intent_eval_r01/results_r01/evaluation.json) | コーンintent（B案）のグリッド評価。評価可能5点で方向不一致0、確定3、大きさ0〜0.40。 |
| [lateral_calibration_validation.json](lateral_calibration_validation.json) | [lateral_estimate_r01/validation_r01/validation.json](../lateral_estimate_r01/validation_r01/validation.json) | 横位置校正のLOOCV・cross-distance・左右別係数・側符号7/7。 |
| [side_mapping_ab_comparison.json](side_mapping_ab_comparison.json) | [side_mapping_r01/results_r01/comparison.json](../side_mapping_r01/results_r01/comparison.json) | A（勾配方向）とB（側ベース）の80評価比較。Aの不一致6/80をBが0/80に。 |

## 注意

- JSONは元ファイルのコピー。集計ロジック・再現コマンドは各出典の`run.py` / `validate.py`を参照。
- 実カメラ・GPU・ROS・FFBは未使用。`physical_metric_verified` / `usable_for_ffb`はfalse。
- リプレイ検証（2,000 frame）の数値は日報§4.8に記載。入力archiveは`recordings/`外の`driver_motion_yellow_r04.tar.xz`で、Git管理外のため本フォルダには含めない。
