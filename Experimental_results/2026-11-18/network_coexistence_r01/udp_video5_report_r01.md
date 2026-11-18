# 通常映像あり5 Mbps・10秒：比較結果（11/18）

> **11/18訂正：この試験時に映像パイプライン（matsunucの送信・GPUPCの受信UI）は起動していなかった。** 実際の条件は映像なしであり、下表の「映像あり」列と目視回答は有効でない。raw archiveと`audit.json`は変更せず、[訂正記録](udp_video5_audit_r01/condition_correction.json)を追加した。実際の映像あり25 Mbpsは[別報告](udp_video25_report_r01.md)を参照。

**5 MbpsのUDP転送は通常映像ありでも成立し、送受信payload一致・欠損0。操作者からも映像の停止/大きな乱れなしとの回答を得た。** この1回の低負荷試験の結果であり、最大容量・定量fps/遅延・PNG/SCTP実到着・FFBの合格ではない。次は [通常映像を維持した25 Mbps・10秒](udp_video25_r01.md)。既存probe.py/collect.pyは不変であり、今回の試験のための新コード反映・再installは不要。

## 前回との比較

| 項目 | 映像なし5 Mbps | 通常映像あり5 Mbps |
|---|---:|---:|
| 送信payload | 6,249,600 bytes | 6,249,600 bytes |
| 送信時間 | 10.000106秒 | 10.000077秒 |
| 送信実測rate | 4.999627 Mbps | 4.999642 Mbps |
| 受信payload（区間合計） | 6,249,600 bytes | 6,249,600 bytes |
| 受信区間経過 | 10.042234秒 | 10.043863秒 |
| 受信再集計rate | 4.978653 Mbps | 4.977846 Mbps |
| iperf報告packet/lost | 5,208 / 0（0%） | 5,208 / 0（0%） |
| 最後に報告されたjitter | 0.296691 ms | 1.162754 ms |
| 映像の停止/大きな乱れ | 条件外 | なし（操作者目視申告） |

受信率差は約−0.000807 Mbps（約−0.0162%）で、受信量そのものは同じ。jitter最終値は約+0.866 msだが、各1回の最終値であり平均/最大でも反復試験でもない。映像による悪化の因果や安定性を断定せず、参考値として保持する。送受時間差を一方向遅延に変換せず、両PC時計の対応も用いていない。

両試験は異なるiperf cookieで、前回と同じ結果ファイルの再提出ではない。今回のclient/serverの実IP/UDP port/実設定/目標rate/source SHAが一致し、client埋込みserver JSONと別提出server JSONも完全一致。両側returncode 0、stderr空。受信側end JSONのbytes/rate=0は前回と同じ表示上の不整合であり、原値を保全したまま独立した受信区間を再集計した。[前回の理由と公式source参照](udp_idle5_report_r01.md)。

## 証拠

- [今回の監査JSON](udp_video5_audit_r01/audit.json)。原archive・JSON4点×2は `recordings/2026-11-18/network_udp_video5_intake_r01/`。
- [操作者の観察記録](udp_video5_audit_r01/observation.json)。回答は「停止・大きな乱れはなかった」。映像を独立収録・解析した証拠や定量fps測定ではない。
- [前回の監査JSON](udp_idle5_audit_r02/audit.json)。同じ受信区間集計方式で比較。
- 今回archive SHA：client `eb157c495dacab90872c005ce04e1a749e749b7c0645c0ac77e69edf293c7df5`、server `ec1838b96baefe785cfc1adfbe42ae1a3a581e1ee0f579d3208e343d7e1558e7`。

## 次段階と採用範囲

[正式検証JSON](udp_video5_verification_r01/audit.json)、[テスト出力](udp_video5_verification_r01/tests.txt)：**353 passed / 0 failed / 0 skipped、15.73秒**。既存検証器・テストは変更せず、新入力の原archive/JSON/hash・全集計を再確認。旧source SHAも不変。画像推論や実通信を再実行した検証ではない。

目的は通常映像との共存なので、映像を維持したまま25 Mbpsへ1段階だけ増量する。25 Mbpsの映像なし条件は、異常時に原因を切り分ける必要が生じた場合に追加する。全rateで映像on/offを一括実施せず、異常があれば中止して増量しない。

必要量約40.49 Mbps（PNG5 Hz）/80.98 Mbps（10 Hz）に通常映像/実overheadが別に必要であり、5 Mbps成功だけでPNG liveを採用しない。通常映像の実送信rate、queue/IPC、NUC encode、SCTP/DTLS、露光/元鮮度、距離精度、接地/車体基準、制御/FFBの認定は未完了。こちらで実通信・listener・install・Git・実機操作は行っていない。
