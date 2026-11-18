# 25 Mbps・通常映像あり：比較結果（11/18）

**25 Mbpsの単一UDP streamは、実際に映像を流した状態でも10秒間継続し、送信側は要求どおり24.998 Mbps、受信区間集計は24.880 Mbpsだった。欠損は14 packets（0.0538%）で、6〜7秒区間に集中し、他区間は0。操作者は映像の停止・大きな乱れなしと回答した。** ただし送受信payloadは一致せず、1回ずつの結果であり、最大容量・定量fps/遅延・PNG/SCTP/FFBの合格ではない。

## 1. 前提の訂正（重要）

これ以前の「通常映像あり5 Mbps」と「25 Mbps r01」は、**映像パイプラインを起動せずに実施されていた**（操作者申告）。matsunucの`webrtc_stream.py`もGPUPCの`webrtc_receive_ui.py`も動作しておらず、WebRTC映像トラフィックは存在しない。したがって次のように扱う。

| 提出 | 申告condition | 実際 | 扱い |
|---|---|---|---|
| 5 Mbps video5 | normal-video | 映像なし | 映像なしの反復試験へ訂正（[訂正記録](udp_video5_audit_r01/condition_correction.json)） |
| 25 Mbps r01 | normal-video | 映像なし | 25 Mbpsの映像なし基準値へ訂正（[訂正記録](udp_video25_audit_r01/condition_correction.json)） |
| 25 Mbps r02 | normal-video | 映像あり | 本報告の主結果（[観察記録](udp_video25_audit_r02/observation.json)） |

raw archiveと`audit.json`は書き換えていない。申告値は`condition_operator_reported_NOT_verified`として原値保持し、訂正は別ファイルに残した。

## 2. 定量結果

| 項目 | 5 Mbps 映像なし | 5 Mbps（実質映像なし） | 25 Mbps 映像なし（r01） | 25 Mbps 映像あり（r02） |
|---|---:|---:|---:|---:|
| 送信payload | 6,249,600 B | 6,249,600 B | 31,248,000 B | 31,248,000 B |
| 送信時間 | 10.000106 s | 10.000077 s | 10.000106 s | 10.000100 s |
| 送信実測rate | 4.999627 Mbps | 4.999642 Mbps | 24.998135 Mbps | **24.998150 Mbps** |
| 受信payload（区間合計） | 6,249,600 B | 6,249,600 B | 31,204,800 B | **31,231,200 B** |
| 受信区間経過 | 10.042234 s | 10.043863 s | 10.043575 s | 10.042100 s |
| 受信再集計rate | 4.978653 Mbps | 4.977846 Mbps | 24.855532 Mbps | **24.880214 Mbps** |
| 欠損 | 0（0%） | 0（0%） | 36（0.1382%） | **14（0.0538%）** |
| payload一致 | 一致 | 一致 | 不一致 | **不一致** |
| 最後に報告されたjitter | 0.296691 ms | 1.162754 ms | 0.093170 ms | 0.246536 ms |
| 映像の停止・大きな乱れ | 条件外 | 未観察（対象なし） | 未観察（対象なし） | **なし（操作者目視）** |

### 欠損の出方（受信区間）

| 区間 | 25 Mbps 映像なし r01 | 25 Mbps 映像あり r02 |
|---|---|---|
| 0〜1 s | 16 / 2,488（0.643%） | 0 / 2,493 |
| 1〜2 s | 20 / 2,607（0.767%） | 0 / 2,605 |
| 2〜6 s | 0 | 0 |
| 6〜7 s | 0 | **14 / 2,609（0.537%）** |
| 7〜10 s | 0 | 0 |

## 3. 解釈

- 両runとも要求rateに到達し、転送は10秒間完了した。TCP接続・port 5208・cookie・実peerは両者で一致し、clientに埋め込まれたserver出力と別提出のserver JSONも完全一致した。
- 欠損は**散発的**で、負荷量に単調には対応しない。映像ありのr02の方が欠損は少なかった。したがって**この1回の比較では「映像追加による悪化」を示す証拠は得られていない**。
- 一方、r01だけから立てた「欠損は開始1〜2秒の過渡」という仮説は、r02の6〜7秒での14 packet欠損により**支持されない**。開始過渡に限定せず、散発的な欠落として扱う。
- 受信率は送信率より約0.12 Mbps（約0.47%）低い。これは10.042秒の受信区間に対する区間合計であり、片方向遅延や映像遅延へ読み替えない。PC間の時計対応も使っていない。
- 目視は操作者申告であり、独立録画・fps測定・capture-to-display遅延の測定ではない。25 Mbps成功をもってPNG 5 Hzの必要量（約40.49 Mbps、通常映像と実overheadは別）を満たしたとは言わない。

## 4. 監査ツールの版更新

今回の2runは、iperf 3.9が受信側の**per-stream** `lost_percent`を0と出力する事象を含む（`end.sum`は0.0538/0.1382で区間合計と一致）。iperf 3.9の`src/iperf_api.c` `iperf_print_summary`では、受信側の`sender_packet_count = sp->peer_packet_count`であり、peerのpacket数を受領していない場合に`packets`は受信側countへfallbackする一方、`lost_percent`は0.0のままになる。

- v1（`audit_udp.py`）は変更せず、過去の監査を再現可能なまま保持。
- v2（`audit_udp_v2.py`）は受信per-streamの`lost_percent`が0かつ`lost_packets>0`のときだけ原値を保持してフラグを立て、欠損数は区間合計と`end.sum`から検証する。`end.sum`の整合性検査は緩めていない。
- 新テスト`tests/test_network_udp_audit_v2.py`で、v2が受理する条件と、`end.sum`不一致・非0の誤値を拒否することを確認。v1が同じ入力で拒否することも確認。

## 5. 証拠

- 監査：[r02](udp_video25_audit_r02/audit.json)、[r01](udp_video25_audit_r01/audit.json)。いずれも`state=paired_trial_verified_NOT_capacity_or_video_acceptance`、`receiver_stream_loss_percent_unavailable=true`。
- 検証：[r02](udp_video25_verification_r02/audit.json) **359 passed / 0 failed / 0 skipped、16.13秒**、[r01](udp_video25_verification_r01/audit.json) **359 passed / 16.11秒**。raw archive/JSON/hashと全集計を再現。
- 原archive・JSON：`recordings/2026-11-18/network_udp_video25_intake_r01/`、`recordings/2026-11-18/network_udp_video25_intake_r02/`。
- archive SHA：r01 client `b73407e180a464fed92a8cb03334a43c802498187e6d6bde2a20670956796313`、server `88c746c670495f07b890bc9c919beff8325a92167f0727cdf7e5e9af06155695`。r02 client `a0b1856bc3e8d6a96ba0feaf327369f5aafed05e1e21d437c41142711958c4b7`、server `330c4d12f2cf4b6da3c4b4a7407a59501ab9868c596153caac4de26f7f43653a`。

## 6. 次段階

次は**50 Mbps・通常映像あり・10秒**を1段階だけ試す。50 Mbpsはこのprobeの上限であり、約40.49 Mbps（PNG 5 Hz）に対する余裕の有無を直接は示さない。映像の停止・大きな乱れが出たらCtrl+Cで中止し、増量しない。必要なら同rateの映像なしで切り分ける。

未取得：5 Mbpsの実際の映像あり条件。今回の25 Mbps比較で中心的な問いには答えたため、必要になった時点で追加する。実映像bitrate・fps・片方向遅延、SCTP/DTLS、NUC encode、露光/元鮮度、距離精度、接地/車体基準、制御/FFBは未測定・未認定。
