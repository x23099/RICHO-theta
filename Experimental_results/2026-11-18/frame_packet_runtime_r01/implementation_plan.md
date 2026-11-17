# 一体packetを既定offで実runtimeへ接続する計画

複雑な互換性変更。既存の操縦/ROS publish/keyboard/FFB・camera幾何は変更しない。実機/実network/GPUを起動せずfake peerとlocal pipeで検証する。

1. sender `--frame-motion-packets`（既定false、motion-native必須）、5/10Hzのみを追加。既存camera readerを共有し、別のカメラを開かない。追加odom subscriptionは観測だけとし、新observerの全callback snapshotをsender-local履歴へ渡す。source ID/streamはtelemetryやRTPと独立、受信RTP先頭PTSで結合しない。
2. HTTP offer/answerで明示した厳密profileと両端applied SDPのMID/message上限を照合。独立unordered/no-retry channel objectを1本だけbindし、無承認/不一致/重複/再接続は測距だけ保留。private aiortc属性を使わない。
3. receiver `--motion-input packet`でのみ独立packetを測距入力とする。通常のRTP映像/telemetry/controlは継続するが、このmodeでRTPを測距へfallbackしない。GPU process/pipeは従来の1本を再利用し、余分なYOLO modelを起動しない。
4. 元capture sequence/streamをNativeFrameへ保持。parentの進行中1組にsource candidateとpacket SHAを結び、同identityで返る結果だけをログへ束ねる。callbackにGPU/pipe IOを置かない。IPCの旧厳密schemaは維持する。
5. packet受信初片からの200msをinference前/後、bridge受理・表示にも適用。これはlocal受信後期限で、元観測鮮度やFFB期限を認定しない。全権限flag false。通常modeの旧条件とログを維持する。
6. 既定off/片側のみ/不一致/欠落/旧scope/retire/finite close、実codec→local pipe→認識結果のsource照合、旧control AST不変を試験。過去SHAを更新して通さず、意図したruntime差分を新監査へ保存する。

根拠: 前段load比較（追加30Hz見送り、10Hz上限候補）、[aiortc公開API](https://aiortc.readthedocs.io/en/latest/api.html)、installed 1.14.0の複数event listenerとSDP/sourceを確認。opt-inの実機採用は未決定で、追加撮影/走行をまだ要求しない。
