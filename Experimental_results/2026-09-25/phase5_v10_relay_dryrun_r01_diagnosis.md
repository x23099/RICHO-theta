# Phase 5 v10 relay・実カメラPC間dry-run診断 r01

## 結論

**遮蔽操作は成功している。v10 relayは録画区間のtoken faultを0件にしたが、active intentを1件fail-closedで見送ったため、試験全体は条件付きPASS・hardware移行は保留とする。**

2回目の模擬ODOM `0.25 m/s`は録画開始52.325～58.724秒にカメラへ届いた。UNKNOWNは52.925～53.630秒、青箱の連続未検出は54.157秒から始まっており、いずれも模擬ODOMの送信中である。したがって、今回の一人作業でも遮蔽は時間内に成立した。

## 入力と来歴

| 入力 | SHA-256 |
|---|---|
| `phase5_v10_relay_dryrun_r01_20260925_173142_491.tar.xz` | `a52bd87ba1a68b5fb0b01c3ce1839cb10ec1be1588573d73fab93364c389a131` |
| `phase5_v10_relay_kobuki_r01.tar.xz` | `f0a1cacd09ee4ae7bb4ffb6f0eda6d0c00856bb1743f6dd253c8d3cf1a389f7c` |
| `phase5_v10_relay_hsr_r01.tar.xz` | `b906875fb204b5da38a097f219ab541b6c37150a0cead35415285e6797a4f911` |

| 項目 | 値 |
|---|---|
| session | `phase5_v10_relay_dryrun_r01_20260925_173142_491` |
| config | `src/bird_eye_config_ttc_v10_ffb_relay_20260925.json` |
| 録画窓 | 17:31:42.491～17:32:59.385 JST |
| adapter | `dry_run`のみ |
| ODOM topic | `/phase5/mock_odom` |

## カメラ・操作タイミング

| 指標 | 結果 |
|---|---:|
| frame / raw・BEV・detection | 2297 / 2297・2297・2297 |
| 実効FPS | 29.870 |
| 有効処理時間p95 | 27.48 ms |
| 青箱検出 | 2048/2297（89.16%） |
| ODOM available | 1042/2297（45.36%） |
| 最小有限TTC | 1.831 s |

カメラCSVで確認した区間は次のとおりである。

| 区間 | 録画開始から | フレーム数 |
|---|---:|---:|
| 1回目 `0.25 m/s` | 21.961～28.361 s | 191 |
| WARNING | 22.034～28.430 s | 180 |
| 2回目 `0.25 m/s` | 52.325～58.724 s | 193 |
| UNKNOWN | 52.925～53.630 s | 16 |
| 青箱連続未検出 | 54.157～62.336 s | 244 |

UNKNOWNは遮蔽物を持って箱へ近づく途中、青箱の測定が不安定になった時点から始まった。その後、黒い遮蔽物を青箱前へ置いた状態も生画像で確認した。操作が遅すぎたという判定ではない。

## v10 relay・adapter

### 録画区間

| 指標 | ハンコン接続PC bag |
|---|---:|
| intent | 2297 |
| command | 2294 |
| status | 2292 |
| challenge | 3844 |
| active intent | 16 |
| active command / status | 15 / 15 |
| fault | **0** |
| active intent→command遅延 | median 0.648 ms、max 6.334 ms |

適用されたactive 15件はすべて`dry_run`、`fault: false`、`applied_magnitude=0.05`だった。内訳はWARNING 6件、UNKNOWN 9件であり、両種の経路がadapterまで到達した。

active intent `sequence=3676`だけはcommandにならなかった。relayが新しいchallengeを確保できない場合に送信を見送るfail-closed動作と整合する。commandになったactive 15件にはすべて既知のchallengeがあり、challenge発行からcommandまで6.711～21.823 msだった。

### 録画開始前

両bag全体ではtoken faultが34件（`unknown_receiver_token` 31、`expired_receiver_token` 3）ある。ただし全件が17:29:39.685～17:30:22.096 JSTのinactive `no_alert`で、録画開始より80秒以上前に終了している。WARNING/UNKNOWNのactive commandにはfaultがない。

これはアプリ・DDS立ち上がり中のcallback滞留と考えられる。hardware試験前には、relay起動後に一定時間faultがないことを確認するready gateが必要である。

## 未解決点

1. active intent 16件中1件がcommandにならなかった。
2. UNKNOWN activeは4つの短い群に分かれた。測定可否が瞬間的に戻るたびにUNKNOWN cadenceが再armされているため、ユーザーが「単発」と感じる保証がまだ弱い。
3. 両PCのbagに記録された`/phase5/mock_odom`は0.0 m/sだけだった。一方、カメラCSVは0.25 m/sを合計384フレーム受信している。今回の判定にはカメラCSVを使えるが、次回は模擬ODOM送信側の独立ログも残す必要がある。
4. 標準解析の`raw_ground_distance observation gate failed`は、遮蔽ラベルなし録画を回帰要件で判定した結果であり、今回のFFB通信試験の失敗理由ではない。

## 次の対応

新しい録画はまだ不要である。まず追加録画なしで次を実装・回帰する。

1. UNKNOWNを再armするには、青箱の有効測定が一定時間連続することを要求し、短い測定復帰で単発通知が繰り返されないようにする。
2. relayの起動安定判定を追加し、challenge流が安定するまでintentを転送しない。
3. relayの見送り理由を記録できる診断出力を追加する。
4. 一人試験用に、停止→長めの0.25 m/s→停止を自動送信し、実送信時刻をCSVへ残すシナリオコマンドを用意する。

再試験する場合、0.25 m/s区間を15秒にすれば、送信開始後に端末から箱まで移動しても十分な余裕がある。ただし今回のUNKNOWNデータはすでに取得できているため、上記コード修正のオフライン回帰に使用できる。

## 成果物

- `phase5_v10_relay_dryrun_r01_analysis/analysis_report.md`
- `phase5_v10_relay_kobuki_r01_bag_summary.json`
- `phase5_v10_relay_kobuki_r01_events.csv`
- `phase5_v10_relay_hsr_r01_bag_summary.json`
- `phase5_v10_relay_hsr_r01_events.csv`
- `report_assets/phase5_v10_warning_raw_frame_0657.png`
- `report_assets/phase5_v10_unknown_raw_frame_1582.png`
- `report_assets/phase5_v10_occlusion_raw_frame_1620.png`
- `report_assets/phase5_v10_occlusion_raw_frame_1700.png`
