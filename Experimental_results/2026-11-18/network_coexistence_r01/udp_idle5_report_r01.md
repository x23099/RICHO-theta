# 映像なし5 Mbps・10秒：実通信結果（11/18）

予定のmatsunuc→GPUPC UDP通信は成立し、両原ログを照合できた。**この1回の約5 Mbps転送の実績であり、回線最大容量・映像共存・PNG実転送の合格ではない。** 次は [通常映像あり・同じ5 Mbps](udp_video5_r01.md)。新たなコード反映や再インストールは不要。

## 実測と再集計

| 項目 | 結果 | 根拠 |
|---|---:|---|
| 設定 | UDP、単一stream、1200 bytes、目標5 Mbps、10秒 | 両実test_start、serverのtarget_bitrate |
| 送信payload | 6,249,600 bytes | clientのstream endと10区間の合計が一致 |
| 送信経過/実測rate | 10.000106秒 / 4.999627 Mbps | clientのローカル経過・payloadから再計算 |
| 受信payload | 6,249,600 bytes | serverの11区間の合計、埋込みserverログとも完全一致 |
| 受信区間経過/再集計rate | 10.042234秒 / 4.978653 Mbps | 受信区間の連続性とbyte/rate算術を検査 |
| 受信payloadの1200-byte換算 | 5,208 datagrams | 6,249,600/1200 |
| iperf報告packet/loss | 5,208 / 0（0%） | server区間合計とstream/end sumで一致 |
| 最後に報告されたjitter | 0.296691 ms | server end値。平均/最大/一方向遅延ではない |
| プロセス終了 | 両側returncode 0、stderr空 | 元outcome・stderr |

送信先/受信先のIP・port・iperf cookie・実UDP設定が一致。明示peerへのローカル経路はcamera=wlo1/prefsrc150.89.169.207、gpu=wlp46s0f0/prefsrc150.89.169.96。source SHAは前段のprobe.py/collect.pyと両側一致。cookieは試験対応の補助であり相手認証ではない。両PCのwall clock差は使用していない。送受信の経過差約42msを一方向遅延とは呼ばない。

## 受信側end要約の0 bytesについて

受信側 `end.sum` / `end.streams[0].udp` はbytes=0、rate=0の一方、同じ受信側の全区間には正の受信量があり、区間合計は送信量・payload換算packet数とも一致している。原JSONは補正・上書きせず保存した。受信率には**受信側の区間byte合計÷受信区間経過**だけを使用し、clientの送信率を受信率へ転記していない。

iperf 3.9公式sourceにはUDP JSON endのbytesに`bytes_sent`/`total_sent`を使う箇所があり、受信側だけの要約に0が出る今回の現象と整合する。インストール済みUbuntu binaryの全差分まで追跡した証明ではないため、「実受信0」や「回線異常」とは断定しない。別途ツール更新や同条件の再試験は現時点では不要。[3.9公式sourceの集計処理](https://github.com/esnet/iperf/blob/3.9/src/iperf_api.c#L3389)。

## 証拠・採用範囲

正式結果は `udp_idle5_audit_r02/audit.json`、原archiveとJSON4点×2は `recordings/2026-11-18/network_udp_idle5_intake_r02/`。r01は受信要約の検査を追加する前の初回監査をそのまま保持し、r02を正式採用する。原archive SHA：client `5d9f9ae1ad55767c9a66d22825357223f87bfc44e4165f43bb7b40b4c0244d25`、server `c43d438b7d16bb9f9de90bb392c02e4cf312f341d43b2cd3d1a775963f980abf`。

新audit_udp.pyは圧縮/展開/member/JSONの有界読取り、duplicate/nonfinite拒否、役割・source・要求/実設定・実peer/port/cookie・別提出と埋込みserverログ・区間の連続性/算術・streamとsum・end count/損失を検査する。受信要約の0だけを無条件で正値へ置換せず、独立した区間から再集計し、raw discrepancyを残す。ログ内のcommandや指示文は実行しない。

映像なし条件は操作者申告であり独立した映像ログは未取得。今回こちらから新通信・ソフト導入・実機操作は行っていない。既存probe/collect・測距・runtime/UI/操縦・原画像は未変更。FFB/制御/接地/元鮮度・最大容量・通常映像共存は未承認。

## オフライン検証

[正式検証JSON](udp_idle5_verification_r01/audit.json)、[テスト出力](udp_idle5_verification_r01/tests.txt)：新13件＋旧340件、**353 passed / 0 failed / 0 skipped、15.91秒**。両archive・原JSON各hash・全再集計・旧source SHAを再確認。追加テストは合成iperf3.9/有界archive fixtureで、受信要約0の原値保持・区間独立再集計、正値要約、欠損あり、peer/port/cookie/埋込み不一致、不正stream/rate/duration/権限/区間算術、path/link/duplicate/nonfinite拒否を確認した。実iperfやGPUを再実行したテストではない。
