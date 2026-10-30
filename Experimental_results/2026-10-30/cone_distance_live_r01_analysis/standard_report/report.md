# 測距処理ログの集計

状態：`INCOMPLETE_CAPTURE`。実機・距離精度の合格判定ではありません。

|Session|処理件数|条件付き出力|記録間の未処理番号数|
|---|---:|---:|---:|
|f1f1b17f34a6447a9789291af128f991|5427|0|42|

処理・記録されたフレームだけの集計です。表示時間率、ネットワーク損失率、カメラFPSではありません。

距離はpaper7基準の条件付き推定値です。実測基準がないため精度・誤差は評価していません。

`summary.json`にsession別の保留理由、各blocker、受信後の処理時間の中央値・p95・最大値と入力SHA256を保存しています。

## Session: f1f1b17f34a6447a9789291af128f991

指定ROI `[270, 0, 350, 720]`。この範囲の外は監視対象外。

|処理結果の主理由|件数|
|---|---:|
|frame_processing_too_old|1|
|no_candidate|1424|
|colour_contour_reaches_roi_edge|3985|
|ambiguous_front_cones|10|
|support_confirmation_pending|4|
|latest_scene_image_rejected|3|

|処理時間項目 [ms]|中央値|p95|最大|
|---|---:|---:|---:|
|frame_age_ms|11.004|14.003|1328.187|
|predict_ms|6.742|8.167|1324.775|
|support_geometry_ms|1.386|1.651|40.433|
|cone_service_ms|8.101|9.515|1325.670|
