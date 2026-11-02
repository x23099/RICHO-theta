# 測距処理ログの集計

状態：`INCOMPLETE_CAPTURE`。実機・距離精度の合格判定ではありません。

**注入テストまたは未確認predictorを含むデータです。実GPUの結果と混同しないでください。**

|Session|処理件数|条件付き出力|記録間の未処理番号数|
|---|---:|---:|---:|
|floor_cone_same_pose_r01_20261015_160621_378|1547|326|0|

処理・記録されたフレームだけの集計です。表示時間率、ネットワーク損失率、カメラFPSではありません。

距離はpaper7基準の条件付き推定値です。実測基準がないため精度・誤差は評価していません。

`summary.json`にsession別の保留理由、各blocker、受信後の処理時間の中央値・p95・最大値と入力SHA256を保存しています。

左右枠接触の比較ログ：1547処理frame、画像上の候補点あり1168件、追加の候補点取得0件。物理接地・距離精度の合格判定ではなく、距離・FFBへ使用していません。

同一フレーム証拠ログ：1547処理frameに選択bbox・支持点・姿勢・床モデル識別子・鮮度理由を記録。距離制御・接地判定には使用していません。

固定床モデルの比較ログ：1242処理frame。元の条件付き距離とは別集計。水平距離であり、接地・実測精度・車体座標・FFBの合格ではありません。

## Session: floor_cone_same_pose_r01_20261015_160621_378

指定ROI `[270, 0, 350, 720]`。この範囲の外は監視対象外。

|処理結果の主理由|件数|
|---|---:|
|no_candidate|354|
|support_confirmation_pending|18|
|latest_scene_image_rejected|634|
|colour_contour_reaches_roi_edge|51|
|abrupt_support_endpoint_change|9|
|newer_scene_processing_pending|147|
|CONDITIONAL_DIAGNOSTIC_NOT_VERIFIED_CONTACT|326|
|abrupt_lower_boundary_y_change|5|
|abrupt_support_width_change|3|

|処理時間項目 [ms]|中央値|p95|最大|
|---|---:|---:|---:|
|frame_age_ms|10.000|10.000|10.000|
|predict_ms|0.000|0.000|0.000|
|support_geometry_ms|0.000|0.000|0.000|
|cone_service_ms|0.000|0.000|0.000|
