# 受信odometryからoffline運動形式への受け渡し計画

2026-11-16。ユーザー「作業が止まってしまっているので再開してください」により、r03実記録の監査完了後、保存情報の受け渡しへ進む。

## 対象と境界

- r03の監査済み2,045telemetryを既存offline_measured_motion_record_v1へ正規化し、排他保存→読出しで元整数stamp/frame/符号付きv・ω/受信時計/sessionが保たれることを確認する。
- sample_fields_validは構造検査で、測定有効性の独立検証ではない。measurement_valid=trueへ自動昇格せずnull、元ROS時計IDも不明nullのまま保持する。受信値0は残すが旧UIの初期0からは補完しない。
- lifecycleは運動値へ変換しない。不正metadata・未受信・unknown・反復/逆行では値や保留理由を明示し、FFB使用許可は出さない。
- 元callback/snapshot/進行ageは元observationと受け渡し結果に残す。receiver時刻へ足し引きして偽の時計対応を生成しない。
- r03には同sessionの距離ログがない。以前の51,202距離は別sessionなので実結合しない。既存joinerへの投入では測定有効性・時計対応不足が保留になることを確かめ、合成の距離に限って保留動作を検証する。
- adapterと再現scriptは実験directoryだけに置く。src runtime/UI/sender/測距/操縦/ROS/FFBを変更・起動しない。新しい実機記録・走行・撮影は要求しない。

## 検証

新形式・旧形式・未受信0・受信0・正逆の符号・元整数ns・frame・session/時計誤り・metadata不正・有効性の不当な昇格拒否・入力コピー・旧候補失効を合成テストで確認。r03原本を正式監査のSHAへ照合して全件変換し、MotionLog/read_motion_records往復と保留件数を集計する。元距離実験のsession不一致も元監査の事実として記録する。raw派生はrecordings、集計はExperimental_resultsへ保存する。
