# 11/17扱い：画像と運動metadataを同じpacketに束ねるローカル試作

ユーザー指定の作業日2026-11-17。実行時のOS/Git時刻や11/16の実験日付は変更しない。11/16終了commit c05ff48をorigin/mainへpushした後に着手。

## 方式比較と採用範囲

1. 既存RTP映像＋別metadataの連番/PTS一致は不採用。先頭欠落でreceiver PTS originが変わり、任意frame.opaqueもcodecを越えない。
2. aiortc内部へRTP識別hookを入れる方式は、既存映像を再利用できるがprivate API/version依存・再送/並替え/decoder境界の保守が必要。現時点のruntime monkey patchはしない。
3. PNG＋metadataは対応と画素一致を検証しやすいが、圧縮時間/帯域が大きい可能性がある。代表保存画像で比較値だけ測る。
4. 独立VP8 keyframe＋metadataを一つの有界packetにする方式を**オフライン試作**する。画像欠落後も他frame参照が不要で、同一packetのbitstreamだけをdecodeするため既存RTPの時刻基準と無関係。時計差を引かず、画像へ番号を描かない。ただし追加encode/通信帯域/画像の非可逆性があるのでライブ採用は未決定。

## 実装・検証

- 新独立moduleに長さ/全体SHA256付きenvelope、厳密JSON/既存source candidate検査、固定1280×720 VP8 keyframeのencode/decodeを追加。画像とmetadataを丸ごと同じdigestへ含める。SHAは誤結合/破損検査で認証ではない。元画像との同一hashをdecoded VP8画像へ要求しない。
- サイズ/型/重複key/NaN/flag/PTS/VP8寸法/参照frameを制限してからdecode。PyAVの公開CodecContext/Packet APIを使い、aiortc本体や既存RTC経路を書き換えない。
- 新stream/sender identity、順序、重複、旧stream混入を受信器で検査。失敗時は以前の画像・運動組を返さない。異なるPCの時刻を比較せず、露光/計測鮮度/FFB認定falseを維持する。
- 先頭/途中frame欠落、順序逆転、別stream、metadata/payload入替え、途中packet、無効motion、停止0/後退符号、独立decodeを合成で検証。
- 11/16の保存pin画像1枚をメモリ内codec比較に利用。元画像を変更/再保存せず、入力SHA・圧縮bytes・ローカルencode/decode時間のみ記録。新規撮影/ネットワーク送信/実機駆動なし。

## 非目標・次の境界

既存ライブ映像と同じdecoded frameへmetadataを貼る方式ではなく、将来の認識入力用の別packet候補。今回RTCへ接続せず、新FFB指令も送らない。受信時計での鮮度・challengeとの接続、DataChannelのfragmentation/最大message/backpressure、同時通信負荷、現在camera captureとodom履歴への接続、GPU測距への接続は次段階。最大packetをそのまま単一DataChannelで送れると仮定しない。
