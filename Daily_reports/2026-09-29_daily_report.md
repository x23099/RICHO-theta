# 2026年9月29日 日報

## 本日の到達点

本日は、9月25日に実装したv11 reliability構成を実PC間で評価し、そこで判明したchallenge間隔揺らぎと疑似ODOM publisher切替問題をv12で修正した。その後、v12の2PC `dry_run`、停止状態のWARNING実機FFB、停止状態のUNKNOWN実機FFBまで順に完了した。

最終的に、実カメラの青箱認識からTTC判定、`intent`、独立relay、challenge認証、`command`、hardware adapter、G923までの経路で、WARNINGの3連振動とUNKNOWNの単発振動を体感・両PC bag・カメラCSVで確認した。全hardware試験でactive欠落0、録画時間内fault 0、最終inactiveだった。

Kobukiの実走行は行っていない。明日は実ODOMを使う低速直進を、最初に`dry_run`、合格後に上限0.05のhardwareという二段階で行う。

## 使用環境と安全条件

| 項目 | 内容 |
|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5`：360度カメラ、`bird_eye.py`、relay、疑似ODOMまたは実`/odom` |
| ハンコン接続PC | `hsr-Alienware-m16-R2`：G923、challenge発行、FFB adapter、status記録 |
| ROS domain | 両PCとも`88` |
| v12設定 | `src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json` |
| challenge | command鮮度0.06秒、stream断判定0.20秒、起動安定1.0秒 |
| FFB | WARNINGは3連、UNKNOWNは最大0.10秒の単発、adapter上限0.05 |
| 本日のKobuki | 全試験で停止。疑似速度は専用`/phase5/mock_odom`だけへ送信 |
| 生録画 | Git管理外。解析CSV、JSON、Markdown、無加工PNGを保存 |

## 1. v11実PC間dry-runと原因診断

v11の実カメラ・遮蔽・2PC dry-runでは、カメラ側のUNKNOWN再armは期待どおり機能した一方、通信経路に次の問題が残った。

| 指標 | v11結果 |
|---|---:|
| active intent | 27 |
| active command | 12 |
| active status | 11 |
| active配送率 | 40.7% |
| 録画中`receiver_challenge_stream_not_stable` | 567件 |
| 両bagの0.25 m/s | 0件 |

challenge受信間隔が一時的に60～129 msへ伸びただけでstream安定時間が0へ戻り、その後1秒間のactive intentまで見送る設計になっていた。また、preflight用の速度0 publisherからシナリオpublisherへ切り替えたため、両bagは0.25 m/s区間を記録できなかった。

詳細は[v11診断](../Experimental_results/2026-09-29/phase5_v11_reliability_dryrun_r01_diagnosis.md)を参照する。

## 2. v12 reliability実装

v11の安全条件を緩めず、challenge単体の鮮度とstream継続性を分離した。

- `challenge_max_age_sec=0.06`は維持し、古いtokenを使うcommandは引き続きfail-closedとした。
- `challenge_stream_timeout_sec=0.20`を追加し、200 ms未満の一時的揺らぎでは1秒の起動安定状態を失わないようにした。
- receiver session変更または200 ms超の断では、従来どおり1秒の再安定化を要求する。
- relay診断へ直前challenge間隔、stream timeout、restart countを追加した。
- 疑似ODOM送信器へ`--wait-for-enter`を追加し、同じpublisherから速度0を送りながら待機し、そのまま停止→0.25 m/s→停止へ移行できるようにした。

v11 bagのオフライン再入力では、active許可が12/27から26/27へ改善し、UNKNOWNイベント群はすべて残った。1件の見送りは個別challengeが60 msを超えた正しいfail-closedだった。

| 検証 | 結果 |
|---|---:|
| 関連テスト | 48/48 PASS |
| 実装時の全単体・回帰テスト | **211/211 PASS** |
| 本日終了時の全回帰再確認 | **220/220 PASS** |
| v12 preflight・ワンコマンドdry-run | PASS |
| 同一publisher ODOM smoke test | PASS |

詳細は[v12実装記録](../Experimental_results/2026-09-29/phase5_v12_reliability_implementation.md)を参照する。

## 3. v12 2PC dry-run

実カメラ、青箱遮蔽、専用疑似ODOM、独立relay、ハンコンPCの`dry_run` adapterを同時に動かした。

| 指標 | 結果 |
|---|---:|
| 録画frame / 実効FPS | 1,045 / 29.950 |
| raw/BEV/detection | 1,045/1,045/1,045、完全 |
| 両bagの0.25 m/s | 各450件 |
| active intent / command / status | 23 / 23 / 23 |
| WARNING active | 18件、2回の3連cadence |
| UNKNOWN active | 5件、2回の単発イベント |
| active欠落 | 0 |
| 録画中stream不安定見送り | 0 |
| 録画中adapter fault | 0 |
| 最終status | inactive、shutdown、`fault=false` |

短い青色復帰ではUNKNOWNを再armせず、有効測定が0.5秒以上連続した後だけ2回目のUNKNOWNを許可した。challenge間隔が60 msをわずかに超えた場面でもstream restartは増えず、v12の分離設計が実PC間で成立した。

詳細は[v12 dry-run診断](../Experimental_results/2026-09-29/phase5_v12_reliability_dryrun_r01_diagnosis.md)を参照する。

## 4. WARNINGの実ハードウェア試験

Kobukiを停止させ、正面約1.087 mの青箱と疑似ODOM 0.25 m/sを用いてG923へ出力した。利用者は明確な3連振動を感じた。

| 指標 | 結果 |
|---|---:|
| 録画frame / 実効FPS | 1,258 / 28.670 |
| WARNING frame | 286 |
| active intent / command / hardware status | 9 / 9 / 9 |
| active群 | 3件×3群、3連振動 |
| 要求 / 適用強度 | 0.25 / 0.05 |
| active欠落 / 録画中fault | 0 / 0 |
| 最終status | inactive、shutdown、`fault=false` |

汎用解析器は実効FPSが30 fps±1%外だったためFAILとしたが、FFB経路と録画完全性には欠落がなく、WARNING hardware試験としてはPASSと判断した。

詳細は[WARNING hardware診断](../Experimental_results/2026-09-29/phase5_v12_hardware_warning_r01_diagnosis.md)を参照する。

## 5. UNKNOWNの実ハードウェア試験

青箱を遮蔽し、WARNING hold終了後のUNKNOWN単発をG923で確認した。利用者の体感は、記録上の「WARNING 3連→UNKNOWN単発→復帰WARNING 3連」と一致した。

| 指標 | 結果 |
|---|---:|
| 録画frame / 実効FPS | 1,301 / 29.588 |
| WARNING / WARNING_HOLD / UNKNOWN | 269 / 34 / 61 frame |
| active intent / command / hardware status | 22 / 22 / 22 |
| WARNING active | 20件、2回の3連cadence |
| UNKNOWN active | 2件、1回の単発イベント |
| UNKNOWN要求 / 適用強度 | 0.15 / 0.05 |
| active欠落 / bag全体fault | 0 / 0 |
| 最終status | inactive、shutdown、`fault=false` |

UNKNOWN後には有効測定が4.238秒連続し、再arm条件0.5秒を満たした。ただし、2回目の遮蔽が0.25 m/s終了の約0.19秒前だったため、0.8秒のholdが切れる前に速度0へ移り、2回目のUNKNOWNは発生しなかった。v12 dry-runでは2回目UNKNOWNを確認済みであり、今回はUNKNOWNから実ハードウェアまでの単発経路をPASSとした。

汎用解析器のFAIL理由は実効29.588 fpsが30 fps±1%をわずかに外れたことだけである。前回hardware試験より改善したが、明日の実走行でもFPSを継続監視する。

詳細は[UNKNOWN hardware診断](../Experimental_results/2026-09-29/phase5_v12_hardware_unknown_r01_diagnosis.md)を参照する。

## 本日の判断と残課題

- v12でchallenge単体鮮度60 msとstream断200 msを分離し、一時的な受信揺らぎを1秒の配送停止へ拡大しない構成を確立した。
- 2PC dry-run、WARNING hardware、UNKNOWN hardwareの全試験でactive sequence欠落0、試験時間内fault 0、最終inactiveだった。
- WARNING 3連とUNKNOWN単発をG923で体感上区別できた。
- 停止状態でのカメラ→G923統合は完了と判断する。
- 実カメラ処理のFPSは試行により28.670～29.950で変動する。動的試験では録画と大容量転送を同時に行わず、30 fps基準とFFB経路を分けて評価する。
- 実Kobuki走行とG923物理出力の同時試験は未実施であり、明日は必ず実走行`dry_run`を先行させる。

## 成果物

- [2026-09-29実験結果](../Experimental_results/2026-09-29/)
- [v12実装記録](../Experimental_results/2026-09-29/phase5_v12_reliability_implementation.md)
- [v12 dry-run診断](../Experimental_results/2026-09-29/phase5_v12_reliability_dryrun_r01_diagnosis.md)
- [WARNING hardware診断](../Experimental_results/2026-09-29/phase5_v12_hardware_warning_r01_diagnosis.md)
- [UNKNOWN hardware診断](../Experimental_results/2026-09-29/phase5_v12_hardware_unknown_r01_diagnosis.md)
- [成果報告用無加工画像](../Experimental_results/2026-09-29/report_assets/README.md)
- [2026-09-30低速実走行手順](../Experimental_results/2026-09-30/phase5_v12_low_speed_live_kobuki_procedure.md)

成果報告用画像は元録画と同じ1280×720でPNG化し、切り抜き、注釈、合成、リサイズ、色・明るさ補正を行っていない。本日報では、v11の1回目UNKNOWN、v12 dry-runの1回目UNKNOWN、v12の有効測定復帰、hardware UNKNOWNの4点を代表資料とする。

## 明日の作業

1. 実走行空間、停止線、非常停止担当、G923固定、両PCのdomain 88を確認する。
2. 模擬ODOM publisherが0件で、実`/odom`がKobuki 1 publisherだけであることを確認する。
3. 車輪を浮かせた状態または十分な空走空間で、操縦入力、停止操作、ODOM符号を確認する。
4. 実ODOM・実カメラ・青箱を使い、adapter `dry_run`で約0.20 m/sの短い直進を1回行う。
5. active欠落0、fault 0、最終inactive、停止距離、FPSを確認する。
6. dry-runが合格した場合だけ、同じ配置・上限0.05でhardware試験を1回行う。
7. 異常振動、連続出力、通信断、停止線超過、0.25 m/s超過があれば即時停止し、hardware試験へ進まない。

詳細なコマンド、配置、停止条件、提出物は[明日の手順書](../Experimental_results/2026-09-30/phase5_v12_low_speed_live_kobuki_procedure.md)に記載した。

## Git

- `6584c67`: v11実験解析、v12 reliability実装、回帰試験、v12手順を記録。
- 本日後半のv12 dry-run、WARNING/UNKNOWN hardware解析、無加工画像、本日報、翌日手順を追加コミットとして整理し、`origin/main`への反映対象とした。
