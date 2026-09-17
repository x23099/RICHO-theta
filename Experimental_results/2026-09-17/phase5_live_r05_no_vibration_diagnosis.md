# Phase 5 r05 無振動の診断（2026-09-17）

## 入力

- カメラ録画: `202609171656.tar.xz`（SHA-256: `b2517ec7f737271a7355e5f3f1701d4ee6283a081687c7584f238c4bd6285f3c`）
- ROS bag: `202609171655.tar.xz`（SHA-256: `59dee1b4112012b8843ca38ba4524baacdf8e4811f43845e933e8c0b1ea01e9d`）
- 派生成果物: `phase5_live_r05_analysis/`, `phase5_live_r05_bag_summary.json`, `phase5_live_r05_events.csv`

## 結論

この試験では振動しないのがログと整合する。映像による警告と ROS コマンドの送信までは成功したが、ハンコン側の adapter がコマンドの時刻を約 58 ms「未来」と判定し、すべてのアクティブな出力を停止した。強度不足ではない。物理ハードウェア故障も、この試験だけでは示されない。

## 根拠

| 観測箇所 | 結果 |
|---|---|
| カメラ | 774 frame、実効 29.967 fps、検出 774/774、ODOM 有効 541/774、WARNING 123 frame |
| 録画 CSV | FFB アクティブ 9 frame、要求値 0.25、publish failure 0 |
| ROS bag の command | 上記と同じ sequence 9 件を受信（1179–1181、1184–1186、1189–1191） |
| ROS bag の status | `output_mode=hardware` のみ 1945 件、`output_active=true` は 0 件 |
| アクティブ 9 件の status | 全件 `action=stop`, `fault=true`, `applied_magnitude=0`, `invalid_request:future_message:age=-0.057181`～`-0.058372` 秒 |
| 全 status | 1914 件が `future_message`。時刻差は一時的な 9 件だけの異常ではない |
| コマンド header と bag 記録時刻 | アクティブ 9 件では header が bag 記録時刻より約 57.45–58.66 ms 先行 |

ROS bag のフォルダ名に `dryrun` があるが、記録された status は **hardware** であり、名前だけで実行モードを判定しない。adapter の既定 `future_tolerance_sec=0.05` 秒を約 7–8 ms 超過している。送受信 PC の時計の相対差、またはタイムスタンプ生成経路を点検する必要がある。どちらの PC の時計が正確かは、このログだけでは確定できない。

## 次の安全な切り分け

1. ハンコン側 adapter を停止し、`/collision/ffb_status` の Publisher が 0 であることを確認する。二重起動させない。
2. 両 PC で同時刻の `date +%s.%N`、`timedatectl --no-pager timesync-status` を採り、NTP 同期の状態と相対時刻差を確認する。ただし手動コマンドの実行差だけで ms 精度の結論は出さない。
3. ハンコン側を **dry_run** で一つだけ起動し、短いコマンド列で `future_message` が消え、`output_active=true` と `applied_magnitude>0` を確認する。これが成立するまで hardware 試験を再開しない。
4. 相対時刻差が再発するなら、単に許容幅を広げるのではなく、時計同期または通信時刻の検証方式を設計し直す。特に安全判定を緩める変更は別途検証が必要。

`phase5_live_r05_analysis/analysis_report.md` の `DIAGNOSTIC` は要件 CSV 未指定による判定であり、ここでの無振動原因判定とは別物。
