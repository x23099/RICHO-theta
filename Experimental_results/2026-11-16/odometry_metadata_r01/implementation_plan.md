# 元odometryの受信状態・時刻・frameを送受信する

2026-11-16。複数ファイル・通信metadata・安全性に関わる変更。実受信telemetry2,208件が全0で元計測が不明という先行監査を根拠に、追加走行の前に入力事実を区別する。

1. 既存senderのodometry購読callbackから、元header stamp、child_frame_id（twist座標）、header.frame_id、符号付きv/ωを一つのスナップショットとして保持する。未受信はnull。既存のUI用値と操縦publisherの内容は変えない。
2. sender process IDと同一process monotonicのcallback時刻・送出時の観測時刻・callback経過時間・stamp進行/反復/逆行を付加する。ROS headerの時計はメッセージだけでは同定できないため、sender時計やreceiver時計と同一視しない。鮮度認定・FFB権限はfalse。
3. bounded・標準Pythonのみのobserverを新設し、callbackと送信loopの同時参照でv/ω/stampを混ぜない。observer競合/異常はmetadataだけを無効化し、既存telemetry/操縦を継続。
4. 受信側は対応schemaの厳密検査後に、別のv2記録envelope内へmetadataを保存。旧senderはv1を維持。未知版/不正metadataは明示して不採用とし、旧top-level数値で救済しない。任意message全体は保存しない。
5. ROS公式Odometry定義でtwistのframeを確認。docs.ros.orgはアクセス拒否だったため、ROS2 common_interfaces公式GitHub humble定義を参照。新しいROS APIや依存は追加せず、元stampとmonotonic事実のみを扱う。
6. 未受信0/受信0、正逆走、凍結stamp、反復、逆行、欠落/不正stamp、frame違い、古いcallback経過、旧版/新旧混在、observer異常、制御ASTの不変性を模擬検証。TelemetryNode全体の旧固定hashは、厳密に指定したmetadata追加だけを除くと元hashに一致することを確認し、baselineを書き換えない。
7. 実sender/GPUへは反映しない。matsunucとGPUPCの双方へ反映が必要と明記し、実機・ROS・ネットワーク・FFBを起動せずローカル検証と手順を保存する。過去の実記録を新metadata付きとして再解釈しない。
