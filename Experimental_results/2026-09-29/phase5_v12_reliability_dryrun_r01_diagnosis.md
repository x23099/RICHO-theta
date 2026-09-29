# Phase 5 v12 reliability dry-run 診断

## 結論

**総合判定: PASS（2PC dry-run統合試験）**

v11で未達だった次の3点をすべて解消した。

1. active intent 23件がすべてcommandおよびactive statusまで到達した。
2. 録画区間内のadapter faultは0件で、最終statusはinactiveかつ`fault=false`だった。
3. 同一publisher方式により、0.25 m/sの450件がKobuki PC・ハンコンPCの両bagへ記録された。

録画中にchallenge間隔が60 msをわずかに超える場面があったが、stream安定状態は解除されず、active通知を失わなかった。個別challenge鮮度60 msは変更していないため、安全条件も維持されている。

この結果により、通信・判定経路は停止状態かつ上限0.05の低強度hardware確認へ進める。ただし、Kobukiを走行させる試験や強度引き上げは別段階とする。

## 入力と来歴

| ファイル | SHA-256 |
|---|---|
| `rokuga_phase5_v12_reliability_dryrun_r01_20260929_162234_202.tar.xz` | `91ebc108cf5834c7932fdd62dc6759578bddfc9644db5fe87f6044942eca7a9f` |
| `phase5_v12_mock_odom_r01.csv` | `7121fd6366e137c49889e75e5b1f996ce5f6fe94f93b8df3326ddd60d8d43394` |
| `K_phase5_v12_reliability_kobuki_r01.tar.xz` | `cc0662264cfd39549e437bab4028e24113b5048c20e0af7a39425227cb48ccf1` |
| `H_rosbugphase5_v12_reliability_hsr_r01.tar.xz` | `65bb47aff7913381637f9164d291ddd303d2883743c2c5d1a819c62ae1511748` |

カメラmetadataから、使用設定が `bird_eye_config_ttc_v12_ffb_reliability_20260929.json`、relay stream timeoutが0.2秒、個別challenge max ageが0.06秒であることを確認した。adapter statusは全件`dry_run`である。

## 判定一覧

| 評価項目 | 結果 | 判定 |
|---|---:|---:|
| カメラ録画完全性 | raw/BEV/detection各1,045 frame | PASS |
| 実効FPS | 29.950 fps | PASS |
| 疑似ODOM CSV | 5,753件、送信失敗0 | PASS |
| 両bagの0.25 m/s | 各450件 | PASS |
| active intent→command | 23/23 | PASS |
| active command→status | 23/23 | PASS |
| WARNING active status | 18件 | PASS |
| UNKNOWN active status | 5件、2イベント | PASS |
| 録画中のrelay stream不安定拒否 | 0件 | PASS |
| 録画中のadapter fault | 0件 | PASS |
| adapter出力mode | 全件`dry_run` | PASS |
| 最終status | inactive、shutdown、fault=false | PASS |

## 疑似ODOMと時刻照合

CSVは同じpublisherを維持して次の順で送信した。

| phase | 件数 | 時刻（JST） | 速度 |
|---|---:|---|---:|
| waiting_for_start | 5,003 | 16:19:48.569～16:22:39.245 | 0.00 m/s |
| initial_stop | 150 | 16:22:39.245～16:22:44.212 | 0.00 m/s |
| forward_0p25 | 450 | 16:22:44.245～16:22:59.212 | 0.25 m/s |
| final_stop | 150 | 16:22:59.246～16:23:04.212 | 0.00 m/s |

送信予定からの誤差は中央値0.104 ms、p95 0.237 ms、最大0.798 ms。送信間隔は中央値33.334 ms、p95 33.457 ms、最大34.033 msだった。

| 記録元 | 0.25 m/s件数 | 記録区間（JST） |
|---|---:|---|
| 外部CSV | 450 | 16:22:44.245～16:22:59.212 |
| Kobuki PC bag | 450 | 16:22:44.245～16:22:59.212 |
| ハンコンPC bag | 450 | 16:22:44.257～16:22:59.224 |
| カメラCSV | 448 frame | 録画経過10.075～25.051秒 |

v11では両bagが旧publisherの速度0だけを記録し、シナリオの0.25 m/sを捕捉できなかった。v12では待機からシナリオ終了までpublisherを維持したため、両bagで速度変化を完全に捕捉できた。

## カメラ・認識結果

録画区間は16:22:34.202～16:23:09.075 JST、約34.874秒だった。

| 指標 | 結果 |
|---|---:|
| frame数 | 1,045 |
| 実効FPS | 29.950 fps |
| 青箱検出率 | 86.51% |
| 測定採用率 | 96.02% |
| 追跡率 | 85.07% |
| ODOM利用率 | 87.46% |
| 有効処理時間p95 | 29.93 ms |
| 最小有限TTC | 4.356 s |
| raw_ground_distance安定採用率 | 98.30% |
| 最大abs(vz) | 0.0363 m/s |

標準解析の表示は`DIAGNOSTIC`だが、解析失敗ではない。正式要件CSVを指定しなかったため、標準解析単独では実験PASSを宣言しない仕様による。録画完全性とゲート再生はPASSしている。

## WARNING・UNKNOWNと再arm

activeは次の8区間、計23件だった。

| 種別 | frame | 録画経過時間 | sequence | command/status |
|---|---|---|---|---:|
| WARNING | 305～307 | 10.142～10.208 s | 3618～3620 | 3/3 |
| WARNING | 311～312 | 10.341～10.375 s | 3624～3625 | 2/2 |
| WARNING | 315～317 | 10.475～10.542 s | 3628～3630 | 3/3 |
| UNKNOWN 1 | 367～369 | 12.208～12.276 s | 3680～3682 | 3/3 |
| WARNING | 433～436 | 14.434～14.526 s | 3746～3749 | 4/4 |
| WARNING | 439～441 | 14.616～14.674 s | 3752～3754 | 3/3 |
| WARNING | 444～446 | 14.775～14.841 s | 3757～3759 | 3/3 |
| UNKNOWN 2 | 730～731 | 24.307～24.342 s | 4043～4044 | 2/2 |

1回目の遮蔽では測定無効が11.442～14.398秒まで継続した。この間、青色のraw検出は短く何度も復帰したが、`collision_measurement_valid`はfalseのままで、UNKNOWNは最初の1イベントしか発火しなかった。raw検出だけで再armしないv11以降の条件が実機映像でも機能している。

その後、有効測定が14.434～17.542秒の約3.108秒間連続し、0.5秒の再arm条件を満たした。さらに18.374～23.507秒にも約5.133秒の有効測定があり、23.541秒からの最終遮蔽に対して2回目のUNKNOWNを許可した。したがって、長い有効復帰後に再armできることも確認できた。

17.574～18.341秒の短い遮蔽では、0.8秒のWARNING holdが切れる前に有効測定へ戻ったためUNKNOWN状態には移行していない。これは再armの失敗ではなく、衝突状態機械のhold動作による。

## relay・adapter結果

録画区間のKobuki PC bagでは、intent 1,044件に対してforward 1,040件、見送り4件だった。4件はすべて`receiver_challenge_already_used`で、active intentではない。active 23件はすべて`authorized`だった。

challenge受信間隔はKobuki側で60 ms超が2回、最大63.917 msだった。これは個別challenge鮮度60 msを一時的に超えるが、200 msのstream timeout未満である。診断の`challenge_stream_restart_count`は録画全体で1のまま、`receiver_challenge_stream_not_stable`は録画中0件だった。v12の分離設計が実PC間でも期待どおり動作した。

adapterへ届いたactive statusは23件すべて次を満たした。

- `output_mode=dry_run`
- `action=apply`
- `output_active=true`
- `applied_magnitude=0.05`
- `fault=false`

WARNINGは要求0.25、UNKNOWNは要求0.15で、いずれもadapter上限0.05へ制限された。active commandからstatusまでのKobuki bag上の遅延は中央値3.042 ms、最大9.594 msだった。

bag全体にある`receiver_challenge_stream_not_stable` 5件はrelay起動直後のsequence 0～4で、録画開始より約112秒前に発生した期待どおりの起動ゲートである。

## v11との比較

| 指標 | v11 | v12 |
|---|---:|---:|
| active intent | 27 | 23 |
| active command | 12 | 23 |
| active status | 11 | 23 |
| active配送率 | 40.7% | 100% |
| 録画中stream不安定見送り | 567 | 0 |
| 録画中fault | 1 | 0 |
| 両bagの0.25 m/s | 0件 | 各450件 |
| 最終inactive/fault=false | PASS | PASS |

## 次の作業

次はKobukiを停止させたまま、G923を接続した低強度hardware確認を行う。

1. v12と同じcamera→intent→relay→command経路を使う。
2. adapterは`hardware`、`max_magnitude=0.05`、既存のhardware安全ゲートをすべて有効にする。
3. 最初は録画再生または専用mock ODOMを用い、Kobukiを走行させない。
4. WARNING 3連とUNKNOWN単発を体感・status・bagで確認する。
5. fault 0、最終inactive、意図しない連続振動なしを満たすまで走行試験へ進まない。

## 成果物

- 標準解析: `phase5_v12_reliability_dryrun_r01_analysis/`
- Kobuki bag要約: `phase5_v12_reliability_kobuki_r01_bag_summary.json`
- Kobuki録画時間窓イベント: `phase5_v12_reliability_kobuki_r01_recording_window_events.csv`
- HSR bag要約: `phase5_v12_reliability_hsr_r01_bag_summary.json`
- HSR録画時間窓イベント: `phase5_v12_reliability_hsr_r01_recording_window_events.csv`
- 疑似ODOM CSV: `phase5_v12_mock_odom_r01.csv`
- 無加工確認画像: `report_assets/phase5_v12_*.png`

bag全体の件数と時間範囲は各`bag_summary.json`へ保存し、イベントCSVはカメラ録画時間窓だけへ限定した。
