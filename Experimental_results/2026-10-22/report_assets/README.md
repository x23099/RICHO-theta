# 2026-10-22 作業の代表資料

ユーザー指定により10/21終了後の継続作業を10/22分として保存。原撮影は10/15・10/19の既存録画で、撮影日を書き換えていない。[検証報告](../scene_uniform_validation_r01/README.md)

| ファイル | 内容・説明時の注意 |
|---|---|
| [metric_quality_and_pose_sensitivity.png](metric_quality_and_pose_sensitivity.png) | 固定K/D・同じ観測での距離と品質採用後の最大差。左の灰色範囲は8つの評価側方向候補による数値感度で、信頼区間ではない。右は対数目盛 |
| [occlusion_measurement_withholding.png](occlusion_measurement_withholding.png) | 生の大きな距離を残したまま、既存因果ゲートで保留し1139で現frame観測へ復帰する様子。欠測を旧距離で埋めていない。各段の縦軸範囲は異なる |
| [scene_evidence_coverage.png](scene_evidence_coverage.png) | 492画像・9録画の方向候補数と、同じ録画内の繰返し平面数。4～5平面等の未達を成功へ格上げしていない |
| [raw_sequence_f000780.png](raw_sequence_f000780.png) | session`floor_cone_same_pose_r01_20261015_160621_378`、frame780。1秒間隔抽出の中央サンプル。元1280×720全画角・無加工・バイト同一コピー |

3図は数値CSVから生成したもので、カメラ画像の編集ではない。raw画像は枠・線・文字追加、切抜き、リサイズ、色/明るさ補正なし。

コピー元・SHA-256・rawの元frame/時刻は[manifest.json](manifest.json)。生成scriptは[plot_results.py](../scene_uniform_validation_r01/plot_results.py)、数値の根拠は[metric_results_r01](../scene_uniform_validation_r01/metric_results_r01/condition_summary.csv)、[scene_results_r01](../scene_uniform_validation_r01/scene_results_r01/session_hypotheses.csv)、[pooled_results_r01](../scene_uniform_validation_r01/pooled_results_r01/session_hypotheses.csv)、[quality_results_r01](../scene_uniform_validation_r01/quality_results_r01/occlusion_recovery.csv)から辿れる。

新規撮影・実機FFB・本番設定変更を示す資料ではない。中央値の改善だけを全環境での数cm精度・本番承認として説明しない。
