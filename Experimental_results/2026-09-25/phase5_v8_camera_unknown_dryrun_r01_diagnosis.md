# Phase 5 v8 実カメラUNKNOWN単発・PC間dry-run診断 r01

## 結論

**UNKNOWN単発仕様はPASS。PC間統合試験全体はFAIL。hardwareへはまだ進まない。**

青箱の遮蔽後、カメラ側は`WARNING_HOLD`から`UNKNOWN`へ遷移した。UNKNOWN activeはframe 502〜504の3件だけで、開始から最初のinactiveまで`0.101382 s`だった。その後はUNKNOWNが継続しても22フレームすべて`unknown_pulse_complete`のinactiveとなり、再発火しなかった。active sequence `4906〜4908`はすべてPC間で配送され、adapterが`dry_run` / `action=apply` / `output_active=true` / `applied_magnitude=0.05` / `fault=false`として適用した。

一方、試験録画区間にchallenge tokenの拒否が24件あった。内訳は`unknown_receiver_token` 23件、`expired_receiver_token` 1件である。WARNING / WARNING_HOLD active command 15件のうちadapterでactive適用を確認できたのは9件だけだった。adapterは拒否時に出力を停止しておりfail-safeだが、警告配送の安定性基準を満たさない。

## 入力と来歴

| 項目 | 値 |
|---|---|
| カメラarchive | `phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310.tar.xz` |
| カメラSHA-256 | `dfc8fee1182bcce184186fa883590b5a602129fa674bf352635b41424f62deed` |
| rosbag archive | `phase5_v8_camera_unknown_dryrun_r01.tar.xz` |
| rosbag SHA-256 | `154e8d4c3b4d3be1c9bab6c9474e9b01cc2cab7a49fa1c790766248c39ade3d5` |
| session | `phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310` |
| config | `src/bird_eye_config_ttc_v8_ffb_distinct_unknown_challenge_20260925.json` |
| 試験録画区間 | 16:04:15〜16:04:58.091 JST |

rosbagは15:57から記録されており、当該録画より前の別プロセスと同じsequence番号が含まれる。そのため全bagのsequence集合だけでstatusを照合せず、上記の試験録画時刻で切り出して判定した。

## 遮蔽とUNKNOWN単発

| 指標 | 結果 | 判定 |
|---|---:|---|
| カメラフレーム | 1,264 | 完全性PASS |
| WARNING | 99フレーム | PASS |
| WARNING_HOLD | 74フレーム | PASS |
| UNKNOWN | 25フレーム | PASS |
| UNKNOWN active | 3フレーム | PASS |
| UNKNOWN active sequence | 4906, 4907, 4908 | PASS |
| UNKNOWN開始 | `17.322468 s` | - |
| 最初のinactive | `17.423850 s` | - |
| 開始→inactive | `0.101382 s` | 約0.1秒の単発 |
| 後続`unknown_pulse_complete` | 22フレーム | 再発火なし |
| UNKNOWN adapter apply | 3 / 3 | PASS |
| UNKNOWN requested / applied | 0.15 / 0.05 | PASS |
| UNKNOWN status fault | 0 | PASS |

青箱の完全な未検出は録画開始`16.822 s`から始まり、最後のWARNING再確認後の有限holdが切れて`17.322 s`にUNKNOWNとなった。速度0へ戻った後は3フレームの解除確認を経てCLEARとなり、遮蔽解除後に不要な追加WARNINGは発生していない。

## PC間統合の未達

| 指標 | 結果 | 判定 |
|---|---:|---|
| 録画区間command | 1,240 | - |
| 録画区間status | 1,216 | - |
| 録画区間challenge | 2,136 | - |
| active command | 18 | - |
| active status | 12 | FAIL（18 / 18未達） |
| WARNING / HOLD active command | 15 | - |
| WARNING / HOLD active status | 9 | FAIL |
| UNKNOWN active command / status | 3 / 3 | PASS |
| カメラ側challenge見送り | 24フレーム | FAIL |
| FFB publish success | 98.10% | FAIL |
| challenge age p95 / max | 33.38 / 250.93 ms | maxが60 ms超過 |
| adapter fault | 24 | FAIL |
| fault内訳 | unknown token 23 / expired token 1 | - |
| adapter mode | 全件`dry_run` | PASS |
| 録画区間最終status | inactive / clear / fault=false | PASS |
| bag最終status | inactive / shutdown / fault=false | PASS |

代表例としてsequence `4738`は、カメラ側ではchallenge受信から`3.24 ms`の新鮮なtokenと認識したが、bag上のchallenge発行→commandは約`167 ms`で、adapterが`unknown_receiver_token`として拒否した。これは、送信側が「challenge callbackが処理された時刻」からの年齢しか判断できず、受信キューへ到着する前の遅延を観測できないことを示す。adapter側の検査は受信側時計で正しく拒否しており、安全性は保たれたが、配送の成功率は不十分である。

## 録画品質

実効FPSは`29.325`で、30 fps ±1%基準の下限`29.7 fps`を下回った。これは前回の`29.341 fps`と同傾向である。また標準解析のobservation gateはFAILだが、本試験で青箱を意図的に遮蔽し、遮蔽ラベルを指定していないためである。UNKNOWN試験の成否とは分けて扱う。

## 次の作業

hardware試験や追加録画をすぐ繰り返す段階ではない。まず、challenge発行からsender callback処理までの遅延が送信側の`challenge_age`に反映されない問題と、`challenge_unavailable`時のcadence resetによる再開始挙動をコード側で診断する。fault 0、active command/status全件一致をdry-runで再確認してからhardwareへ進む。

この診断に対するコード修正は `challenge_recovery_implementation.md` に記録した。修正後のv9候補はローカル回帰試験まで完了しており、次の判定点はPC間dry-run再試験である。

## 根拠成果物

- [`phase5_v8_camera_unknown_dryrun_r01_analysis/analysis_report.md`](phase5_v8_camera_unknown_dryrun_r01_analysis/analysis_report.md)
- [`phase5_v8_camera_unknown_dryrun_r01_bag_summary.json`](phase5_v8_camera_unknown_dryrun_r01_bag_summary.json)
- [`phase5_v8_camera_unknown_dryrun_r01_events.csv`](phase5_v8_camera_unknown_dryrun_r01_events.csv)
- [`phase5_v8_camera_unknown_dryrun_r01_window_summary.json`](phase5_v8_camera_unknown_dryrun_r01_window_summary.json)
- [`report_assets/phase5_v8_unknown_raw_frame_0502.png`](report_assets/phase5_v8_unknown_raw_frame_0502.png)
