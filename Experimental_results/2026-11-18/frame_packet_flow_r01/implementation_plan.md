# 11/18扱い：有界fragment・再構成・送信待ち制御

2026-11-17のユーザー依頼により、11/17日報作成完了後の11/18作業枠。OS/Git時刻、元資料の日付は変更せず、Git操作はユーザーに任せる。

## 前提と範囲

- 11/17の一体packetをそのまま巨大DataChannel messageとして送らない。RFC8831 §6.6のinterleaving未対応時16KiB指針、RFC8841のmax-message-size、aiortcのbufferedAmountを参照する。16KiBなら常に安全とせず、実remote上限以下の値を呼出し側で選ぶ必要がある。
- 今回は独立した分割/再構成とスケジューラのローカル試作。新しいRTC/ROS/FFB起動やネットワーク送信、既存callbackの変更はしない。前日のpacket/codec/source candidateも変更しない。

## 設計

1. fragment headerにsender/stream ID、capture sequence、全体長、index/count、全体packet SHAを固定長で入れる。全体・単片・個数を制限し、長さ/位置を検査してから有界領域へ格納。
2. 再構成は現在の1組だけ。新しいsequenceで古い途中/完成未消費分を失効。旧fragmentは新しい組へ混ぜない。順不同は許容、同じ重複は期限延長しない、不一致重複は当該組を失効。
3. 最初のfragment受信からのlocal期限を、組立完了や重複でリセットしない。完成後も同じ期限内に一度だけ引き渡す。別stream、途中欠落、全体SHA/inner packet不整合は採用しない。受信時計逆行/closeで退役。
4. 送信待ちは進行中1組＋最新待機1組まで。毎回進行中を置換して低帯域時に完了を妨げる方式を避け、待機だけを最新へ更新する。sender内capture時刻からの期限を超えた組は破棄。fragment生成はencoder/worker側で行い、bufferedAmount＋次messageが上限を超える間はhand-offしない。
5. hand-offは実際のsend成功と同一視しない。実送信失敗はcloseで残りを失効する契約。既にtransportへ投入したbytesは撤回できず、buffer上限は当該channelの値で通信全体/FFB遅延を保証しない。
6. 合成fragment、実VP8 packetの分割往復、欠落/順序/重複/競合/期限/再接続/低帯域の論理シミュレーションを行う。負荷不足で完了0の場合も隠さず記録し、実通信性能と混同しない。

## 非目標

再構成時計は最初のfragment到着後の経過で、元露光・計測・片道遅延を認定しない。SHAは認証ではない。実SDPとの上限交渉、RTC transport hook、encoder worker/thread連携、GPU測距への接続、車体TF/FFBは未実装のまま。
