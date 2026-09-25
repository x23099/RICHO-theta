# Phase 5 v9 challenge回復・実カメラPC間dry-run診断 r01

## 結論

**総合FAIL。hardwareへは進まない。同条件の追加録画も、次のコード修正前には行わない。**

v9で追加したtoken単回使用と有限cadenceの非再発火は成立した。一方、0.10秒の回復待ちを終えた時点でもカメラプロセスが古いchallenge callbackを処理しており、受信側adapterへ期限切れtokenが送られた。試験録画区間のadapter faultは21件、active commandは5件中3件だけが適用された。このためPC間配送の合格条件を満たさない。

また、青箱遮蔽は模擬ODOM 0.25 m/sの終了後に始まっており、リスクは遮蔽前にCLEARへ戻った。今回の録画にUNKNOWNはなく、UNKNOWN単発の再検証には使用できない。

## 入力と来歴

| 入力 | SHA-256 |
|---|---|
| `phase5_v9_camera_unknown_dryrun_r01_20260925_164955_362.tar.xz` | `d2611d77fd7fa9b9236cb188be4a52d4bbe7a33ae766c9f694e1b30492dc8838` |
| `phase5_v9_challenge_recovery_kobuki_r01.tar.xz` | `c2b1519e19dc106f9c5f6e90c4bf09346b001d2e1c4cfba1e6ec644f7baaba25` |
| `phase5_v9_challenge_recovery_hsr_r01.tar.xz` | `ae0da0a2eb28639d7dfb99d44306815b9354d06d8109bb8d7d2e2148e45c6fe1` |

| 項目 | 値 |
|---|---|
| session | `phase5_v9_camera_unknown_dryrun_r01_20260925_164955_362` |
| config | `src/bird_eye_config_ttc_v9_ffb_challenge_recovery_20260925.json` |
| 録画区間 | 2026-09-25 16:49:55.362〜16:50:45.927 JST |
| adapter | 全status `output_mode=dry_run` |
| ODOM | 専用`/phase5/mock_odom` |

## カメラ・リスク判定

| 指標 | 結果 | 判定 |
|---|---:|---|
| frame / raw・BEV・detection | 1,483 / 1,483・1,483・1,483 | PASS |
| 実効FPS | 29.309 | FAIL（30 fps ±1%未達） |
| 青箱検出 | 829 / 1,483 | 遮蔽を含む |
| 観測採用 | 99.76% | PASS |
| 模擬0.25 m/s利用 | 182フレーム、10.742〜16.982 s | PASS |
| WARNING | 183フレーム、10.808〜17.082 s | PASS |
| UNKNOWN | 0フレーム | FAIL（条件未成立） |
| FFB active command | 5件 | 3連の一部のみ配送成功 |

模擬ODOMは約6秒間送信された。カメラ側で最後に0.25 m/sを利用したのは16.982秒、リスクがCLEARへ戻ったのは17.119秒である。青箱の未検出開始は17.248秒だったため、遮蔽は移動状態の終了から約0.27秒後だった。すでにCLEARだったので`WARNING_HOLD → UNKNOWN`へ進まなかった。frame 318は青箱が見えるWARNING、frame 504は人が黒い遮蔽物で青箱を覆った状態である。

## v9回復処理

| 指標 | 結果 |
|---|---:|
| FFB publish成功率 | 92.99% |
| challenge見送り | 104 / 1,483フレーム |
| `recovery_cooldown` | 64フレーム |
| `no_recent_receiver_challenge` | 29フレーム |
| `already_used` | 11フレーム |
| `callback_gap`記録 | 94フレーム |
| `sender_age`記録 | 18フレーム |
| callback gap最大 | 273.06 ms |
| sender age最大 | 205.78 ms |

回復理由と検出時間はCSVへ正しく記録された。送信済みtokenの再利用はHSR bag上で0件であり、同一WARNING中のactiveは開始後約0.42秒で終了し、その後の再発火もない。この2点はv9修正の意図どおりである。

しかし、固定0.10秒の回復待ちでは受信キューが最新tokenへ追いついたことを保証できなかった。callback gapは最大273 msあり、回復終了直後でもsenderが見たローカルageと、HSRで測ったchallenge発行→command時間が大きく異なる。

## active command照合

| seq | sender age | HSR challenge→command | adapter結果 |
|---:|---:|---:|---|
| 6060 | 9.48 ms | 109 ms | status未観測、applyなし |
| 6061 | 0.47 ms | 69 ms | apply後、watchdog stop |
| 6063 | 25.70 ms | 269 ms | `unknown_receiver_token`で拒否 |
| 6066 | 10.99 ms | 59 ms | apply |
| 6067 | 15.04 ms | 65 ms | apply |

カメラ側ではseq 6063を25.70 msの新しいtokenと判断したが、受信側で見た往復は269 msだった。callbackが実行された時刻を起点にしたsender ageだけでは、callback実行前の滞留を測れないというv8の原因が残っている。

録画区間の全commandでは、HSR bagでtokenと照合できたものが1,377 / 1,378件だった。challenge発行→commandは中央値17 ms、p95 48 ms、最大403 msで、100 ms超過が22件、sender期限60 ms超過が48件あった。

## adapter照合

| 指標 | Kobuki bag | HSR bag |
|---|---:|---:|
| challenge | 2,509 | 2,510 |
| command | 1,378 | 1,378 |
| status | 1,364 | 1,363 |
| active apply | 3 | 3 |
| fault | 21 | 21 |

fault内訳は`unknown_receiver_token` 18件、`expired_receiver_token` 2件、`watchdog_timeout` 1件で両bagが一致した。watchdogはseq 6061のapply後、有効な後続commandが0.10秒以内に届かなかったため安全停止した。adapterの拒否・停止動作は正しく、受信側の期限を緩める理由はない。録画区間の最終statusはinactive / clear / fault=false、bag終了時もinactive / shutdown / fault=falseだった。

## 原因と次の実装

カメラGUIとchallenge subscriberが同じPythonプロセスにある限り、画像処理中のGIL・executor遅延によって、callback前のtoken滞留をsenderから正確に観測できない。待ち時間を0.10秒から単純に延長する方法は、配送の成立を保証せず、通知遅延と見送り時間だけを増やすヒューリスティックになる。

次はchallenge受信と最終`/collision/ffb_command`送信を、カメラGUIとは別プロセスのrelayへ分離する。`bird_eye.py`はローカルのrisk intentだけを送信し、専用relayがreceiver challengeとintentの両方を検査してcommandへ変換する。受信側adapterのchallenge期限0.10秒、watchdog 0.10秒、強度上限は維持する。

この分離は`challenge_relay_implementation.md`のv10候補として実装した。次の実機判定はhardwareではなくPC間`dry_run`で行う。

別プロセス化と自動テストを完了するまでは再録画しない。次の実カメラ試験では、0.25 m/s開始約2秒後に遮蔽を開始し、速度送信が終わるまで遮蔽を維持する。

## 根拠成果物

- `phase5_v9_camera_unknown_dryrun_r01_analysis/analysis_report.md`
- `phase5_v9_camera_unknown_dryrun_r01_window_summary.json`
- `phase5_v9_camera_unknown_dryrun_r01_active_reconciliation.csv`
- `phase5_v9_challenge_recovery_kobuki_r01_bag_summary.json`
- `phase5_v9_challenge_recovery_kobuki_r01_events.csv`
- `phase5_v9_challenge_recovery_hsr_r01_bag_summary.json`
- `phase5_v9_challenge_recovery_hsr_r01_events.csv`
- `report_assets/phase5_v9_warning_raw_frame_0318.png`
- `report_assets/phase5_v9_occlusion_raw_frame_0504.png`
