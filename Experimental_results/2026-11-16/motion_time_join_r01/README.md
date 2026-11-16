# 時刻付き車速・ヨー記録と距離の対応付け（オフライン）

2026-11-16。**時刻・有効性付きの運動情報を保存し、距離と映像受信時刻基準で対応付ける処理を実装した。実通信には未接続。** 新しい撮影・ROS送信・G923出力は行っていない。

## 結果

正式結果は[results_r02/audit.json](results_r02/audit.json)、[合成20ケース](results_r02/synthetic_cases.csv)、[検証記録](verification.json)。r01は数値入力の防御強化前に成功した版の履歴で、現在版の正式結果ではない。

| 検証 | 結果 |
|---|---:|
| 合成シナリオ | 20/20成功 |
| 正走・逆走・実測停止の組合せ | 3/3生成、符号・値を維持 |
| 欠落・指令値・時計不明・古い値・未来値等 | 17/17保留 |
| 排他的保存→読出し→JSON往復 | 合成19レコード同一 |
| 既存実ログの再生 | 51,202件 |
| 元距離が数値のまま維持 | 19,297件 |
| 元距離が保留のまま維持 | 31,905件 |
| 実ログ由来の運動情報との組合せ | 0件（運動情報の提出なし） |
| 新27＋関連テスト | 127成功、0失敗 |

実ログの組合せ0件は処理停止や測距精度の低下ではない。元ログに車速・ヨーの記録がなく、捏造しないことを確認した結果。[前段の空間入力監査](../motion_spatial_inputs_r01/README.md)・[距離受け渡し](../motion_range_handoff_r01/README.md)の成果を継承する。既知のframe34957/45469/46432の距離も同一。

## 実装と保存形式

[driver_motion_time_join.py](../../../src/driver_motion_time_join.py)は新規のオフライン専用module。既存telemetry/主測距/表示/FFBからimportしていない。外部依存追加なし。

`offline_measured_motion_record_v1` に次を保存する。

| フィールド | 意味 |
|---|---|
| session / receiver_clock_id / sequence | 明示した受信セッション・時計識別・記録順序 |
| source_kind / motion_frame_id | 実測odometry/旧telemetry/指令を区別、速度を表す座標frame |
| source_clock_id / source_stamp_ns | 元計測時計と整数nsの元時刻。送信wall timestampで代用しない |
| received_at_sec / logged_at_sec | 受信側monotonicの受信時刻と記録時刻。元時刻とは別 |
| measurement_valid / linear_mps / angular_radps | 有効性と符号付き実測値。不明はnull、実測0とは区別 |

これは正規化した入力事実の保存形式で、受信した任意辞書を自動的に実測認定するadapterではない。時計IDやframeも呼出し側から明示する。未受信や情報不足をnullで記録できるが、有効な組合せにはならない。

`MotionLog` は新規ファイルの排他的作成だけ。追記/上書きなし。1行16KiB、呼出し側指定の件数/容量上限あり。readerも行長/総件数/総bytesを制限し、重複JSONキー・NaN/Inf・途中行を拒否する。記録時刻/sequenceの逆順や異なるsession/受信時計もwriterが拒否する。元stampの逆行等は診断記録として残せるが、消費側は採用しない。同期ディスク書込みなので実RTC callbackで直接使用しない。

## 時計対応と採用条件

`offline_motion_clock_binding_v1` は、元時計ID/受信時計ID/session、元時計アンカーns・受信時計アンカー秒、適用開始/終了ns、誤差上限、根拠種別/識別を持つ。元時計→受信時計は **整数nsのアンカー差を取ってから** 秒へ変換する。大きなepoch全体をfloatにして微小差を失わない。

時計対応は外から与える宣言であり、IDやSHAだけで実時計が検証済みになるわけではない。今回の根拠種別は全て `synthetic_fixture_only`。`external_clock_alignment_record` を将来入力する場合も実根拠の確認が別途必要で、`clock_alignment_independently_verified=false` は今回の出力で固定。適用区間内のドリフトも誤差上限に含める必要がある。対応の自動推定、既定offset、ROS時刻=受信monotonicという仮定は実装していない。

`OfflineMotionJoiner` は以下を全て満たした場合だけ `pair_available=true` とする。

1. 距離が既存のsession/参照/順序/期限/表示レビュー条件を満たす。保留を救済しない。
2. 運動レコードのsession/受信時計/frameが指定と一致し、`source_kind=measured_odometry`、測定有効性true、v/ωが明示された有限値。
3. 受信/記録/sequence/元stampが逆順・重複でなく、時計対応が元時計と適用時刻に一致する。
4. 対応先計測時刻の誤差区間全体が運動情報の受信より過去で、映像の受信時刻以前。未来のnearestや補間を使わない。
5. 誤差上限、元計測から評価時点までの最大経過時間、映像受信時刻との最大ずれが呼出し側の明示した上限以内。

新しい運動入力が無効なら旧候補を消去。受信/記録だけが新しくても古い元計測時刻を若返らせない。期限切れでも消去する。時計異常/巻戻りは運動候補と距離保持値を消去して例外。距離保留時の出力は運動情報もnullとし、過去の組合せを再送しない。

試験ではずれ50ms・運動年齢100ms・時計誤差5msを使用した。**合成試験の呼出し値であり、実機採用値・FFB100ms要件の達成ではない。** 境界・期限・順序の防御は単体試験でも確認した。

### ここで保証していないこと

対応先は **映像受信時刻** であり、露光時刻ではない。ネットワーク・デコード遅延があるため `exposure_time_alignment_verified=false`。今回のrange packetは元受信時計の種別とsessionは持つがOS boot-clock IDを持たず、receiver_clock_idの正しい実セッションへの結合も後続の収集側の責任。既存実ログ再生の `audit/logical-receiver-scope` は照合用ラベルで、実clock証拠ではない（運動情報も対応宣言も入力していない）。

車体基準XY・対象ID・物体全体の形状・リスク勾配・FFB指令は生成しない。距離があっても運動情報がなければ `range_sample` は維持して `pair_available=false / measured_motion=null` とする。`usable_for_ffb=false / published_to_ros=false / controlling_distance=false` は固定。

## 成果物と再現

- `results_r02/synthetic_motion_records.jsonl`: 合成19レコード。実機計測ではない。異なるsessionのケースは束縛logへ混入せず、下記ケース原本に保存。
- `results_r02/synthetic_cases.jsonl`: 独立20ケースの入力・時計宣言・試験policy・結果。連続した実走行のstreamではない。
- `results_r02/synthetic_cases.csv`: 期待結果との照合表。
- `recordings/2026-11-16/motion_time_join_r02/missing_motion_pairs.jsonl`: 実距離全51,202件の運動未入力時の出力。Git対象外。
- `results_r02/audit.json`: 元正式監査/全入力/参照/実装/派生物のSHA。

このPC用。再実行は未使用の出力名に変更する。既存ファイルへの上書きは拒否する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/motion_time_join_r01/replay.py \
  --handoff-audit Experimental_results/2026-11-16/motion_range_handoff_r01/results_r02/audit.json \
  --intake-dir recordings/2026-11-16/body_display_full_intake_r02 \
  --raw-output-dir recordings/2026-11-16/motion_time_join_r03 \
  --output-dir Experimental_results/2026-11-16/motion_time_join_r01/results_r03

env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_driver_motion_time_join.py tests/test_driver_motion_handoff.py \
  tests/test_driver_motion_spatial.py tests/test_driver_body_display_guard.py \
  tests/test_driver_motion_bridge.py tests/test_driver_motion_integration.py tests/test_body_display_range_audit.py
```

先行の56テスト、82テストや90テストと重複するので累積成功件数として加算しない。

## 次の実装段階

既存telemetryの制御内容は変えず、**元odometryの計測時刻・frame・受信済み状態を収集するmetadata経路と、受信側での受動記録**を追加する段階。通信callbackで同期ファイル書込みをせず、サイズ/件数制限付きで別の保存処理へ渡す。旧senderからの値は時計情報が欠けると明示して保留し、未受信の初期0を測定停止としない。これは今回まだ実装/起動していない。

この準備中は追加撮影・GPU操作不要。実通信に反映する変更が完成してからGPU側の反映/記録確認手順を提示する。実機由来の組合せ・勾配の確認には時刻根拠と現取付の車体↔光学変換等が別途必要。現在の組合せだけでROSやG923を有効化しない。
