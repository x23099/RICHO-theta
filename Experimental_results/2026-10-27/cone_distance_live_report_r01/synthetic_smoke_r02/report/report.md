# 測距処理ログの集計

状態：`FINALIZED_DIAGNOSTIC_LOG`。実機・距離精度の合格判定ではありません。

**注入テストまたは未確認predictorを含むデータです。実GPUの結果と混同しないでください。**

|Session|処理件数|条件付き出力|記録間の未処理番号数|
|---|---:|---:|---:|
|injected_first|6|1|0|
|injected_reconnected|2|0|0|

処理・記録されたフレームだけの集計です。表示時間率、ネットワーク損失率、カメラFPSではありません。

距離はpaper7基準の条件付き推定値です。実測基準がないため精度・誤差は評価していません。

`summary.json`にsession別の保留理由、各blocker、受信後の処理時間の中央値・p95・最大値と入力SHA256を保存しています。

## Session: injected_first

前方レンズ全体（複数コーンは保留）。

|処理結果の主理由|件数|
|---|---:|
|support_confirmation_pending|5|
|CONDITIONAL_DIAGNOSTIC_NOT_VERIFIED_CONTACT|1|

|処理時間項目 [ms]|中央値|p95|最大|
|---|---:|---:|---:|
|frame_age_ms|0.000|0.000|0.000|
|predict_ms|0.000|0.000|0.000|
|support_geometry_ms|0.000|0.000|0.000|
|cone_service_ms|0.000|0.000|0.000|

## Session: injected_reconnected

前方レンズ全体（複数コーンは保留）。

|処理結果の主理由|件数|
|---|---:|
|support_confirmation_pending|2|

|処理時間項目 [ms]|中央値|p95|最大|
|---|---:|---:|---:|
|frame_age_ms|0.000|0.000|0.000|
|predict_ms|0.000|0.000|0.000|
|support_geometry_ms|0.000|0.000|0.000|
|cone_service_ms|0.000|0.000|0.000|
