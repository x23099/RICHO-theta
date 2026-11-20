# VP8_INTRA frame/motion packet 実回線 transport 試験 r01：結果（11/18）

> **11/20訂正：本試験で実際に流れたのはPNGではなく VP8_INTRA だった。** 実channelの`encode_packet()`（`src/driver_frame_packet.py:107`）がlibvpxでVP8を生成し、ヘッダも`codec='VP8_INTRA'`（同`:126`）。PNG側（`driver_lossless_frame_packet.py`等）はruntime/channelからimportされていない。ディレクトリ名`png_link_probe_r01`は経緯によるもので、**PNGの実transportは未実施**。raw JSONと監査JSONは変更していない。

**実SCTP/DTLS DataChannelで、送信側がchannelへ渡し切った296 frameが、受信側で296 frameすべて再構成・期限判定を通ってアプリまで届いた（frame_completion_ratio = frame_publication_ratio = 1.0）。** これはVP8_INTRA packet経路の結果であり、payloadは約4.54 Mbps。PNG（約40.49 Mbps）の検証ではない。

## 1. 定量結果

| 項目 | 値 |
|---|---:|
| 試験時間（sender / receiver） | 66.737 s / 82.031 s |
| 要求rate | 5 Hz |
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
| frame_completion_ratio / publication_ratio | **1.000 / 1.000** |
| 受信側で完了前に置換されたpacket | 4 |
| 期限切れframe（受信） | 0 |
| duplicate / invalid / conflict | 0 / 0 / 0 |
| 受信側latency（初片到着→publish） min / mean / max | 2.62 / 36.24 / 114.66 ms |

送信側の`scheduler`：`offered=303`、`expired=7`、`pending_replaced=0`、`held_for_buffer=1,409`、`packets_handed_off=296`、`peak_retained_bytes=125,757`。`held_for_buffer`はchannel bufferが閾値を超えてfragment送出を待った回数で、backpressureが働いたことを示す。

## 2. 何が分かったか

- **VP8_INTRA packet経路はframe単位で欠損がない。** 296渡して296完成・296到達。fragmentの破損・重複・競合も0。受信側0.2秒期限による取りこぼしも0。
- **期限の余裕は大きい。** 初片到着からアプリ到達まで平均36 ms、最大115 ms。ただし受信側だけの時間で、encode・実ネットワーク転送・capture→初片は含まない。
- **backpressureは機能している。** `held_for_buffer`が1,409回あり、channel buffer（peak 125,757 B）を超えないよう送出を待っている。
- この経路は**すでにruntimeへ配線済み**（`--frame-motion-packets`）で、今回の測定は実装済み経路の実回線確認にあたる。

## 3. 限界

- **PNGではない。** 7.81 fragment/frame × 16,384 B ≈ 128 KB/frameで、VP8 intraの実測（約94〜101 KB）と同桁。PNGの約1 MB/frameとは異なる。
- **帯域は目標の1/9。** 40.49 Mbps（PNG 1 MB × 5 Hz）に対し、今回は上限見積りでも4.54 Mbps。**30秒で40.49 Mbpsを流すには約152 MB必要**で、今回は66.7秒で37.86 MB。
- **実効4.46 Hzで、要求5 Hzに届いていない。** offerは303/66.7 = 4.54 Hz。capture時刻間隔かodom対応かは未測定。7 frameはcaptureから0.2秒を超えて期限切れ。
- **`sequence_gaps=1,695`は欠損ではない。** `capture_sequence`はカメラのフレーム番号で、5 Hzへ間引いているため正常。
- **`both_closed=false`。** 受信側はclose前にコピーされたため、最後の周期flush（2秒間隔）時点の値。送受296一致で、flush時点までの取りこぼしはない。
- **`replaced=4`の機序は未確定。** 完了数には影響していない。

## 4. 判断

**VP8_INTRA packetのtransportは成立。PNGは未検証。**

PNG採用の判断には、lossless sender/fragmentsを実transportへ配線した別試験が必要。一方、VP8経路は距離入力のcodec候補として現実的だが、保存画像比較では**保留gateが4枚中2枚で反転**している（[11/20のオフライン評価](../../2026-11-20/vp8_packet_assessment_r01/README.md)）。transportの成立と、距離判断への採用可否は別問題として扱う。

## 5. 証拠

- [監査JSON](transport_audit_r01/audit.json)、原JSON 2点は `recordings/2026-11-18/png_link_probe_intake_r01/`。
- archive SHA：sender `b48e1a95ee12423c566c0052c690329bbc51a534bc1613f628f5def9950f3258`、receiver `e8d5dcbd2579761b71389eb73c85041f1bdc7098fa3f3717ba19187cd42d9553`。
- [検証JSON](verification_r03/audit.json)：**372 passed / 0 failed / 0 skipped（16.74秒）**。
