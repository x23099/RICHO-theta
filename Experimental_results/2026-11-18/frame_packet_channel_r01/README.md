# 11/18：独立packet channel接続部をfake通信で検証

画像・運動一体packetの**上限算出、callback外worker、owner threadでのsend、有限終了**を実装した。新規34件を含む関連258件成功、失敗/skip 0、4.26秒。[正式監査](results_r01/audit.json)、[試験出力](results_r01/tests.txt)、[計画](implementation_plan.md)。

実codecと実threadは動かしたが、channelはfakeであり、実peer/ソケット/ROS/カメラ/G923を起動していない。既存RTCや操縦へは未接続。ライブ採用、実通信性能、元計測鮮度、物理精度、FFB利用を認定した結果ではない。

## 実装

[新module](../../../src/driver_frame_packet_channel.py)と[試験](../../../tests/test_driver_frame_packet_channel.py)。既存[flow module](../../../src/driver_frame_packet_flow.py)には、workerで検査済みのimmutable planをownerへ渡す内部入口だけを追加した。従来の`offer(wire)`は同じ検査と制限を維持し、既存27件も再実行成功。

### 上限と接続契約

`negotiated_message_bytes`は**既に適用されたremote SDP**の明示MIDを選び、remote広告、local能力、アプリ上限の小さい値を採る。`max-message-size`省略は65,536bytes、0は無制限として扱いつつアプリ上限16,384bytesを維持。1,024bytes未満、重複/非canonical整数、MID不明/重複、inactive/拒否されたapplication、不明protocol等は推測せず拒否する。全SDP実装ではなく保守的なmodern SCTP subset。installed aiortcの公開capability取得とSDP解析との整合も、peer起動なしで確認した。

この関数自体がoffer/answerや接続交渉を送るわけではない。local能力は現接続の広告に対応させ、両側で同じfragment上限を設定する必要がある。片側だけ`app_cap`を変えてよいという契約ではない。MID・channel object・sender/stream IDを実接続へ束ねるopt-in runtime入口はまだない。SDP変更/再接続時には新しいscope/instanceを必要とする。

送信adapterは、明示した独立channel objectだけを使う。label/protocolは`theta-frame-motion-v1`、unordered、maxRetransmits=0、maxPacketLifeTimeなしを要求する。labelは一意性・認証根拠ではなく、既存`control`/`telemetry`をlabel検索して転用しない。今回作成したfake channelの設定であって、実channelの作成・remote受付は追加していない。

### 所有権と有界処理

| 場所 | 処理と上限 |
|---|---|
| sender producer（RTC callback外） | native画像copyとcandidate検査。元配列/辞書を後から変更してもworker入力は変わらない |
| sender専用worker | encode＋SHA/JSON/fragment plan検査。処理中1＋最新待機1、準備済み最新1。処理中に新入力が来た場合は旧完了を採らず最新待機を処理 |
| sender channel-owner | `pump`で準備済みplanを受け、最大32片/回の明示budgetでsend。実codecや全体SHA/JSON解析をしない。前段schedulerの進行中1＋最新待機1/age/buffer制限を継承 |
| receiver message callback | bytes型・長さ・local clock検査、非待機lock取得、有界inbox投入のみ。codec/全体hash/JSON/画像copy/disk IOなし |
| receiver専用worker | 初片時刻を維持して再構成/検査/decode。単一workerだけがassembler/decoderを所有 |
| receiver consumer（単一owner） | `take`で完成組を1回だけ取得。初片からの同じ期限を、decode完了後・消費時にも確認 |

受信inboxは最大128片、16KiB設定ならpayload計2MiB以下。これと別に組立1packet最大2,105,399bytes、codec入力/出力画像、Python objectや一時copyがある。送信側にもnative BGR各2,764,800bytesの画像jobとprepared/active/pending packetが存在する。**総heapやCPUのハード上限を認定していない。** 最大packetのburstが必ず128片inboxへ収まる保証もなく、溢れた場合は退役する。

受信overflow/lock競合では、その接続instanceを退役し旧候補を渡さない。自動復帰や旧片の再利用はせず、新scopeで作り直す契約。短いlockはcodec/コピー/IOを含まないが、Python/GIL/OS scheduling下のcallback最悪時間を保証する測定ではない。

### 失敗・期限・終了

- send例外、closed/closing channel、不正buffer、時計逆行はpacket adapterを終了。引き渡し済みbytesは取消不能。`messages_sent`はsend呼出し正常終了数であってremote配送数ではない。
- `bufferedAmount`の対象は当該channel。SCTP内部滞留/再送/flightや他trafficを含む全遅延保証ではない。unordered/no-retryでも他通信と資源競合しない保証にはならない。
- 受信arrival時刻とworker処理時刻を分離。queue内の古いarrivalと現在時刻を交互にassemblerへ入力して、正常な待ちを時計逆行と誤判定しない。queue待ちも初片からの期限に含め、decode前/後/消費時に期限超過を破棄。
- `close(timeout_sec)`は0〜1秒の明示join上限。daemon workerのcodecを強制停止はできない。blocked codecの場合は`False`（worker停止未完了）を返し、候補と待機は無効化する。後からcodecが返っても結果は公開せず、finallyで状態を解放する。強制プロセス隔離やdecoder sandboxを実装した結果ではない。
- close/send失敗/overflow以後の遅延結果を再採用しないこと、旧streamの片が新接続へ混ざらないことを確認。物理・FFB・ROS flagsはfalseのまま。

sender fixtureは10.05秒系、receiverは700,000秒系でend-to-end検証。PC間時刻の引き算や同期/換算は使わない。ただし受信初片より前の輸送遅延、露光/元odomの鮮度は不明のまま。

## 根拠と変更範囲

全34新試験に、上限/default/0/不正SDP、public aiortc API、実worker encode→fake send→実worker decode、thread owner確認、入力copy、最新待機置換、保留運動保持、backpressure/期限、send/encode/decode例外、queue/lock詰まり、blocked codec/finite close/遅延完了、再接続scope、時計異常等を含む。

関連258成功には旧224件が含まれ、先行257成功/正式258成功を加算しない。先行試験の後に公開aiortc capabilityの1試験を追加した。正式監査はHEAD `33feb17918cd1c204950c2ee214573272de2aeea`（ユーザー側commit `1118v1`）をbaselineに、既存送受信/capture/odom/recording/FFB 8 sourceのSHA不変を確認。過去の距離/表示12 source、11/17 packet/source実装の保存SHAも一致。

カメラ画像を新規撮影・加工・再保存していない。今回は合成native画像と合成運動だけの試験。旧flowの正式結果は当時の履歴として変更せず、今回変更後のflow SHAを新しい監査へ保存した。

作業日は11/18、実行UTCは監査にそのまま保存。新日報の作成依頼ではないため日報へ追記していない。今回の変更は未commit/未pushで、Git書込みは行っていない。

## 次の作業

次は既存video encodeと追加packet encodeを保存画像で併走させ、CPU・処理遅延・生成bytes・最新入力の破棄を計測し、採用可能なrate/方式を決める。fake channel結果だけでは実併用可能とは決めない。その後、capture/odom取得点・接続scope・GPU認識入力へのopt-in接続を追加し、初めて実通信の確認手順を提示する。

**現段階の追加撮影/走行、GPUPC反映、時計設定、G923試験は不要。** 車体TF・車幅・障害物点の意味と、risk-gradient/抵抗FFBへの変換は依然別のgate。現在の測距をそのまま車体の空き距離やFFB入力に昇格させない。

## 再現（解析PC、未使用の出力名）

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_channel_r01/check.py --output-dir Experimental_results/2026-11-18/frame_packet_channel_r01/results_r02
```

既存runtime等がbaselineと同一である条件も検査するため、将来それらを変更した場合は監査を更新して新結果として記録する。過去のSHAを書き換えて通さない。

## 外部根拠

[RFC 8841 §6](https://www.rfc-editor.org/rfc/rfc8841.html#section-6)はmessage上限の方向性・省略時64KiB・0・整数構文を規定。[RFC 8831 §6.6](https://www.rfc-editor.org/rfc/rfc8831.html#section-6.6)の大message占有/16KB指針を継承。[aiortc公開API](https://aiortc.readthedocs.io/en/latest/api.html#data-channels)のcapability・bufferedAmount・channel属性を利用する契約で、private SCTP/RTP属性への接続はない。
