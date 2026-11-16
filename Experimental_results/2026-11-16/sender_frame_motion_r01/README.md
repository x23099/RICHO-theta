# 時計同期に依存しない送信元フレーム・運動対応：部品実装完了

2026-11-16。**送信PC内だけのmonotonic時計で、画像read-return以前のodom callbackを選ぶ独立部品を実装した。PC間時計対応の新規実装は中止した。** 実行中の映像・測距・ROS・操縦・FFBには未接続。

[計画](implementation_plan.md)、[実装](../../../src/driver_frame_motion.py)、[正式結果](results_r01/audit.json)、[合成出力4例](results_r01/synthetic_candidates.json)、[新規30試験](results_r01/tests.txt)。

## 方針変更の根拠

- [9/17設計](../../../handover/clock_independent_ffb_design_20260917.md)には、PC時計差約51〜58msによるFFB拒否と、受信側monotonicによるchallenge期限判定への変更がある。
- [9/24日報](../../../Daily_reports/2026-09-24_daily_report.md)には、challenge方式でPC間通信とG923出力まで確認した記録がある。初期の設計文書に残る「hardware未確認」は当時の段階で、最終到達点ではない。
- 現行のリスク勾配FFB目標でもchallengeは安全設計として維持されている。既存の期限・watchdog・arm条件を緩めない。元FFB実装の書換えや実機起動はしていない。

**challengeによる指令期限の保証と、画像・odometryの対応は別問題。** 今回の変更は、後者もPC間時計の同期を必須にせず進めるための送信元部品。既存のclock binding必須なoffline joinerを、そのまま認定flagだけ外して使用する変更ではない。

## 部品の動作

`SenderFrameMotion.offer()`へ既存の厳密な`driver_odometry_observation_v1`を渡し、同じsender時計で得た画像のcapture sequence/read-return時刻・sender media PTS・対応処理時刻を`associate()`へ渡す。

- callerが同じ送信PC・同じmonotonic時計を使用することが必要。IDの文字列一致だけで実時計の同一性を認定しない。
- 最大1,024観測の有界履歴。試験はcapacity4、callback/progress各100ms、capture待ち200msを**合成試験の指定値**として使用した。実機採用値・FFB期限・誤差予算ではない。
- 画像取得より未来のcallbackしかない場合は保留。未来callbackの前に記録された過去callbackがあれば、その最新のものだけを候補とする。補間・未来nearest・旧有効値による救済なし。
- 直近の過去callbackが無効、stamp反復/逆転、frame不一致、古すぎる場合は数値を出さない。未受信と実測停止0を分離し、符号付きv/ω・元整数ns stamp・元観測をそのまま保持。
- callback sequence欠落、観測drop増加、offer lock競合の履歴は旧値で埋めず失効。unknown/busy観測後も旧値を復活させず、新しい観測callbackが必要。
- sender混在、snapshot/フレーム順序逆転、不正metadata等ではinstanceを退役し、新stream instanceでのみ再開。lock取得はnonblocking、IO/画像コピー/ROS呼出しなし。

出力の`local_pair_available=true`は**観測済みの過去callback候補が存在する**という意味だけ。実測鮮度・露光同期・車体座標・FFB利用許可ではない。`odometry_observation.snapshot_mono_sec`は元のsnapshot読出し時刻を保存し、画像時刻へ偽装しない。`callback_to_capture_sec`はcallbackからread-returnまでの差であって、計測/露光/輸送の遅延ではない。

### 残す制約

camera read-returnはセンサ露光時刻ではなく、odom callbackは元計測時刻ではない。ソース観測の欠落やstamp非進行を拒否しても、計測の実年齢そのものを証明するわけではない。callbackを全件観測できなければ履歴が不十分な区間は保留になる。`receiver_frame_identity_verified`・`exposure_time_verified`・`header_clock_relation_verified`・`source_freshness_verified`・物理/FFB/ROS flagsはすべてfalse。

## 受信画像へまだ接続しない理由：実codecとRTPの確認

現環境のaiortc **1.14.0**、PyAV/NumPyの版と3ライブラリソースSHAを正式結果に保存した。private実装は診断試験でのみ参照し、runtime monkey patchや外部ライブラリ変更はしていない。

| 合成sender PTS | 先頭から受信した場合のPTS | 先頭captureが欠けた場合のPTS |
|---:|---:|---:|
| 0 | 0 | 欠落 |
| 3,000 | 3,000 | 0 |
| 6,000 | 6,000 | 3,000 |

実`TimestampMapper`を使い、32bit RTP wrapを含む条件で確認。受信先頭PTS0はsender先頭capture0の証明にはならない。senderはRTPのtimestamp originを加え、receiverは最初の完成frame timestampを基準に振り直す。実VP8 encode/decodeでは1280×720を維持する一方、PyAV frameの`opaque`に入れただけのstream/capture識別情報は消える。PTS変換も1tick以内の丸めがあり、単純等値や任意tagだけで実画像へ対応づけない。

根拠：実インストール済みソースと、[aiortc sender v1.14.0](https://github.com/aiortc/aiortc/blob/1.14.0/src/aiortc/rtcrtpsender.py)、[receiver v1.14.0](https://github.com/aiortc/aiortc/blob/1.14.0/src/aiortc/rtcrtpreceiver.py)。upstream mainも参照したが、今回の再現試験は上記インストール済み版。ネットワーク上の実パケット欠落試験ではなく、時刻変換器へ欠落相当の列を入れたローカル試験。

**次の実装対象は、このsource bundleと受信した実画像を、欠落・再接続でも取り違えない識別方法。** 到着順、近い受信時刻、初回PTS0、decoded画像のハッシュを元画像ハッシュと同一視する方法では代用しない。新しいPC時計同期へ戻すこともない。

## 検証結果

新規30試験と、既存odom観測、操縦不変性、FFB relay/publisher、時計観測/受信記録、native codecの関連試験を合わせて**174件成功、0失敗、3.49秒**。先行102成功は修正前の部分suiteで、加算しない。独立した実機実験数ではない。

正式checkでも新規30件成功・skipなし、合成4例のJSON保存。既存測距/表示12ソースのSHAは以前の正式実機監査と一致。`webrtc_stream.py`、`webrtc_receive_ui.py`、`theta_rtc_diagnostic.py`、既存odom observer、FFB relay/publisherは今回無変更。新部品を既存callbackへ接続したわけではなく、動作中の映像・距離表示や通常telemetry payloadも変えていない。

再現時は未使用の出力名を指定する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/sender_frame_motion_r01/check.py --output-dir Experimental_results/2026-11-16/sender_frame_motion_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_driver_frame_motion.py tests/test_driver_odometry_observation.py tests/test_driver_motion_integration.py tests/test_collision_ffb_relay.py tests/test_collision_ffb_publisher.py tests/test_driver_sender_clock_observation.py tests/test_driver_telemetry_recording.py tests/test_theta_rtc_diagnostic.py
```

これは解析PC向け再現コマンドで、GPU PCにこの絶対パスを入力する手順ではない。今回はGPU反映、追加記録、撮影、走行、時計設定変更を依頼しない。日報・commit・pushは今回未依頼で実施していない。
