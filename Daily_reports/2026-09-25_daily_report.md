# 2026年9月25日 日報

## 本日の到達点

9月24日の録画TTC hardware再生で判明した「WARNINGとUNKNOWNが体感上区別しにくい」問題から作業を開始し、UNKNOWNを最大0.10秒の単発通知へ分離した。合成riskと9月8日の実録画を使ったROS 2 `dry_run`で、WARNINGは3連、UNKNOWNは単発、fault 0、最終inactiveとなることを確認した。

その後、実カメラ・青箱・専用模擬ODOM・PC間challengeを使ってv8、v9、v10の順に試験した。v8ではUNKNOWN単発そのものは成立したが、カメラGUI内のchallenge callback停滞により古いtokenが送られた。固定回復待ちを追加したv9でもcallback前の滞留は解消できなかったため、challenge受信と最終command送信をカメラGUIから独立したrelayプロセスへ分離した。

v10 relay試験では録画区間のadapter faultを0件にでき、WARNINGとUNKNOWNをadapterまで配送できた。遮蔽操作も0.25 m/s送信中に成立していた。一方、active intent 16件中1件がfail-closedで見送られ、UNKNOWNが短い測定復帰により4区間へ再発火した。これを受け、追加録画なしでv11 reliability実装まで進めた。

v11では、青箱の有効測定が0.5秒連続するまでUNKNOWNを再armしない条件、challenge流が1.0秒安定するまでrelay転送を開始しない条件、relay見送り理由の診断topic、一人試験用の停止→0.25 m/s→停止ODOMシナリオを実装した。過去v10録画の再入力では、UNKNOWN activeを9フレーム・4区間から1フレーム・1区間へ抑制できた。全206件の単体・回帰テストはPASSした。

本日はハンコンへの新しい物理出力、およびKobuki実走行は行っていない。次の実機作業はv11のPC間`dry_run`再試験である。

## 使用環境と安全条件

| 項目 | 内容 |
|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5`：360度カメラ、`bird_eye.py`、relay、模擬ODOM |
| ハンコン接続PC | `hsr-Alienware-m16-R2`：challenge発行、FFB adapter、status記録 |
| ROSドメイン | 両PCとも`88` |
| adapter | 実カメラ統合試験はすべて`dry_run` |
| 模擬ODOM | `/phase5/mock_odom`。実機`/odom`とは分離 |
| FFB上限 | adapter適用上限0.05、有限出力、watchdog 0.10秒 |
| Git対象外 | 元録画archiveと動画。解析CSV・JSON・Markdown・無編集PNGのみGit管理 |

## 1. UNKNOWN単発通知の実装

従来はWARNINGとUNKNOWNの両方に同じ3連cadenceが適用され、adapter上限により体感強度も同じ0.05となっていた。`CollisionFfbCadenceController`を変更し、WARNING・CRITICALは従来の3連、UNKNOWNは最大0.10秒の単発とした。

| 入力 | activeパターン | 結果 |
|---|---|---:|
| WARNING 15フレーム | `111001110011100` | 3連、active 9件 |
| UNKNOWN 15フレーム | `111000000000000` | 単発、active 3件 |

隔離ROS 2 `dry_run`ではcommand/status 46/46、active 12/12、fault 0だった。9月8日の0.20 m/s接近録画を新仕様で再生した結果もcommand/status 630/630、active 13/13、fault 0となった。WARNINGは9 activeの3連、UNKNOWNは4 activeの短い通知として区別された。

詳細は[UNKNOWN単発FFB実装記録](../Experimental_results/2026-09-25/unknown_single_pulse_implementation.md)を参照する。

## 2. v8 実カメラ・PC間dry-run

### WARNING経路

青箱を正面約1.0 mに置き、専用模擬ODOMを0.25 m/sで送信した。青箱検出からTTC WARNING、3連FFB command、PC間challenge、adapter statusまで同一sequenceで接続した。

| 指標 | 結果 |
|---|---:|
| 録画フレーム | 841、動画3種すべて完全 |
| 青箱検出・観測採用 | 841/841 |
| active command/status | 11/11 |
| adapter fault | 0 |
| 実効FPS | 29.341 FPS |

FFB機能経路はPASSした。標準解析のFAILは30 FPS±1%基準だけで、検知・TTC・FFB配送には影響していない。

### UNKNOWN経路

青箱を遮蔽し、`WARNING_HOLD → UNKNOWN`を発生させた。UNKNOWN activeは3フレーム、約0.101秒で終了し、その後22フレームは`unknown_pulse_complete`として再発火しなかった。UNKNOWN sequence 3件は全件adapterへ到達した。

一方、録画区間でadapter faultが24件発生した。内訳は`unknown_receiver_token` 23件、`expired_receiver_token` 1件で、WARNING系active 15件のうちadapterで適用できたのは9件だった。adapterは不正tokenを拒否して出力停止しておりfail-safeだが、PC間配送としてはFAILと判定した。

カメラ側でchallenge age 3.24 msと記録したcommandでも、ハンコン接続PCのbagではchallenge発行から約167 ms経過していた。callbackが実行される前のキュー滞留時間をカメラ側ageで観測できないことが原因と判断した。

## 3. v9 challenge回復待ちと限界

送信済みtokenの再利用禁止、callback gap検出、sender age超過時の0.10秒回復待ちを追加した。単体・回帰185件はPASSし、v9実験でもtoken単回使用と有限cadenceの非再発火は成立した。

しかし実カメラ試験ではcallback gapが最大273 msあり、固定0.10秒待った後も古いtokenが残った。録画区間のadapter faultは21件、active command 5件中適用は3件で、総合FAILだった。受信側の期限を緩和せず、カメラGUIからchallenge処理を分離する方針へ変更した。

また、この試験は0.25 m/s送信終了後に遮蔽が始まったためUNKNOWNが発生していない。通信問題と操作タイミングを分離して扱った。

## 4. v10 challenge relayの分離

`bird_eye.py`は同一PC内の`/collision/ffb_intent`へ危険度と有限cadenceをpublishし、別プロセスの`collision_ffb_relay.py`が最新challenge、intent age、token未使用を確認して最終`/collision/ffb_command`へ転送する構成へ変更した。`run_field_experiment.py`からrelayを自動起動・停止できるようにした。

```text
bird_eye.py
  └─ /collision/ffb_intent
       └─ collision_ffb_relay.py
            ├─ intent age <= 0.10 s
            ├─ challenge callback age <= 0.06 s
            └─ token単回使用
                 └─ /collision/ffb_command
                      └─ ハンコンPC adapter
```

実装後は全197件の回帰テストとワンコマンド`--dry-run`がPASSした。

## 5. v10 実カメラ・PC間relay試験

一人で遮蔽を行った試験を、カメラ録画、Kobuki PC bag、ハンコン接続PC bagの3入力から解析した。

| 指標 | 結果 |
|---|---:|
| 録画フレーム / 実効FPS | 2297 / 29.870 FPS |
| 青箱検出 | 2048/2297 |
| 1回目0.25 m/s | 21.961～28.361秒 |
| WARNING | 22.034～28.430秒 |
| 2回目0.25 m/s | 52.325～58.724秒 |
| UNKNOWN | 52.925～53.630秒 |
| 完全遮蔽画像 | 約56.63秒。0.25 m/s送信中 |
| active intent / command / status | 16 / 15 / 15 |
| 録画区間adapter fault | 0 |
| active intent→command | 中央0.648 ms、最大6.334 ms |

遮蔽は送信時間内に成立しており、操作失敗ではなかった。adapterへ到達したactive 15件はすべて`dry_run`、`fault=false`、適用0.05で、WARNING 6件とUNKNOWN 9件を確認した。

active intent `sequence=3676`だけは最新challengeを確保できず、relayがfail-closedで見送った。録画開始前にはinactive commandのtoken faultが34件あったが、録画区間では0件だった。起動直後のready判定が必要と判断した。

UNKNOWN activeは9フレームが4区間に分かれた。短い有効測定が入るたびにUNKNOWNが再armされたため、単発通知の意味を安定させるには連続した測定復帰を要求する必要があった。

詳細は[v10 relay診断](../Experimental_results/2026-09-25/phase5_v10_relay_dryrun_r01_diagnosis.md)を参照する。

## 6. v11 reliability実装

v10結果に対し、追加録画なしで次の4項目を実装した。

### 6.1 UNKNOWNの連続有効測定による再arm

- UNKNOWN通知後は`measurement_valid=true`が0.5秒連続するまで再armしない。
- 途中で無効測定が1回でも入ると連続時間をリセットする。
- v10実録画の`detections.csv`を再入力した結果、UNKNOWN activeはv10の9フレーム・4区間から、v11では1フレーム・1区間へ減少した。

### 6.2 relay起動安定ゲート

- challengeを1.0秒連続受信するまでintentを転送しない。
- challenge間隔が期限0.06秒を超えた場合、またはreceiver sessionが変化した場合は安定時間をリセットする。
- 安定前と受信断後は`receiver_challenge_stream_not_stable`としてfail-closedで見送る。

### 6.3 relay診断topic

全intentの処理結果を`/collision/ffb_relay_diagnostics`へJSONでpublishする。転送・見送り、理由、intent/challenge age、challenge安定継続時間、受信件数、session/tokenを記録する。bag解析スクリプトにも診断JSONの復号と理由集計を追加した。

### 6.4 一人試験用ODOMシナリオ

`publish_mock_odom_scenario.py`を追加した。既定条件は停止5秒→0.25 m/sで15秒→停止5秒、30 Hzである。各publishの予定時刻、実際のmonotonic時刻、UTC時刻、ROS stamp、速度、publish成否をCSVへ逐次flushする。

実機`/odom`へのpublishはコード上で拒否し、`/phase5/`配下だけを許可する。終了時と割込み時には停止値を送る。長い15秒の移動区間により、一人でも端末から青箱へ移動して遮蔽操作できるようにした。

## 7. 検証結果

| 検証 | 結果 |
|---|---:|
| Python構文確認 | PASS |
| Git whitespace確認 | PASS |
| ROS/FFB workspaceをsourceした全テスト | **206/206 PASS** |
| v11 config preflight | PASS |
| v11ワンコマンド起動`--dry-run` | PASS |
| ODOMシナリオ短縮smoke test | PASS |
| v10 bag解析の後方互換 | PASS |
| v10設定ファイル | 変更なし |

ODOM smoke testでは停止、0.25 m/s、停止の3 phaseが順にpublishされ、各実送信時刻がCSVへ保存された。これは専用mock topicを使ったソフトウェア確認であり、Kobuki実機やG923への物理出力は行っていない。

詳細は[v11実装記録](../Experimental_results/2026-09-25/phase5_v11_reliability_implementation.md)を参照する。

## 本日の判断と残課題

- WARNING 3連と継続UNKNOWN単発の区別は成立した。
- カメラGUI内でchallenge callbackを処理する設計は、callback前の滞留を正しく評価できないため採用しない。
- 独立relayにより録画区間のtoken faultは0件になったが、起動安定前の見送りと理由記録が必要だったためv11へ進めた。
- UNKNOWNの短い測定復帰による再発火は、0.5秒の連続有効測定gateと過去録画再生で抑制できた。
- ソフトウェア実装と回帰は完了したが、v11の実PC間`dry_run`は未実施である。
- v11 `dry_run`がPASSするまではhardware出力へ進まない。
- 実走行試験は、停止状態のPC間dry-runと低強度hardware統合がPASSした後の別段階とする。

## 成果物

- [2026-09-25実験結果](../Experimental_results/2026-09-25/)
- [v10 relay診断](../Experimental_results/2026-09-25/phase5_v10_relay_dryrun_r01_diagnosis.md)
- [v11実装記録](../Experimental_results/2026-09-25/phase5_v11_reliability_implementation.md)
- [v11一人用dry-run試験手順](../Experimental_results/2026-09-25/phase5_v11_reliability_dryrun_procedure.md)
- [成果報告用画像・グラフ](../Experimental_results/2026-09-25/report_assets/README.md)
- [v11設定](../src/bird_eye_config_ttc_v11_ffb_reliability_20260925.json)
- [一人用ODOMシナリオ](../src/publish_mock_odom_scenario.py)

成果報告用として、v8 WARNING、v8 UNKNOWN、v9 WARNING・遮蔽、v10 WARNING・UNKNOWN・遮蔽の生カメラ画像を保存した。画像は元映像と同じ1280×720で、切り抜き、リサイズ、注釈、色補正をしていない。元の大容量録画archiveと動画はGitへ追加していない。

## 次回作業

1. 両PCを最新Gitへ揃え、両方でROS domain 88を確認する。
2. ハンコン接続PCのadapterを`dry_run`、challenge方式、上限0.05で起動する。
3. v11設定でカメラとrelayをワンコマンド起動し、`/collision/ffb_relay_diagnostics`を両PCのbagへ記録する。
4. 一人用ODOMシナリオで停止5秒→0.25 m/s 15秒→停止5秒を送信する。
5. 移動区間中に短い測定復帰を含む遮蔽を行い、UNKNOWNが0.5秒未満の復帰では再発火しないことを確認する。
6. adapter fault 0、安定後のactive intent/command/status対応、最終inactive、ODOM CSV全行成功を満たした場合のみ低強度hardware試験を検討する。

詳細な実行コマンドと合格条件は[v11試験手順](../Experimental_results/2026-09-25/phase5_v11_reliability_dryrun_procedure.md)に記載した。

## Git

本日途中までのコミットは`e997030`（UNKNOWNとWARNINGの切り分け）、`f86e197`（実験0925v1）、`fbd3bda`（実験0925v2）である。本日後半のv10解析、無編集生画像、v11 reliability実装、テスト、手順書、本日報を追加コミットとして整理する。録画archive、AVI、作業用一時ファイルは含めない。
