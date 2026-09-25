# Phase 5 v8 実カメラ・模擬ODOM・PC間dry-run診断 r01

## 結論

**FFB機能経路はPASS。録画品質は実効FPSのみFAIL。**

実カメラの青箱検出、専用模擬ODOM `0.25 m/s`、TTC WARNING、3連FFB command、PC間challenge、ハンコン接続PCの`dry_run` applyが同一sequenceで連結した。active command 11件はすべてadapterで`output_active=true`となり、要求0.25は上限0.05に制限された。faultは0件、最後は`shutdown`のinactiveで終了した。

標準録画解析の自動判定は`FAIL`だが、理由は実効FPS `29.341`が要件`30 fps ±1%`（`29.7〜30.3 fps`）を下回った1点だけである。フレーム完全性、青箱検出、観測採用、challenge、FFB送受信に失敗はない。したがって、本試験を**機能統合PASS・性能基準未達**と判定する。

## 入力と来歴

| 項目 | 値 |
|---|---|
| カメラarchive | `phase5_v8_camera_mock_odom_dryrun_r01_20260925_153955_320.tar.xz` |
| カメラSHA-256 | `5d60214d91b299d536b915d1aab01fce68cfb4d59e7127fea4a3d5f597cc4c93` |
| rosbag archive | `phase5_v8_camera_dryrun_r01.tar.xz` |
| rosbag SHA-256 | `8629afdbd61ec02808e4b1448a6cb522702d17f882fa7a0a026d1d62e9a55716` |
| config | `src/bird_eye_config_ttc_v8_ffb_distinct_unknown_challenge_20260925.json` |
| ODOM topic | `/phase5/mock_odom` |
| adapter | `output_mode=dry_run`, `freshness_mode=challenge`, `max_magnitude=0.05` |

## カメラ・検出・TTC

| 指標 | 結果 | 判定 |
|---|---:|---|
| 録画フレーム | 841 | - |
| raw / BEV / detection | 841 / 841 / 841 | PASS |
| 実効FPS | 29.341 | FAIL（30 fps ±1%基準） |
| 青箱検出 | 841 / 841（100%） | PASS |
| 観測採用 | 841 / 841（100%） | PASS |
| 追跡 | 841 / 841（100%） | PASS |
| 模擬ODOM移動フレーム | 99 | PASS |
| WARNINGフレーム | 99 | PASS |
| 最小TTC | 4.097 s | WARNING域と整合 |
| challenge age p95 / max | 19.34 / 57.65 ms | PASS（60 ms以内） |
| challenge不足による送信見送り | 0 | PASS |
| FFB publish success | 100% | PASS |

青箱の中央位置は`x=0.0294 m`、中央距離は`z=1.0265 m`で、試験条件の正面約1.0 mと整合する。

## PC間challenge・FFB照合

| 指標 | 結果 |
|---|---:|
| challenge | 24,541件 |
| FFB command | 9,955件 |
| adapter status | 9,949件 |
| 模擬ODOM | 12,617件 |
| `0.25 m/s` ODOM | 89件、約2.93秒 |
| active command | 11件 |
| active status | 11件 |
| challengeと照合できたactive command | 11 / 11 |
| カメラ→command同一sequence | 11 / 11 |
| command→status同一sequence | 11 / 11 |
| command→status遅延 | 0.266〜0.894 ms、中央0.480 ms |
| active challenge往復時間 | 7.804〜22.875 ms、中央17.454 ms |
| adapter mode | `dry_run` 9,949 / 9,949 |
| active適用値 | 0.05（11 / 11） |
| fault | 0 |
| 最終status | inactive / `shutdown` / `fault=false` |

activeは`9369〜9372`、`9374〜9376`、`9379〜9382`の3群に分かれ、間に`cadence_gap:triple`が記録された。実効フレーム間隔により各群のサンプル数は4 / 3 / 4だが、3回のON区間と有限終0.5秒の終了は成立している。

commandとstatusの総数差6件はBEST_EFFORTのinactive status欠落である。active 11件は全件照合でき、最終inactiveも記録されているため、機能判定には影響しない。

## 未達点と次の判断

- 実効FPSは前半`29.738`、後半`28.955`で、後半の低下が全体を`29.341` fpsまで下げた。有効処理時間p95は`36.20 ms`、40 ms超過率は`9.88%`だった。
- このFPS低下はFFB経路の成否を覆さないが、正式な30 fps性能受け入れは未達である。同時ダウンロード等を止めた条件で、今後の実験時に再確認する。
- v8のUNKNOWN単発は録画リスク再生で既にPC間dry-run PASSである。本試験ではWARNING経路を分離して確認したため、UNKNOWNを意図的に発生させていない。
- 次は別録画で短時間遮蔽を与え、実カメラ由来のUNKNOWNが単発になることを`dry_run`で確認する。その後に限り、Kobuki停止・上限0.05でhardware統合確認を検討する。

## 根拠成果物

- [`phase5_v8_camera_live_dryrun_r01_analysis/analysis_report.md`](phase5_v8_camera_live_dryrun_r01_analysis/analysis_report.md)
- [`phase5_v8_camera_dryrun_r01_bag_summary.json`](phase5_v8_camera_dryrun_r01_bag_summary.json)
- [`phase5_v8_camera_dryrun_r01_events.csv`](phase5_v8_camera_dryrun_r01_events.csv)
- [`report_assets/phase5_v8_warning_raw_frame_0407.png`](report_assets/phase5_v8_warning_raw_frame_0407.png)
