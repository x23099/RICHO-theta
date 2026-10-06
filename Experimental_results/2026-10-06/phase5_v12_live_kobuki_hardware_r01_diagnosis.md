# Phase 5 v12 実Kobuki走行 hardware r01 診断

## 結論

**総合判定: PASS**

実Kobukiの`/odom`を用いた低速直進でTTC WARNINGが成立し、active通知8件が`intent → relay command → hardware status`へ欠落なく到達した。active statusは8件すべて`output_mode=hardware`、`action=apply`、`output_active=true`、適用強度0.05、`fault=false`だった。3つ目のactive区間終了から30.5 ms後には`action=stop`、`output_active=false`となり、bag終了時には`reason=shutdown`、`fault=false`を確認した。

Kobukiの実速度は最大0.213 m/s、移動量は約0.412 mで、カメラ推定距離約0.96 mに停止した。実速度上限0.25 m/sおよび停止線0.80 mを越えていない。ログ上は実走行hardware統合試験に合格している。

実施者は3回連続の振動を明確に感じ、その後に不要な振動はなかったと報告した。記録上の3つのactive区間および終了後の`output_active=false`と体感が一致するため、ログと体感を合わせて総合PASSとする。操縦・停止を妨げる異常の申告もない。

標準解析器の`FAIL`は、動的接近の視覚速度を静的安定性検査が外れ値扱いしたためであり、録画、WARNING、配送、hardware出力の失敗ではない。

## 入力と来歴

| ファイル | SHA-256 |
|---|---|
| `rokuga_phase5_v12_live_kobuki_hardware_r01_20261006_143236_125.tar.xz` | `afc509fd5b58617f623f320d3c832c17cb4f4eae1a7771d7c79a6a9c380c7ae8` |
| `K_rosbug_phase5_v12_live_kobuki_hardware_kobuki_r01.tar.xz` | `19827490bd29837964fbaf810348d26877043890ebbf3662eaa051c8f2d72964` |
| `H_rosbug_phase5_v12_live_kobuki_hardware_hsr_r01.tar.xz` | `ffe28959614bf2f1ff05d65e090a3d629f6d743a0365a038aaea7ef44e88c219` |

- カメラ録画開始: 2026-10-06 14:32:36.125 JST
- 録画時間: 約21.72秒
- config: `src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`
- ODOM: 実機`/odom`
- adapter: `hardware`、challenge freshness、安全ゲート有効、上限0.05
- bag集計窓はセッション名の開始時刻とカメラCSVの継続時間から定めた。

## 判定一覧

| 評価項目 | 結果 | 判定 |
|---|---:|---:|
| カメラ録画完全性 | raw/BEV/detection各650 frame | PASS |
| 実効FPS | 29.920 fps、30 fps±1%内 | PASS |
| 青箱raw検出 | 650/650、100% | PASS |
| 有効測定・追跡 | 308/650、47.38% | 注意 |
| 実ODOM | 両bag各1,091件、正方向移動134件 | PASS |
| 最大実速度 | 0.213 m/s | PASS |
| 最大移動量 | 約0.412 m | PASS |
| 最終カメラ推定距離 | 約0.960 m | PASS |
| 最小有限TTC | 4.375秒 | PASS |
| WARNING | 22 frame、約0.70秒 | PASS |
| active intent→command→status | 8→8→8、欠落0 | PASS |
| adapter mode | 録画窓status 636件すべて`hardware` | PASS |
| active物理出力 | 8件すべてactive、適用値0.05 | PASS |
| 録画区間内adapter fault | 0件 | PASS |
| active終了後の停止 | 30.5 ms後に`output_active=false` | PASS |
| bag最終status | `shutdown`、出力0、`fault=false` | PASS |
| 3連FFBの体感 | 3回連続を明確に体感 | PASS |
| 停止後の不要振動 | なし | PASS |
| FFBによる停止操作への悪影響 | 異常申告なし | PASS |

## 走行結果

| 指標 | 結果 |
|---|---:|
| `/odom`最高速度 | 0.2132 m/s |
| 走行中速度中央値 | 0.1642 m/s |
| 走行中速度p95 | 0.2068 m/s |
| `/cmd_vel`最大値 | 0.2592 m/s |
| `/cmd_vel`中央値 | 0.1944 m/s |
| 正方向走行区間 | 14:32:46.443～14:32:49.231 JST |
| ODOM正味移動量 | 0.4123 m |
| ODOM積算移動量 | 0.4125 m |

実速度は上限0.25 m/s以下だった。`/cmd_vel`は0.25 m/sを超える値が7件、約0.30秒あり、最大0.2592 m/sだったが、Kobukiの実速度は最大0.2132 m/sに留まった。再試験で指令上限を厳密に管理する場合は操縦入力側を0.25 m/s以下へ制限する。

`/cmd_vel.angular.z`は全64件で0だった。ODOM角速度は走行中中央値0.016 rad/s、p95 0.065 rad/sで、直進試験として大きな旋回はない。

青箱の初期raw距離は約1.46 mで、設定上の校正有効上限1.35 mおよび領域上限1.40 mより遠かった。このため前半340 frameは主に`calibration_range_gate`で測定不採用になった。接近後は追跡が成立し、走行中の有効追跡距離は約1.342 mから0.970 mへ減少した。停止後の最終追跡距離は約0.960 mだった。

## TTCと物理FFB出力

WARNINGはframe 372～393、録画経過12.390～13.092秒で成立した。最小TTCはframe 374の4.375秒だった。WARNING activeはtriple cadenceとして3区間に分かれた。

| active区間 | frame | 録画経過 | sequence | 件数 |
|---|---:|---:|---:|---:|
| 1 | 372～374 | 12.390～12.456秒 | 6280～6282 | 3 |
| 2 | 378～380 | 12.591～12.656秒 | 6286～6288 | 3 |
| 3 | 383～384 | 12.757～12.790秒 | 6291～6292 | 2 |

フレーム周期との境界により3区間目はCSV上2 sampleだが、3つのactive時間窓は存在する。active全8 sequenceは両PCのintent、command、statusで完全一致している。

ハンコンPC bagにおける配送遅延は次のとおりだった。

| 経路 | 中央値 | 最大 |
|---|---:|---:|
| intent→command | 0.001 ms | 8.716 ms |
| command→status | 0.584 ms | 0.780 ms |

ハンコンPC側の録画窓ではrelay診断650件中、forwarded 637件、rejected 13件だった。見送り理由はすべて`receiver_challenge_already_used`で、active sequence 8件は全件forwardされた。

## 録画前faultと終了状態

bag全体には録画開始約16秒前の`invalid_request:unknown_receiver_token`が2件ある。

| 時刻 | sequence | adapter動作 |
|---|---:|---|
| 14:32:19.770 JST | 5418 | `action=stop`、安全拒否 |
| 14:32:19.889 JST | 5421 | `action=stop`、安全拒否 |

これらは未知challenge tokenをhardware安全ゲートが拒否した結果で、カメラ録画開始14:32:36.125より前であり、走行中の物理出力には影響していない。録画窓内のfaultは0件だった。bag最後は14:34:26.175 JST、sequence 6731、`action=stop`、`output_active=false`、適用値0、`reason=shutdown`、`fault=false`だった。

## 標準解析FAILの解釈

`gate_regression.csv`では安定採用率99.71%だが、接近中の最大`abs(vz)`が0.2793 m/sとなりFAILになった。静止録画向けの距離安定性基準へ真の接近速度を入力したためであり、本試験では参考値とする。実走行の採否は実ODOM、TTC、配送、adapter status、安全停止を根拠に判断した。

## 体感確認と次の判断

2026-10-06に実施者から「3回連続の振動を感じ、その後も不要な振動はなかった」と報告を受けた。これにより、WARNINGの3連通知、物理出力停止、操作者による識別の全項目を確認できた。

次は条件を広げず、同じ正面直進条件でhardwareをあと2回実施し、合計3試行の再現性を確認する。r02・r03では初期距離を校正範囲内の1.30～1.35 mに修正し、可能なら`/cmd_vel`も0.25 m/s以下へ抑える。遮蔽、旋回、速度引き上げ、強度変更は再現性確認後に別段階で判断する。

## 成果物

- 標準解析: `phase5_v12_live_kobuki_hardware_r01_analysis/`
- カメラ集計: `phase5_v12_live_kobuki_hardware_r01_camera_summary.json`
- Kobuki PC bag集計: `phase5_v12_live_kobuki_hardware_kobuki_r01_bag_summary.json`
- Kobuki PC録画窓イベント: `phase5_v12_live_kobuki_hardware_kobuki_r01_recording_window_events.csv`
- ハンコンPC bag集計: `phase5_v12_live_kobuki_hardware_hsr_r01_bag_summary.json`
- ハンコンPC録画窓イベント: `phase5_v12_live_kobuki_hardware_hsr_r01_recording_window_events.csv`
- 無加工画像: `report_assets/phase5_v12_live_hardware_*.png`

元の`.tar.xz`および動画は大容量のためGit管理対象外とする。
