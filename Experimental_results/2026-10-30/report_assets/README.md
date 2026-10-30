# 2026-10-30 代表資料

原ファイルをバイト単位で複製し、SHA256一致を確認。来歴は`manifest.json`、複製スクリプトは`../save_report_assets.py`。既存ファイルは上書きしない。

| 資料 | 内容・制約 |
| --- | --- |
| [実機r02無加工画像](live_r02_raw_f000635.png) | session `f860e50d1c4e485a98cbc1a2f6138cdf`、frame635、1280×720。コーンと床が写る復号画像。枠・数値・切抜き・リサイズ・色補正なし。元センサーの無圧縮原本とは呼ばない |
| [候補点の時系列](support_candidate_timeline.png) | 実機r02の1,689処理行。色別1,636・補完追加35・保留18の区別。元CSVは`../cone_support_live_review_r01/results_r02/frame_review.csv`。距離精度や接地の正解率ではない |
| [固定床の高さ感度](fixed_floor_height_sensitivity.png) | 元CSVは`../floor_pose_fixed_mode_r01/evaluation_r01/height_sensitivity.csv`。既存法線へ明示高さを与えた条件付き数値グラフ。59 cmが画像から独立に確認されたことを示さない |

写真は無加工、グラフは数値から生成したもの。作業中の赤のみ別評価は本資料に含めない。
