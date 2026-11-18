# PNG frame/motion packet 実回線 transport 試験 r01：結果（11/18）

**実SCTP/DTLS DataChannelで、送信側がchannelへ渡し切った296 frameが、受信側で296 frameすべて再構成・期限判定を通ってアプリまで届いた（frame_completion_ratio = frame_publication_ratio = 1.0）。** ただし今回は**PNG 1 frameが約128 KB（上限見積り）で、payloadは最大でも4.54 Mbps**であり、目標の40.49 Mbps（約1 MB/frame × 5 Hz）の約1/9しか流れていない。**transportの成立は確認できたが、40 Mbps級の帯域共存は未検証**である。

## 1. 定量結果

| 項目 | 値 |
|---|---:|
| 試験時間（sender / receiver） | 66.737 s / 82.031 s |
| 要求rate | 5 Hz（probe下限） |
| 送信offer | 303 frame |
| 送信前に期限切れ | 7 frame |
| **channelへ渡し切ったframe** | **296** |
| 生成fragment | 2,311 |
| fragment/frame | 7.81 |
| message上限 | 16,384 B |
| **payload上限見積り** | **37,863,424 B（4.539 Mbps）** |
| 送信実効rate | 4.435 Hz |
| 受信観測span | 66.315 s |
| 受信側publish rate | 4.464 Hz |
| **受信で再構成できたframe** | **296** |
| **アプリまで届いたframe** | **296** |
| frame_completion_ratio | **1.000** |
| frame_publication_ratio | **1.000** |
| 受信側で完了前に置換されたpacket | 4 |
| 期限切れframe（受信） | 0 |
| duplicate / invalid / conflict | 0 / 0 / 0 |
| 受信側latency（初片到着→publish） min / mean / max | 2.62 / 36.24 / 114.66 ms |

送信側の`scheduler`：`offered=303`、`expired=7`、`pending_replaced=0`、`held_for_buffer=1,409`、`packets_handed_off=296`、`peak_retained_bytes=125,757`。`held_for_buffer`はchannel bufferが閾値を超えてfragment送出を待った回数で、backpressureが働いたことを示す。

## 2. 何が分かったか

- **frame単位では欠損がない。** 296渡して296完成・296到達。fragmentの破損・重複・競合も0。受信側の0.2秒期限による取りこぼしも0。
- **期限の余裕は大きい。** 初片到着からアプリ到達まで平均36 ms、最大115 msで、0.2秒期限に対して余裕がある。ただしこれは受信側だけの時間で、encode・実ネットワーク転送・capture→初片は含まない。
- **backpressureは機能している。** `held_for_buffer`が1,409回あり、channel buffer（peak 125,757 B）を超えないよう送出を待っている。

## 3. 重要な限界（この結果で40 Mbpsを語れない理由）

- **payloadが小さすぎる。** 2,311 fragment × 16,384 B = 37.86 MBが上限で、296 frameで割ると約128 KB/frame。前段のオフライン実測は約1,012 KB/frameだったので、**約1/8**。コーンが写らない低詳細な画面ではPNGが小さくなるためで、40.49 Mbpsの条件を試したことにならない。
- **実効4.46 Hzで、要求5 Hzに届いていない。** 送信offerは303/66.7秒 = 4.54 Hz。capture時刻間隔・odom対応のどれが効いたかは未測定。7 frameはcaptureから0.2秒を超えて期限切れになった。
- **`sequence_gaps=1,695`は欠損ではない。** `capture_sequence`はカメラのフレーム番号で、送信は5 Hzへ間引いているため、飛びは正常。packet lossの指標に使わない。監査JSONでも`receiver_capture_sequence_jumps_are_not_packet_loss=true`として区別した。
- **`both_closed=false`。** 受信側はclose前にコピーされたため、最後の周期flush（2秒間隔）時点の値。送信296・受信296・publish296が一致しているので、flush時点までの取りこぼしはない。
- **受信側`replaced=4`の機序は未確定。** 完了数には影響していない。unordered fragmentの到着順に起因する可能性があるが、断定しない。
- 通常映像のfps・停止、片方向遅延、測距精度、ROS/FFBは測っていない。`usable_for_ffb=false`を維持する。

## 4. 判断

**transport実装は成立。帯域条件は未達（未検証）。** 今回の結果は「経路と再構成が壊れていない」ことの確認であり、「PNG 5 Hzを通常映像と共存できる」ことの証明ではない。

40 Mbps級の判定には、**オフラインで約1 MB/frameだった代表シーン**（コーンが見え、テクスチャがある構図）で同じ30秒試験をやり直す必要がある。そのとき`payload_bytes_upper_bound`が36〜38 MB（約40 Mbps）に近づいていることを確認してから、frame到達率を読む。

## 5. 証拠

- [監査JSON](transport_audit_r01/audit.json)、原JSON 2点は `recordings/2026-11-18/png_link_probe_intake_r01/`。
- archive SHA：sender `b48e1a95ee12423c566c0052c690329bbc51a534bc1613f628f5def9950f3258`、receiver `e8d5dcbd2579761b71389eb73c85041f1bdc7098fa3f3717ba19187cd42d9553`。
- [検証JSON](verification_r03/audit.json)：**372 passed / 0 failed / 0 skipped（16.74秒）**。監査スクリプト修正後の正式版。r01/r02は履歴として保持。
