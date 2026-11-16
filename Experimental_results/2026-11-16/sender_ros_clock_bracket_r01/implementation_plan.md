# ROS時計と送信monotonicの読出し区間を記録する

2026-11-16。ユーザー「すすめてください」で実装する。元stampは貼付Kobukiソースでdriver更新時のnode clock由来と分かったが、時計対応・計測瞬間・現在binary一致までは認定していない。

## 今回の境界

送信node自身のROS nowをmonotonic_nsで前後から挟み、時計種別/use_sim_time/ROS clock active状態・順序・世代とともに既存telemetryの独立keyへ追加する。odom metadataはv1のまま保持し、同一sender IDで対応させる。センサ取得時刻やKobuki nodeとの同時計性を自動認定しない。

受信記録は新keyがある場合のみv3 envelopeとして厳密検査して保存。旧senderは従来v1/v2を維持し、元のUI値・距離・操縦・接続・topics・FFB・OS時計は変更しない。失敗は新metadataだけを不採用にする。受信callbackのdisk I/Oは追加せず既存有界queueへ保存する。

ROS逆行/設定変化はgenerationを分ける。monotonic異常や観測失敗で過去の区間を再利用しない。前進jump全件検知や連続誤差上限をこの有限サンプルから保証しない。ROS−monotonic差の区間は1回の読出し観測であって、時計drift/読出し精度・実headerとの対応を含む検証済みbindingではない。

PC間4timestamp交換は今回追加しない。送信PC内の区間と受信monotonicは別時計として保存する。新sender/receiverへまだ反映せず、まずfake ROS/peerで生成→JSON→受信→ファイル保存と、従来制御AST不変を検証する。実機を動かさない。配布・実記録は検証後に別手順を出す。

## 根拠と選択

ROS2公式rclpy humbleのNode.get_clock/Clock.now/clock_type、Python3.10公式time.monotonic_nsを確認。整数nsで差を保持し、epoch全体をfloatにしない。既存odom schemaへ項目を混ぜるより、独立schema/key＋記録v3が旧観測の意味と互換性を維持しやすい。ROS依存は既存node getterへ限定し、新validator/samplerは標準ライブラリだけにする。
