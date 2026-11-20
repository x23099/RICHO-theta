# 2026-11-18 日報：実回線の映像共存を5→50 Mbpsで確認、VP8_INTRA packet実経路のtransport probeを実装・初回測定

> **11/20訂正：** 本文の一部で「PNG実経路」としていた箇所は誤り。実channelのcodecは**VP8_INTRA**で、PNGは未接続・未検証。また「36〜38 MB（約40 Mbps）」は計算誤りで、40.49 Mbpsを30秒流すには**約152 MB**必要。raw data・監査JSONは変更していない。詳細は[11/20のVP8評価](../Experimental_results/2026-11-20/vp8_packet_assessment_r01/README.md)。

## 1. 到達点

1. **通常映像とUDP負荷の共存を、実機のWi-Fi経路で5→25→50 Mbpsまで段階的に測定した。** 5 Mbpsは欠損0、25 Mbpsは0.054%、50 Mbpsは0.22〜0.29%。50 Mbps（`probe.py`の上限）で欠損が増え、実用上の余裕は25 Mbps前後という目安を得た。
2. **条件の誤りを検出して記録を訂正した。** 「通常映像あり」として提出された5 Mbpsと25 Mbps r01は、実際には映像送信・受信UIを起動していなかった。raw archiveと監査JSONは書き換えず、訂正記録を別途保存した。
3. **frame/motion packetの実SCTP/DTLS経路用transport probeを実装した。** 既定off。初回測定では296 frameを渡して296 frameが完成・到達（欠損0）。ただし実channelのcodecは**VP8_INTRA**で、payloadは上限4.54 Mbps。**PNG（約40.49 Mbps）は未接続・未検証**。**VP8のtransportは成立、PNGの帯域条件は未検証**。

本日の主眼は距離推定そのものではなく、**測距入力をFFBの勾配へ接続する前提となる「映像と追加データを同じ回線で運べるか」の足切り**である。最終目標（操舵入力に対する衝突リスク勾配の抵抗型FFB）と現在地は [RESEARCH_GOAL.md](../RESEARCH_GOAL.md) のとおりで、距離・物理・接地・元鮮度・制御/FFBの認定フラグはすべてfalseのまま据え置いた。

## 2. 実施条件・Git状態

- 作業枠はユーザー指定の**2026-11-18扱い**。OS/Git時刻と過去の実験日時は変更していない。
- 当日commit：`33feb17`（1118v1）〜`138fac5`（1118v13）、および`0635bdb`（1118日報、実体はprobe結果の保存）。開始時点のHEADは`c05ff48`（11/17日報）。
- 日報作成時点の未commit差分：本日報、`Experimental_results/2026-11-18/report_assets/`。commit/pushはユーザー側で行う。
- 実機操作はすべてユーザー側。こちらでは実通信・iperf3導入・Git操作・カメラ/ROS/G923起動を行っていない。解析PCでの読み取りと局所ファイル作成のみ。

## 3. 実施内容

### 3.1 画像・packet系（前段）

- 保存画像のPNG/CUDA比較、packet再圧縮のGPU比較（r01〜r03）、frame packet runtime/channel/flowのoffline実装、sender負荷モデル。
- 詳細は [HANDOFF.md](../HANDOFF.md) の11/18各節と各`Experimental_results/2026-11-18/*/README.md`。

### 3.2 回線共存（network_coexistence_r01）

- 両PCのIPv4/interface/route/iperf3有無を`collect.py`で採取し、カメラPC→GPUPC方向の単一UDP streamを5→25→50 Mbps、各10秒で測定。`probe.py`は実行直前にown IPとpeer routeを検査し、不一致なら通信せず停止する。
- iperf 3.9の受信側per-stream `lost_percent`が0になる事象（`peer_packet_count`未受領時）を含むため、v1（`audit_udp.py`）を変更せず[v2](../Experimental_results/2026-11-18/network_coexistence_r01/audit_udp_v2.py)を追加した。`end.sum`の整合性検査は緩めていない。

### 3.3 frame/motion packet transport probe（png_link_probe_r01）

- [driver_frame_packet_probe.py](../src/driver_frame_packet_probe.py)：既存channelのcounterを読むだけのprobe。2秒ごとにatomic JSONを書き、画像は保持しない。推論・ROS・FFB・表示変更なし。
- `webrtc_stream.py` / `webrtc_receive_ui.py` / `start_theta_receive_rtc.sh` に既定offのoptionを追加。ディレクトリ未指定なら従来経路と同一。
- [手順](../Experimental_results/2026-11-18/png_link_probe_r01/README.md)、[監査](../Experimental_results/2026-11-18/png_link_probe_r01/audit_probe.py)。

## 4. 定量結果

### 4.1 回線共存（UDP 10秒、受信区間集計）

| rate | 実際の条件 | 送信 Mbps | 受信 Mbps | 欠損 | 欠損率 |
|---|---|---:|---:|---:|---:|
| 5 Mbps | 映像なし | 4.999627 | 4.978653 | 0 / 5,208 | 0% |
| 5 Mbps | 映像なし（申告は映像あり） | 4.999642 | 4.977846 | 0 / 5,208 | 0% |
| 25 Mbps | 映像なし（申告は映像あり） | 24.998135 | 24.855532 | 36 / 26,040 | 0.1382% |
| 25 Mbps | 映像あり | 24.998150 | 24.880214 | 14 / 26,040 | 0.0538% |
| 50 Mbps | 映像あり r01 | 49.995470 | 49.673069 | 114 / 52,079 | 0.2189% |
| 50 Mbps | 映像あり r02 | 49.995415 | 49.617055 | 151 / 52,079 | 0.2899% |

- 25 Mbps映像ありの欠損は6〜7秒に集中、50 Mbps r01は6〜7秒、r02は3〜4秒。**「約6秒周期」という仮説は2runで位置が一致せず棄却。**
- r02の3〜4秒は送信側自身が2〜3秒44.6 Mbps、3〜4秒55.4 Mbpsとpaceを乱しており、詰め戻しによる受信buffer超過の可能性が高い。CPU/割り込み未測定のため断定しない。
- 図表：[network_coexistence_rates.csv](../Experimental_results/2026-11-18/report_assets/network_coexistence_rates.csv) / [.png](../Experimental_results/2026-11-18/report_assets/network_coexistence_rates.png)。

### 4.2 VP8_INTRA実経路 transport（5 Hz要求、約66秒）

| 項目 | 値 |
|---|---:|
| 送信offer / 期限切れ / channelへ渡したframe | 303 / 7 / **296** |
| fragment生成・送出 | 2,311 |
| fragment/frame | 7.81 |
| payload上限（fragments × 16,384 B） | 37,863,424 B（**4.539 Mbps**、66.7秒合計） |
| 送信実効rate / 受信publish rate | 4.435 / 4.464 Hz |
| 受信で完成 / アプリ到達 | **296 / 296** |
| frame_completion_ratio / publication_ratio | **1.000 / 1.000** |
| 受信側latency（初片→publish） 平均 / 最大 | 36.24 / 114.66 ms |
| 期限切れ・重複・破損・競合 | 0 |
| 送信backpressure（held_for_buffer） | 1,409回、peak保持125,757 B |

- `sequence_gaps=1,695`は`capture_sequence`の間引きによる正常値で、packet lossではない。
- 図表：[png_transport_probe_r01.csv](../Experimental_results/2026-11-18/report_assets/png_transport_probe_r01.csv) / [.png](../Experimental_results/2026-11-18/report_assets/png_transport_probe_r01.png)。

### 4.3 前段の参照値（本日再測定ではない）

| 項目 | 値 | 出典 |
|---|---:|---|
| PNG packet（fragment込み）中央値 | 1,012,201.5 B | lossless_frame_packet_r01 |
| VP8 packet | 約101,927 B | 11/17 packet試作 |
| PNG 5 Hz / 10 Hz の単純データ量 | 40.49 / 80.98 Mbps | 同上（実overhead別） |
| 同一画像の元 vs packet再圧縮の距離差 | 1.1892693049 → 1.1590857906 m（−0.0301835143 m） | GPU再圧縮r02 |
| packet encode 中央値 / encode+receiver | 18.947 ms / 35.021 ms（最大41.900） | GPU再圧縮r02 |

## 5. 検証

| 段階 | 成功 | 失敗/skip | 時間 |
|---|---:|---:|---:|
| lossless packet GPU準備 | 297 | 0 / 0 | — |
| GPU提出監査 | 308 | 0 / 0 | 15.60 s |
| 回線採取手順 | 323 | 0 / 0 | 15.68 s |
| 有限UDP試験準備 | 340 | 0 / 0 | 15.92 s |
| 実UDP 5 Mbps（映像なし／実質なし） | 353 | 0 / 0 | 15.73 s |
| 25/50 Mbps（audit v2） | 359 | 0 / 0 | 16.11〜16.30 s |
| frame/motion packet transport probe | 372 | 0 / 0 | 16.74 s |

- 同じ入力・環境での成功結果は再利用し、追加変更があった段階だけ再実行した。
- **副作用：** `verify_udp*.py`は11/18 pre-probeの`webrtc_stream.py`/`webrtc_receive_ui.py` SHAをfrozenとして検査するため、probe実装後のtreeでは`previous frozen source differs`で停止する。保存済みUDP監査・検証JSONは不変で、再実行には当時のcommitが必要。この旨を[回線README](../Experimental_results/2026-11-18/network_coexistence_r01/README.md)とHANDOFFに記載した。

## 6. 判明した課題

1. **条件の取り違え。** 「映像不要」という案内が`inspect`の範囲であることを明示できず、5 Mbpsと25 Mbps r01を映像なしで実施した。rawは保持し、訂正記録と手順の必須確認（映像ウィンドウの更新確認）を追加した。
2. **probeが測ったのはVP8_INTRAだった。** 実channelの`encode_packet()`がVP8を生成するためで、約128 KB/frame（上限見積り）はVP8の実測（94〜101 KB）と同桁。**PNG経路はruntime/channel未接続で、実transportは未実施**。40.49 Mbpsの判断にはPNG sender/fragmentsの実配線が必要。
3. **実効4.46 Hz。** 5 Hz要求に対して約11%不足。capture間隔かodom対応かは未測定。
4. **50 Mbpsの欠損機序。** 送信側paceの乱れと受信buffer超過の可能性があるが、CPU・割り込み・Wi-Fi状態を記録していない。
5. **未測定・未認定。** 通常映像の実bitrate/fps、片方向遅延、SCTP/DTLS実到着（PNG）、元露光の鮮度、測距の絶対精度、接地/車体基準、制御/FFB。`usable_for_ffb=false`を維持。

## 7. 次回作業

1. **VP8経路で距離判断の安定性を確認**（11/20にオフライン評価を開始）。保存画像4枚では保留gateが2枚で反転したため、ROIを検証した画像で反転率と距離差を測る。PNGの実transport配線はその後、VP8で不足する場合に限り着手する。なお40.49 Mbpsを30秒流すには約152 MB必要（今回の実測は66.7秒で37.86 MB）。
2. その結果で分岐する。
   - 到達率が高い → 距離推論を載せ、勾配FFBの入力接続設計へ。
   - completedは高いがpublishedが低い → 期限・queue設計（ROI限定・期限短縮）を検討。
   - completedが低い → 帯域を下げる、ROIのみ可逆、別リンクを検討。
3. 余力があれば5 Mbpsの実際の映像あり条件を取得（優先度は低い）。
4. 今月中に勾配FFBへ本格シフトするため、PNGに固執せず「ROIだけ可逆」も並行して設計候補に置く。

## 8. 成果物

- 代表資料：[report_assets](../Experimental_results/2026-11-18/report_assets/README.md)（CSV2点、画像2点、生成script）。
- 回線：[比較報告（25 Mbps）](../Experimental_results/2026-11-18/network_coexistence_r01/udp_video25_report_r01.md)、[50 Mbps r01](../Experimental_results/2026-11-18/network_coexistence_r01/udp_video50_report_r01.md)、[50 Mbps r02](../Experimental_results/2026-11-18/network_coexistence_r01/udp_video50_report_r02.md)、[手順](../Experimental_results/2026-11-18/network_coexistence_r01/README.md)。
- frame/motion packet transport（VP8_INTRA）：[結果報告](../Experimental_results/2026-11-18/png_link_probe_r01/transport_report_r01.md)、[監査JSON](../Experimental_results/2026-11-18/png_link_probe_r01/transport_audit_r01/audit.json)、[検証JSON](../Experimental_results/2026-11-18/png_link_probe_r01/verification_r03/audit.json)。
- VP8のオフライン距離評価：[11/20評価](../Experimental_results/2026-11-20/vp8_packet_assessment_r01/README.md)。
- 原データ：`recordings/2026-11-18/`（Git管理外）。UDP各intake、frame packet probe intake。
