# 11/18 独立packet接続部の実装計画

複雑な互換性・終了境界を含む変更。既存RTC、ROS、表示、操縦、G923へ接続せず、実ソケットを開かない。

1. RFC 8841 §6に従い、明示したremote SDPのapplication MIDとlocal受信能力からmessage上限を選ぶ。未指定64 KiB、0は無制限の意味だがアプリ上限16 KiBを維持。不明/曖昧なSDPは推測しない。
2. 送信元画像のコピー・検査はRTC callback以外のproducerで行う。専用daemon workerでencode/packet検査を行い、最新待機1件だけ保持する。準備済みfragment planをowner threadへ渡し、channel.sendはownerでのみ行う。
3. 受信callbackは有界binary inboxへ非待機投入するだけ。再構成・検査・decodeは専用worker所有。overflow/lock競合は当該instanceを退役し、旧候補/遅延結果で復活させない。初片からの期限をdecode完了時も確認する。
4. send例外・閉鎖・時計逆行・有限close、blocked codec、遅延完了、再接続の別scopeをfake channelで試験する。hung codecの強制停止はできないため、closeのworker_doneと候補失効を区別する。
5. 正式試験結果・ソースSHA・既存runtime不変を保存する。実帯域/実負荷/共存性能/元観測鮮度や物理精度の認定ではない。日報・Git書込み・実機起動は行わない。

根拠: [RFC 8841 §6](https://www.rfc-editor.org/rfc/rfc8841.html#section-6)、[RFC 8831 §6.6](https://www.rfc-editor.org/rfc/rfc8831.html#section-6.6)、[aiortc公開API](https://aiortc.readthedocs.io/en/latest/api.html#data-channels)。private SCTP能力属性やRTP改変は使わない。threadの待機中にcodecは停止不能なので、無限joinや非daemon executorを使用しない。
