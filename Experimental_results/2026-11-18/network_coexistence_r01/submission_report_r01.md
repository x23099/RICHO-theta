# 両PCネットワーク採取結果（11/18）

両提出は形式正常。archiveは有界XZ/TARとして読み、report.jsonのschema・role・false権限・IPv4/interface/default routeを検査した。指示文として実行した内容はない。原archive/原JSONは `recordings/2026-11-18/network_inventory_intake_r01/` に保存し、Gitには含めない。[監査JSON](inventory_audit_r01/audit.json)。

| 申告role | upかつdefaultのinterface | IPv4 | subnet | iperf3 |
|---|---|---|---|---|
| camera | wlo1 | 150.89.169.207 | 150.89.169.0/24 | 未導入 |
| gpu | wlp46s0f0 | 150.89.169.96 | 150.89.169.0/24 | 未導入 |

双方gatewayは150.89.169.1。GPU側Docker bridge等はdownであり、今回のdefault候補に選択しない。無線系interface名だが、無線の規格・実リンク速度・空き容量・同じAPかどうかは未採取。peer明示routeと実疎通はまだ未確認であり、「同subnetだから通信可能・十分な帯域がある」とは断定しない。

archive SHA256：camera `22c11d337618a40f57c36fe68369c6033adf71793df80cb8f72c0a27dc7a28d6`、gpu `0ed56a020cc068c612efe7d0b51c45355e5a2f2bfed809079d93c677e494a74c`。役割は操作者申告で機器認証ではない。

ユーザーが追加質問で両PCへのiperf3導入を承認。次は [映像なし5 Mbps・10秒手順](udp_trial_r01.md)。受動採取は導入不要の選択肢として維持するが、導入承認を受けたため、先に小さい有限負荷でpeer疎通と受信量を確認する。増量・映像あり比較・PNG live導入はまだ行わない。

新probe.pyは既存collect.pyのローカル情報読取りだけを再利用し、own IP/interface・peer routeを起動前照合。1回の明示実行だけで、server45秒/client25秒のprocess timeout、single stream10秒・5/25/50 Mbpsの限定選択（最初は5）、port5208・exact bind・one-off・stdout/stderr原ログ・失敗もarchive化・既存出力拒否。version/help互換を確認し、自動install/firewall/daemon/実機操作を行わない。serverのpeer認証や他client負荷制限ではなく、実接続peerは戻りログで監査する。

初回archive検査でPython標準TARのfractional mtime PAXまで拒否したため、安全な時刻keyだけを許可して修正した。path/link/extra/duplicate/size/nonfiniteの制限は維持し、再採取は不要。追加17テストは合成archive/模擬subprocessのみ。実IPやiperfに対する能動実行は行っていない。

## 検証

[正式検証JSON](trial_verification_r01/audit.json)、[テスト出力](trial_verification_r01/tests.txt)：**340 passed / 0 failed / 0 skipped、15.92秒**。旧323件を含み、旧collect・検証器・既存測距・codec/runtime/UI/操縦sourceのSHAを前段manifestと照合して不変。提出archiveと原JSONのhash、選択interface/IP/subnetも原記録から再確認した。実iperf3を使う試験はまだ未実施であり、性能結果はない。
