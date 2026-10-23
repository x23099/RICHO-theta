# 10/23代表資料（旧10/22扱いの作業を含む）

ユーザー指定により、10/22として保存した前段作業も10/23の日報へまとめた。
元結果は移動せず、代表4資料だけをこのフォルダへバイト同一コピーした。
原カメラ画像は撮影日10/15のままで、作業日に合わせて撮影日を変えていない。

| ファイル | 内容・出典 |
|---|---|
| [distance_quality_and_pose_sensitivity.png](distance_quality_and_pose_sensitivity.png) | [10/22保存の距離品質/姿勢感度](../../2026-10-22/scene_uniform_validation_r01/README.md)。数値図であり実機保証ではない |
| [rejection_and_wide_roi_control.png](rejection_and_wide_roi_control.png) | [全画像の停止理由と単一範囲拡張](../../2026-10-22/scene_rejection_audit_r01/README.md)。元成功系列の回帰も表示 |
| [separate_bands_comparison.png](separate_bands_comparison.png) | [本日の上下独立抽出](../scene_separate_bands_r01/README.md)。採用数と時間再現性の比較であり距離精度ではない |
| [raw_sequence_f000780.png](raw_sequence_f000780.png) | session=`floor_cone_same_pose_r01_20261015_160621_378`、frame780、約26.059秒、native1280×720。元PNGとバイト同一、無加工 |

カメラ画像の注釈・合成・切り抜き・リサイズ・色/明るさ補正はしていない。
数値グラフは[生成コード](../scene_separate_bands_r01/report.py)と[manifest](manifest.json)から元CSV/生成スクリプトへ追跡できる。
