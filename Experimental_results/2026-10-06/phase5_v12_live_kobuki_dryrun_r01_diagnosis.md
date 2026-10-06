# Phase 5 v12 実Kobuki走行 dry-run r01 診断

## 結論

**統合試験判定: PASS（hardware試験へ進行可）**

実Kobukiの`/odom`を用いた低速直進でTTC WARNINGが成立し、active通知8件が`intent → relay command → dry_run status`へ欠落なく到達した。両PCのbagでsequenceは完全一致し、adapter faultは0件、全statusは`output_mode=dry_run`、active時の適用値は0.05だった。

Kobukiは最高0.183 m/sで約0.534 m前進し、カメラ推定距離約0.85 mで停止した。計画上限0.25 m/sおよび停止距離0.80 mを超えて接近していない。したがって、同じ配置と速度上限を維持し、手順書どおり低強度hardware試験を1回行える。

標準解析器の表示は`FAIL`だが、その理由は動的接近による最大視覚速度0.241 m/sを静的な観測安定性条件が外れ値として扱ったためである。録画完全性、実効FPS、WARNING判定、配送、adapter動作の失敗ではない。今回の統合試験判定とは分けて扱う。

## 入力と来歴

| ファイル | SHA-256 |
|---|---|
| `phase5_v12_live_kobuki_dryrun_r01_20261006_135700_661.tar.xz` | `37d62dc8ea047b9a3bc352b7aa47505b9f39f1620020e898a2fe1141341449a7` |
| `K_rosgub_phase5_v12_live_kobuki_dryrun_kobuki_r01.tar.xz` | `b9bf0512232d86efc6b938a37a91aea0e4853910a8064136884121795c5f5ca9` |
| `H_rosbug_phase5_v12_live_kobuki_dryrun_hsr_r01.tar.xz` | `0eb7ba4574e4f25e8a6315e6cf97bcb3639ee115f956b1d521f08c3a023ad329` |

- カメラ録画開始: 2026-10-06 13:57:00.661 JST
- 録画時間: 約19.13秒
- config: `src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`
- ODOM: 実機`/odom`
- adapter: `dry_run`、上限0.05
- bag集計窓はセッション名の開始時刻とカメラCSVの継続時間から定めた。

## 判定一覧

| 評価項目 | 結果 | 判定 |
|---|---:|---:|
| カメラ録画完全性 | raw/BEV/detection各572 frame | PASS |
| 実効FPS | 29.891 fps、30 fps±1%内 | PASS |
| 青箱raw検出 | 572/572、100% | PASS |
| 有効測定・追跡 | 306/572、53.50% | 注意 |
| 実ODOM | 両bag各960件、正方向移動190件 | PASS |
| 最大実速度 | 0.183 m/s | PASS |
| 最大絶対角速度 | 0.097 rad/s、走行中中央値0.016 rad/s | PASS |
| 最大移動量 | 約0.534 m | 注意（計画約0.50 mより3.4 cm大） |
| 最終カメラ推定距離 | 約0.853 m | PASS |
| 最小有限TTC | 4.217秒 | PASS |
| WARNING | 28 frame、約0.98秒 | PASS |
| active intent→command→status | 8→8→8、欠落0 | PASS |
| adapter mode | status 571件すべて`dry_run` | PASS |
| active適用値 | 8件すべて0.05 | PASS |
| adapter fault | 0件 | PASS |
| 最終status | inactive、`fault=false` | PASS |

## 走行結果

両bagで実ODOMと`/cmd_vel`は一致して記録された。

| 指標 | 結果 |
|---|---:|
| `/odom`最高速度 | 0.1834 m/s |
| `/odom`走行中中央値 | 0.1706 m/s |
| `/odom`走行中p95 | 0.1770 m/s |
| `/cmd_vel`最大値 | 0.2184 m/s |
| `/cmd_vel`中央値 | 0.2034 m/s |
| 正方向走行区間 | 13:57:07.906～13:57:11.849 JST |
| ODOM正味移動量 | 0.5342 m |
| ODOM積算移動量 | 0.5344 m |

実速度は目標目安0.18～0.22 m/sよりわずかに低いが、上限0.25 m/sを守りながらWARNINGを発生できたため、再録画は不要である。走行方向の横ぶれは小さく、`/cmd_vel.angular.z`は全86件で0だった。

青箱の初期raw距離は約1.54 mで、設定の校正有効上限1.35 mおよび検出領域上限1.40 mより遠かった。そのため、前半264 frameは主に`calibration_range_gate`で測定不採用となった。接近後は追跡が成立し、走行中の有効追跡は68 frame、距離は約1.334 mから0.867 mへ減少した。停止後の最終追跡距離は約0.853 mだった。

## TTCとFFB通知

WARNINGはframe 309～336、録画経過10.285～11.263秒で成立した。最小TTCはframe 315の4.217秒だった。WARNING activeは3つの時間窓に分かれ、triple cadenceとして送信された。

| active区間 | frame | 録画経過 | sequence | 件数 |
|---|---:|---:|---:|---:|
| 1 | 309～311 | 10.285～10.350秒 | 12496～12498 | 3 |
| 2 | 314～316 | 10.477～10.541秒 | 12501～12503 | 3 |
| 3 | 319～320 | 10.653～10.684秒 | 12506～12507 | 2 |

フレーム周期の揺れにより3区間目はCSV上2 sampleだが、3つのactive時間窓は存在する。active全8 sequenceは両PCで同一で、欠落はない。

ハンコンPC bagにおける配送遅延は次のとおりだった。

| 経路 | 中央値 | 最大 |
|---|---:|---:|
| intent→command | 0.318 ms | 1.250 ms |
| command→status | 0.306 ms | 0.605 ms |

ハンコンPC側のrelay診断は録画区間572件中、forwarded 571件、rejected 1件だった。唯一の見送り理由はinactive通知の`receiver_challenge_already_used`であり、active通知には影響していない。Kobuki PC側は終了境界のinactive 1件が時間窓外となったため571件だが、active sequenceは両PCで完全一致している。

## 標準解析FAILの解釈

`gate_regression.csv`では、raw_ground_distanceの安定採用率は100%だが最大`abs(vz)`が0.2412 m/sのためFAILになった。この評価は静止・外乱録画で距離推定の揺れを検査する用途で、青箱へ実際に接近する本試験では真の距離変化も大きな`vz`になる。したがって、今回のFAILを観測ゲート故障とは判定しない。

ただし、初期配置が校正範囲外だった点は改善する。hardware試験では、青箱をカメラから約1.30～1.35 mへ置き、開始時点から有効測定・追跡が成立することをGUIで確認する。

## hardware試験へ進む条件

本記録はdry-run進行条件を満たす。次は次の条件を変更せず、hardwareを1回だけ実施する。

1. 青箱初期距離を約1.30～1.35 m、停止線を0.80 mとする。
2. 実速度上限0.25 m/sを維持する。0.18 m/sへ届かなくても強引に速度を上げない。
3. adapterはchallenge freshness、安全ゲート有効、`max_magnitude=0.05`とする。
4. 3連FFBを感じた時点、または停止線のうち早い方で停止する。
5. カメラ・両PC bag・adapterログを再度保存する。
6. 初回hardwareでは強度変更、遮蔽、旋回、再試行を行わない。

## 成果物

- 標準解析: `phase5_v12_live_kobuki_dryrun_r01_analysis/`
- カメラ集計: `phase5_v12_live_kobuki_dryrun_r01_camera_summary.json`
- Kobuki PC bag集計: `phase5_v12_live_kobuki_dryrun_kobuki_r01_bag_summary.json`
- Kobuki PC録画窓イベント: `phase5_v12_live_kobuki_dryrun_kobuki_r01_recording_window_events.csv`
- ハンコンPC bag集計: `phase5_v12_live_kobuki_dryrun_hsr_r01_bag_summary.json`
- ハンコンPC録画窓イベント: `phase5_v12_live_kobuki_dryrun_hsr_r01_recording_window_events.csv`
- 無加工画像: `report_assets/phase5_v12_live_*.png`

元の`.tar.xz`および動画は大容量のためGit管理対象外とする。
