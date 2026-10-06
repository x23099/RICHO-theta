# Phase 5 v12 実Kobuki走行 hardware r02 診断

## 結論

**FFB経路判定: PASS**

**WARNING・3連FFB再現確認: PASS（r03へ進行可）**

**距離推定精度: 未確定、FPS性能: 基準外**

実Kobuki走行でTTC WARNINGが成立し、active通知11件が`intent → relay command → hardware status`へ欠落なく到達した。active statusはすべて`hardware`、`output_active=true`、適用強度0.05、`fault=false`だった。最後のactiveから36.5 ms後に出力停止し、録画区間内faultは0件だった。

実施者は3回の振動を体感し、物理停止線は越えていないと報告した。また、実際の初期距離は1.30 mだったと補足した。前回の「初期配置が約1.51 m」「停止基準未達」という判断はカメラ推定だけに基づいていたため訂正する。物理配置・停止線の確認とFFB経路の記録を合わせ、r03へ進行可能とする。

一方、初期カメラ推定約1.51 mは実測1.30 mより約0.21 m遠く、最終推定0.758 mも物理停止位置との対応が確定していない。床面反射の影響は実施者の観察に基づく原因候補であり、反射による輪郭・接地点の変化はまだ解析で確認していない。ODOM移動量約0.638 mも、初期距離と停止線の実測との整合を未確認のまま残す。距離精度のPASSとはしない。

実速度は最大0.213 m/sで上限0.25 m/s以下、`/cmd_vel`最大値も0.2508 m/sでほぼ上限内だった。r03の停止判断は実測した物理停止線を優先し、約0.90 mを早めの停止目標とする。

## 入力と来歴

| ファイル | SHA-256 |
|---|---|
| `rokuga_phase5_v12_live_kobuki_hardware_r02_20261006_150430_183.tar.xz` | `815da6c5da19e7bd39b4c6f51e666b52165bd2d69baaa5f631f49115bc6c79c0` |
| `K_rosbug_phase5_v12_live_kobuki_hardware_kobuki_r02.tar.xz` | `0e451c0b10a179daa570616065aaa8ad882041d78ff257550c9465e00c5aa7b8` |
| `H_rosbug_phase5_v12_live_kobuki_hardware_hsr_r02.tar.xz` | `b5f6bcae2fd7f0620d27257caa6245aba9fa2e1132f316f053cbd5489f748b96` |

- カメラ録画開始: 2026-10-06 15:04:30.183 JST
- 録画時間: 約16.16秒
- config: `src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`
- ODOM: 実機`/odom`
- adapter: `hardware`、challenge freshness、安全ゲート有効、上限0.05

## 判定一覧

| 評価項目 | 結果 | 判定 |
|---|---:|---:|
| カメラ録画完全性 | raw/BEV/detection各479 frame | PASS |
| 実効FPS | 29.631 fps | 注意（30 fps±1%を0.069 fps下回る） |
| 青箱raw検出 | 479/479、100% | PASS |
| 有効測定・追跡 | 270/479、56.37% | 注意 |
| 実ODOM | 両bag各811件、正方向移動206件 | PASS |
| 最大実速度 | 0.213 m/s | PASS |
| 最大移動量 | 約0.638 m | 注意 |
| 初期実距離／カメラ推定 | 実施者実測1.30 m／約1.51 m | 精度未確定 |
| 最終カメラ推定距離 | 約0.758 m | 精度未確定 |
| 最小有限TTC | 3.518秒 | PASS |
| WARNING | 27 frame、約0.87秒 | PASS |
| active intent→command→status | 11→11→11、欠落0 | PASS |
| active物理出力 | 11件すべて適用値0.05 | PASS |
| 録画区間内adapter fault | 0件 | PASS |
| active終了後の停止 | 36.5 ms後に`output_active=false` | PASS |
| bag最終status | `shutdown`、出力0、`fault=false` | PASS |
| 3連FFBの体感 | 実施者が3回の振動を確認 | PASS |
| 物理停止線の超過 | 実施者が超過なしを確認 | PASS |

## 走行結果

| 指標 | 結果 |
|---|---:|
| `/odom`最高速度 | 0.2132 m/s |
| 走行中速度中央値 | 0.1578 m/s |
| 走行中速度p95 | 0.2026 m/s |
| `/cmd_vel`最大値 | 0.2508 m/s |
| `/cmd_vel`中央値 | 0.1968 m/s |
| 正方向走行区間 | 15:04:36.016～15:04:40.197 JST |
| ODOM正味移動量 | 0.6382 m |
| ODOM積算移動量 | 0.6384 m |

`/cmd_vel.angular.z`は全91件で0だった。走行中ODOM角速度は中央値0.016 rad/s、p95 0.032 rad/sで、直進性はr01より安定していた。

青箱の初期raw推定距離は約1.51 mだった。推定値が校正有効上限1.35 mおよび検出領域上限1.40 mより遠いため、前半207 frameは主に`calibration_range_gate`で不採用となった。実際の初期距離は実施者報告で1.30 mであり、物理配置の範囲外とは判定しない。追跡成立後の推定距離は約1.349 mから0.742 mへ減少し、停止後は約0.758 mで安定した。

## TTCと物理FFB出力

WARNINGはframe 272～298、録画経過9.191～10.058秒で成立した。最小TTCは3.518秒だった。WARNING activeは3区間に分かれた。

| active区間 | frame | 録画経過 | sequence | 件数 |
|---|---:|---:|---:|---:|
| 1 | 272～275 | 9.191～9.290秒 | 1605～1608 | 4 |
| 2 | 277～279 | 9.358～9.424秒 | 1610～1612 | 3 |
| 3 | 282～285 | 9.523～9.623秒 | 1615～1618 | 4 |

フレーム周期との境界によりactive sample数は4+3+4だが、通知時間窓は3群である。11 sequenceすべてが両PCのintent、command、statusで一致した。

ハンコンPC bagにおける配送遅延は次のとおりだった。

| 経路 | 中央値 | 最大 |
|---|---:|---:|
| intent→command | 0.504 ms | 1.381 ms |
| command→status | 0.546 ms | 0.900 ms |

relay診断478件はforwarded 476件、rejected 2件だった。見送りはinactiveの`receiver_challenge_already_used`だけで、active通知への影響はない。

## 録画前faultと終了状態

bag全体には録画開始約12秒前の`invalid_request:unknown_receiver_token`が1件ある。sequence 965を`action=stop`で安全拒否したもので、録画区間中のfaultは0件だった。

Kobuki PC bagの最後は15:05:12.666 JST、sequence 2242、`action=stop`、`output_active=false`、適用値0、`reason=shutdown`、`fault=false`だった。

## 標準解析FAILの解釈

標準解析のFAIL理由は次の2点だった。

1. 実効29.631 fpsが30 fps±1%の下限29.700 fpsをわずかに下回った。
2. 実接近による最大`abs(vz)` 0.2619 m/sを静的距離安定性検査が外れ値扱いした。

映像3種とCSVは479 frameで一致し、active配送にも欠落はないため、FFB経路判定には影響しない。FPSはr03でも監視する。

## r03の条件と記録

1. 初期距離は実測1.30～1.35 mとし、同じ青箱・床面・設定を使用する。
2. 距離推定にずれがあるため、FFBまたは物理停止目標の早い方で停止する。目標は0.90 m、限界停止線は0.80 mとする。
3. 初期と停止後の実測距離をメモし、同時点のカメラ推定距離と比較する。カメラ位置から青箱前面まで測定する。
4. 3連体感、停止後の不要振動、操縦・停止への影響をメモする。
5. 強度0.05、実速度上限0.25 m/s、直進条件を維持する。

r03は0.90 mの早めの停止目標を追加するため、停止位置をr01・r02と同条件の精度評価として扱わない。WARNING配送と体感の再現性、および距離推定と実測の差を確認する試行とする。

## 成果物

- 標準解析: `phase5_v12_live_kobuki_hardware_r02_analysis/`
- カメラ集計: `phase5_v12_live_kobuki_hardware_r02_camera_summary.json`
- Kobuki PC bag集計: `phase5_v12_live_kobuki_hardware_kobuki_r02_bag_summary.json`
- Kobuki PC録画窓イベント: `phase5_v12_live_kobuki_hardware_kobuki_r02_recording_window_events.csv`
- ハンコンPC bag集計: `phase5_v12_live_kobuki_hardware_hsr_r02_bag_summary.json`
- ハンコンPC録画窓イベント: `phase5_v12_live_kobuki_hardware_hsr_r02_recording_window_events.csv`

元の`.tar.xz`および動画はGit管理対象外とする。
