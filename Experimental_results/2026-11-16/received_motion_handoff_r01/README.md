# 実受信odometryをoffline運動形式へ受け渡す検証

2026-11-16。**r03実受信2,045件を既存の運動保存形式へ変換し、保存→読出し後も同一であることを確認した。** 同時に、元時計の同定・時計対応・測定有効性の独立確認がない情報を距離との有効ペアへ自動昇格させないことを確認。実験用offline処理で、運転runtimeやROS/FFBへ接続していない。

[実装計画](implementation_plan.md)、[adapter](adapter.py)、[再現script](check.py)、[正式集計](results_r01/audit.json)。元提出物は[受信疎通の監査](../odometry_metadata_received_audit_r01/README.md)で確認済みのreceived_telemetry_odom_20261116_r03.tar.xz。

## 確認結果

| 項目 | 結果 |
|---|---:|
| 元イベント | 2,046（開始1＋telemetry2,045） |
| offline_measured_motion_record_v1への変換 | 2,045件 |
| 排他保存→read_motion_records往復一致 | 2,045 / 2,045 |
| 受信したv/ω=0をそのまま保持 | 2,045 / 2,045 |
| 整数ns元stamp・frame・session・受信時計・時刻・sequence | 維持 |
| measurement_valid / source_clock_id | 全null、推定なし |
| 測定有効性不明 / 元時計不明 / 時計対応なしの保留理由 | 各2,045件（同じ記録に付く重複理由） |
| 以前の距離ログと実結合した件数 | 0件、別sessionのため試行しない |
| 新adapter10を含む関連テスト | 145成功、0失敗（1.89秒） |
| 実行中の送受信・測距・操縦・ROS/FFB変更 | なし |

以前の145件以前に確認した63/60/200/49等は重複するsuiteで、累積件数として合算しない。今回の追加はadapterの10テスト。疎通確認で受信した0を保持することと、独立に検証済みの運動入力としてFFBへ供給することを区別する。

## 変換方針

`transfer()` は明示されたsession/receiver時計のtelemetryだけを受理。共通envelopeは従来厳密validator、versioned観測はchecked_observationで検査する。検査用コピー以外に原記録を変えず、返却observationのinvalid_fieldsも独立コピー。lifecycle・不明schema・不正型・権限flag・余分なfield・scope誤りは拒否する。

- 受信済み観測: 元callbackのheader_stamp_ns・motion_frame_id・v/ωを保持し、source_kindは元odometry由来を表すmeasured_odometry。**measurement_validはnullのまま**で、source_kindだけではjoinerに採用されない。
- 未受信/競合等で状態不明/旧sender/不正または未知metadata: v/ωをnullとし、旧UI数値の0で補完しない。理由を残す。
- 正の元stampがあっても、source_clock_idをsender-processやreceiver時計へ置換しない。時計対応は作らない。
- sample_fields_valid=trueは構造検査のみ。measurement_valid=trueは生成しない。反復/逆行/欠落stampは対応理由も残す。
- callback・snapshot・progress age・pose frame等の元観測はwrapperのobservationへ保存。異なる時計間の引き算や自動offset推定は行わない。
- replay_only=true、pairing_eligible=false、usable_for_ffb=false、published_to_ros=falseを維持する。

raw派生は `recordings/2026-11-16/received_motion_handoff_r01/normalized_motion.jsonl` と `handoff.jsonl`。後者は元観測・複数保留理由・元受信行SHAを含む。全入力と派生・adapter・script・既存運動module・テストのSHAを正式集計に記録した。

## 結合の境界と次の段階

今回の受信sessionは `4852ed17f96f41cfbd13aa38d0ba6592`、receiver時計は `receiver-process/dc5c953f531a473697cec72b2c044ff3`。以前の51,202件の距離sessionは `e52bb32f03d6488ebf37d769f46ec37a`。別実験の距離と運動を時刻が近い等の理由で組み合わせない。実ペア0は受信失敗でも測距精度低下でもなく、必要な同session距離・時刻根拠がないことの明示。

合成テストでは、採用中の旧運動候補に新しい未認定観測を投入したとき、既存OfflineMotionJoinerが `motion_measurement_invalid_or_missing` で旧候補を失効させ、距離値は保ったままpair_available=false/measured_motion=nullになることも確認した。この合成距離は実r03の測距実績とはしない。

次は、元ROS時計とsender/receiver時計を同定する根拠・誤差上限・運動入力の有効性条件、および現取付の車体↔光学変換を整理する段階。同時計・同sessionの結合を確認する試験が必要になった時点で手順を提示する。今すぐ同じ停止記録・走行・コーン撮影を繰り返す必要はない。時計対応/車体XY/リスク勾配/実FFBを完成済みとは扱わない。

## 再現

未使用の出力名を指定する。実ROS/カメラ/ネットワーク/G923は不要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/received_motion_handoff_r01/check.py --source-audit Experimental_results/2026-11-16/odometry_metadata_received_audit_r01/results_r01/audit.json --output-dir Experimental_results/2026-11-16/received_motion_handoff_r01/results_r02 --raw-output-dir recordings/2026-11-16/received_motion_handoff_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_received_motion_handoff.py tests/test_odometry_metadata_live_audit.py tests/test_receiver_telemetry_live_audit.py tests/test_driver_odometry_observation.py tests/test_driver_telemetry_recording.py tests/test_driver_motion_time_join.py tests/test_driver_motion_handoff.py tests/test_driver_motion_spatial.py tests/test_driver_motion_integration.py
```
