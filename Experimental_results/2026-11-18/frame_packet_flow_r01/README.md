# 11/18扱い：有界fragment・再構成・最新待機制御を実装

**11/17の画像・運動一体packetに対して、分割/再構成、欠落/期限/再接続検査、進行中1組＋最新待機1組の送信スケジューラを実装した。** 既存RTC/ROS/操縦/測距/FFBには接続していない。送信のhand-offを生成するだけで、実networkへsendする処理は追加していない。

11/17日報・代表資料2点の作成/根拠確認を先に終えた後、ユーザー指定の**11/18作業枠**として着手。実行日はauditのUTCどおりで、OS/Git時計や元資料の日付を改変していない。ユーザーがGit操作を行うため、今回こちらではcommit/push/pullをしていない。

[計画](implementation_plan.md)、[新module](../../../src/driver_frame_packet_flow.py)、[新規27ケース](results_r01/tests.txt)、[正式結果](results_r01/audit.json)、[再現script](check.py)。

## 実装と境界

### 分割・再構成

- 固定長fragment headerへsender/stream ID、capture sequence、全体長、index/count、全体packet SHAを保存。headerは88bytes。呼出し側指定のmessage上限は1,024〜16,384bytesで、header込み。**実際のremote max-message-size以下を選ぶ交渉処理は未実装**。
- 受信器は最大1組だけを保持。新しいsequenceで古い途中/完成未消費分を消し、旧fragmentは新しい組へ混ぜない。順不同を許容し、同一重複は無視、不一致重複は当該sequenceを失効。
- 受信最初のfragmentからのlocal期限を、追加片/重複/完成で延長しない。完成後も同じ期限内に1回だけ引き渡す。期限切れ後の同sequenceは復活せず、受信時計逆行/closeでinstanceを退役。
- layout/サイズ/countを確認してから、最大2,105,399bytes（旧packet上限）までの領域を確保。全片完成後にSHAとinner packet/schema/source identityを照合し、decodeは行わない。保存byte数の上限は全Python heapの上限ではなく、bitmap/オブジェクトや完成bytesへの一時copy等は別。
- well-formedな別sender/streamの片は現在の組へ混ぜず無視。malformed入力はfail-closedで現在組を失効する。SHAは認証ではない。

### 送信待ち・backpressure

- 進行中1組と最新待機1組だけを保持し、新しい入力では待機だけを置き換える。毎回進行中を中断して低帯域時に何も完了しなくなる設計は避ける。
- sender内の同じmonotonic時計でcapture ageを検査し、期限超過を破棄。待機への入替えやbuffer確認で期限を延長しない。
- `buffered_amount + 次fragment長 <= 指定上限`の時だけhand-off。送信不能/不正buffer情報は未送信分を破棄、closeで再開を拒否。実際のsend失敗時はcallerがcloseする契約。
- **hand-offは送信成功や配送ではない。** 既にtransportへ渡したbytesをこの部品から取り消すことはできない。`bufferedAmount`が表す当該channelのqueueと、SCTP内部の再送/flight、他の映像/操縦通信全体の滞留は別。全通信遅延やFFB100msを保証しない。

全methodは同じworker/event ownerが順次呼ぶ前提でthread-safeではない。packet検査・全体SHA/組立・encode/decodeをRTC/UI callbackへ直接置く構成ではない。まだそのworker接続もしていない。

## 合成byte queueシミュレーション

入力画像は11/16 pin5186の元PNG SHAを確認しメモリ内で1回encode。代表packetは101,959bytes、16KiB message上限では7片。再encode画像を保存せず、元画像fileは不変。運動とcapture sequenceは合成fixtureであり実画像の計測odomではない。

設定は**合成指定値**：20Hzで20組生成、2ms刻み、sender capture age/receiver初回fragment期限各200ms、logical channel byte queue上限32KiB。両PCのclock originを意図的に10秒系と700,000秒系へ分け、引き算しない。

| 論理link設定 | 完成して引渡し | 最新待機への置換 | 備考 |
|---|---:|---:|---|
| 32Mbps、欠落なし | 20/20 | 0 | 全sequenceが順序どおり一致 |
| 8Mbps、欠落なし | 11/20 | 9 | 古い待機を破棄。1,2,4,6,…,20を引渡し |
| 1Mbps、欠落なし | 0/20 | 14 | sender期限切れ6、帯域不足を0完成として保持 |
| 32Mbps、frame5のfragment1を欠落 | 19/20 | 0 | frame5を採用せず、frame6以降へ復帰 |

このmodelの最大messageは16,384bytes、logical byte queue最大32,768bytes、sender保持packet bytes最大203,898、receiver最大101,969。close後の保持は両側0。全完成packetは元のwireとbyte一致し、順序/重複/初回受信後期限も検査した。

**これらは実network帯域、ライブFPS、matunuc/GPUPC性能ではない。** CPUのencode/decode時間、Wi-Fi jitter、損失再送、SCTP/DTLS overhead、他の映像/操縦trafficをmodel化していない。前日のencode約26ms/decode約15msを消費時間へ組み込んだ実時間試験でもない。1Mbpsで完成0なのは実装上の成功配送ではなく、古い途中データを採用しない負荷限界の例。

再構成期限は初回fragment到着以降の制限であり、その前のtransport遅延・露光時刻・元odom年齢は不明。source freshnessや実FFB利用を認定しない。

## 検証

新規27テストと既存packet/source-frame/odom/操縦/FFB/記録/native codec等で**224成功、0失敗、3.93秒**。部分suite80成功・正式check27成功は同じ試験を含み、別件数として加算しない。

27ケースには実VP8 packetの分割→逆順再構成→独立decode、最初/途中packet欠落、単片欠落、期限延長禁止、旧片混入、conflict重複、全体SHA/inner identity不一致、malformed/巨大layout、scope/close/clock異常、backpressure/最新待機/進行中維持等を含む。既存11/17 packet/source部品はbyte不変で正式auditのSHA一致、旧距離/表示12 sourceも一致。構文・diff checkを確認。

## 次に残すこと

この部品は未接続。次は実channel上限の交渉、encoder/再構成/decodeをcallback外へ置くworker所有権、実send失敗と終了処理への接続をローカルfake peerで検証する。その後に追加encode/帯域が既存映像・操縦へ与える負荷を測り、ライブ方式を採用するか判断する。**同時通信が問題なく動くと、今回のmodelだけで結論しない。** 実source capture/odom履歴とGPU入力、車体TF/車幅/点の意味、FFBは別のgate。

現時点のGPUPC反映・追加撮影/走行・時計同期設定・G923試験は不要。新部品・日報・資料はローカル未commit/未pushで、Git操作はユーザーに委ねる。

## 再現（解析PC、出力名は未使用）

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_flow_r01/check.py --output-dir Experimental_results/2026-11-18/frame_packet_flow_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_driver_frame_packet_flow.py tests/test_driver_frame_packet.py tests/test_driver_frame_motion.py tests/test_driver_odometry_observation.py tests/test_driver_motion_integration.py tests/test_collision_ffb_relay.py tests/test_collision_ffb_publisher.py tests/test_driver_sender_clock_observation.py tests/test_driver_telemetry_recording.py tests/test_theta_rtc_diagnostic.py
```

## 根拠資料

[RFC8831 §6.6](https://www.rfc-editor.org/rfc/rfc8831.html#section-6.6)は、大きなmessageによるSCTP占有と、interleaving未対応時の16KB指針を示す。[RFC8841 §6](https://www.rfc-editor.org/rfc/rfc8841.html#section-6)はmax-message-sizeの交渉を定義する。[aiortc API](https://aiortc.readthedocs.io/en/latest/api.html#aiortc.RTCDataChannel.bufferedAmount)のbufferedAmountは当該channelの送信待ちbytes。これらを設計の根拠にしたが、この独立試作が実装済みRTC全体のdelayやmessage互換性を検証したわけではない。
