# 時計非依存 FFB: ローカル dry-run 検証

2026-09-17、隔離した ROS_DOMAIN_ID=211、ROS_LOCALHOST_ONLY=1 の環境で、更新済み `oit_interfaces`、`collision_ffb_node`、`collision_ffb_probe` を使用した。adapter は `output_mode=dry_run`, `freshness_mode=challenge` で起動し、G923 にはアクセスしていない。

| 指標 | 結果 |
|---|---:|
| command / active command | 18 / 15 |
| status / active apply coverage | 18 / 15/15 (1.000) |
| fault | 0 |
| 最大適用強度（dry-run上の値） | 0.050 |
| 応答時間 p95 | 2.128 ms |
| 最終 CLEAR 停止時間 | 1.303 ms |
| 自動判定 | PASS |

probe が送った command には受信側発行の非ゼロ session/token が入り、adapter はすべての active 指令を受理した。別途、時刻の異なる生成値でも受理すること、期限切れ・別セッション・重複指令を拒否すること、watchdog 停止を単体テストで確認した。

この結果は**同一ホストの dry-run 統合試験**であり、2台のPC間の遅延・欠落や物理ハンコンの出力を保証しない。次の判断材料は実PC間での challenge probe、続いてカメラと模擬ODOMを使った dry-run の rosbag である。
