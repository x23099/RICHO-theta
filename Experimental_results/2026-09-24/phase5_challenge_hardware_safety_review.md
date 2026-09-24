# Phase 5 challenge方式 hardware展開前安全レビュー（2026-09-24）

## 結論

**レビュー時判定: コード実装は条件付きGO、実機hardware試験はNO-GO。**

**実装後判定: 安全ゲートとfake backend試験はPASS。実機hardware試験は別途承認待ち。**

2026-09-24の2 PC dry-run r02では、受信側challenge、認識、TTC、3連FFB command、PC間通信、adapter statusまでが正常に接続された。時刻同期に依存せず、active 9 sequenceが両PCで一致し、全statusは`fault=false`、challenge age最大29.89 ms、commandからstatusまで最大0.682 msだった。

一方、現行`collision_ffb_node`は`freshness_mode=challenge`と`output_mode=hardware`の組合せを意図的に起動拒否する。この禁止を単純に削除してはならない。challenge方式専用の明示承認ゲートとhardware時の期限上限を追加し、fake backend試験を通した後に、停止状態・単発・低強度から実機確認する。

## レビュー対象

- `collision_ffb_node.py`: mode gate、challenge検証、watchdog、hardware呼出し
- `collision_ffb_challenge.py`: receiver monotonic clockによるsession/token期限検証
- `collision_ffb_policy.py`: source、sequence、状態、強度、watchdogのfail-closed処理
- `collision_ffb_backend.py`: G923 writer lock、有限effect、stop/erase/close、capability検査
- 2026-09-24 r02のカメラ録画、Kobuki PC bag、ハンコン接続PC bag

## dry-runで確認済みの根拠

| 項目 | r02結果 | 判定 |
|---|---:|---|
| challenge受信 | 1,566→3,095、3フレーム以上停止0件 | PASS |
| challenge age | p95 19.19 ms、最大29.89 ms | PASS |
| 送信側期限60 ms超過 | 0/897 | PASS |
| FFB publish | 897/897 | PASS |
| active sequence | 両PCで同じ9件 | PASS |
| adapter適用 | dry-run、0.25要求→0.05適用、fault 0件 | PASS |
| command→status | 最大0.682 ms | PASS |
| 終了状態 | inactive、`shutdown`、faultなし | PASS |

標準解析のFAILは実効FPS 29.286が30 fps±1%を外れたことだけで、challenge/FFB経路の失敗ではない。

## 現行安全機構

1. `output_mode`の既定値は`disabled`である。
2. hardwareは`hardware_armed=true`、安定した`/dev/input/by-id/*-event-joystick`を要求する。
3. 0.03超は`hardware_initial_test_passed=true`を要求し、hardware上限は0.05である。
4. policyの絶対上限は0.25であり、今回のadapter適用上限は0.05である。
5. effectは最大120 msの有限矩形波で、CLEAR、watchdog、終了時にstop/eraseする。
6. 最後の妥当な指令から100 msでwatchdogがSTOPする。
7. G923 writer lockにより主要FFB writerの多重起動を拒否する。
8. challengeは受信側のmonotonic clockで100 ms以内を検証し、別PCのwall clockを比較しない。
9. session不一致、未知token、期限切れtoken、不正source・sequence・状態・強度はSTOPへfail closedする。
10. device write失敗時はstopを再試行し、statusをfaultにする。

Linux force-feedback APIでは、effectの再生・停止・消去はアプリケーション側の責務であり、機器によって初期化時やeffect更新時の挙動が異なる。したがって有限effect、明示stop/erase、物理的に電源を切れる準備は継続して必須とする。

## hazardと対策

| hazard | 現行対策 | hardware解禁前の扱い |
|---|---|---|
| 古いPC間指令 | challenge token 100 ms、sequence検査 | challenge期限をhardware時100 ms以下へ固定 |
| command停止・通信断 | 100 ms watchdog | hardware時100 ms以下へ固定し単体試験 |
| adapter異常終了 | 最大120 msの有限effect | effect上限120 msを維持 |
| 誤ったhardware起動 | disabled既定、armed、初回試験gate | challenge＋hardware専用gateを追加 |
| 過大出力 | hardware上限0.05 | 0.05を維持し増加しない |
| 多重writer | process lock | 起動前に関連node停止とlock拒否を再確認 |
| token欠落・遅延 | commandを拒否してSTOP | faultとinactiveをfake backendで確認 |
| device抜去・write失敗 | stop再試行、fault | fake backend例外試験を維持 |
| プロセス停止後の残留力 | 有限effect、close時stop/erase | USB/電源を即時切断可能にする |
| 誤ってKobukiが走行 | adapterは速度topicをpublishしない | 初回試験はKobukiを停止し速度出力を無効化 |

ROS 2の`BEST_EFFORT + KEEP_LAST(1) + VOLATILE`は最新値を優先し、古い指令を永続化しない構成である。欠落そのものは起こり得るため、安全性は配送保証ではなくchallenge期限、watchdog、有限effectで確保する。

## 必須実装

現行の「challenge＋hardwareを常に拒否」を、次のすべてを要求する条件付きgateへ置き換える。

1. 新規parameter `challenge_hardware_armed`を追加し、既定`false`とする。
2. `freshness_mode=challenge`かつ`output_mode=hardware`では、同parameterが厳密に`true`でなければbackend生成前に起動拒否する。
3. この組合せでは`challenge_max_age_sec <= 0.100`を必須にする。
4. この組合せでは`watchdog_timeout_sec <= 0.100`を必須にする。
5. 既存の`hardware_armed`、`hardware_initial_test_passed`、`max_magnitude <= 0.05`、stable device path、120 ms effect上限は緩和しない。
6. 起動ログへ`freshness=challenge`と専用gateの状態を出す。
7. launchへ自動追加せず、手動の明示コマンドだけで有効化する。

parameter名は「試験済み」を意味する名前ではなく、起動ごとの意思確認を表す`challenge_hardware_armed`とする。dry-runの成功だけで物理試験まで完了したように見える名前を避ける。

## 必須自動テスト

1. 専用gateなしのchallenge＋hardwareはbackend生成前に起動失敗する。
2. 専用gateあり、0.03、期限100 ms以下ではfake backendを生成できる。
3. 0.05は既存`hardware_initial_test_passed=true`も同時に必要とする。
4. challenge ageまたはwatchdogが100 ms超なら起動失敗する。
5. 有効tokenでAPPLYし、要求0.25を0.05へclampする。
6. 未知session、未知token、期限切れtokenでSTOP、inactive、faultになる。
7. active後にchallenge発行例外が起きるとhardware stopが呼ばれる。
8. command停止100 msでhardware stopが1回だけ呼ばれる。
9. CLEARとnode終了でstop/closeが呼ばれる。
10. upload/write失敗でstopを再試行し、faultを報告する。
11. disabled/dry-run/従来clock hardwareの回帰を壊さない。

現行のchallenge、policy、backend純粋テストは本レビュー時点で56件PASSした。ROS node試験はこのPCのローカル`install`に`oit_interfaces`が未buildだったため実行しておらず、変更実装後に`colcon build`して必ず実施する。

## 実機確認へ進む条件

以下をすべて満たすまでhardwareでは起動しない。

1. 上記実装と自動テストが完了する。
2. `oit_interfaces`と`oit`をclean buildし、対象テストがPASSする。
3. 両PCのcommit、`ROS_DOMAIN_ID=88`、topic publisher数を確認する。
4. G923を固定し、周囲を退避し、USBまたは電源を即時切断できる。
5. Kobukiを停止し、車体速度を出さない。
6. 他のFFB writerが0件である。
7. challenge、command、statusを両PCでbag記録する。
8. ユーザーがchallenge方式の物理出力試験を改めて明示承認する。

## 実装結果（2026-09-24）

安全ゲートと自動テストの実装は完了した。G923へのアクセスと物理出力は行っていない。

- FFB adapterへ`challenge_hardware_armed`を既定falseで追加した。
- challenge＋hardwareでは同gateの明示true、challenge期限100 ms以下、watchdog 100 ms以下を必須にした。
- 既存の`hardware_armed`、初回試験gate、0.05上限、120 ms有限effect、writer lockは維持した。
- probeもchallenge＋hardwareに対応させたが、`--acknowledge-physical-output`を引き続き必須とした。
- 有効token、期限切れtoken、challenge発行例外、watchdog、0.05二重gateをfake backendで検査した。
- 安全系・probe対象テスト100件がPASSした。
- 変更Pythonファイルのflake8、pydocstyle、`git diff --check`はPASSした。
- ROS 2 package buildはPASSした。
- package全体では機能試験99件PASS、1件skip。既存ファイル由来のflake8/pydocstyle 2件だけが既知のFAILだった。

以上により「コード実装と自動試験」の条件は完了した。次はユーザーの明示承認後に、停止状態・0.03・1イベントの実機試験へ進む。

### 0.03停止状態実機試験

2026-09-24にchallenge＋hardware、3連、0.03、0.5秒、1イベントを実施した。command/statusは18/18、active applyは9/9、fault 0件、応答p95 1.036 ms、最終CLEAR停止0.568 msで、自動判定はPASSだった。各CLEARとshutdownでもinactiveを確認した。

操作者は振動を知覚できなかったため、0.03は通知強度としては不採用とする。詳細は[0.03 r01診断](phase5_challenge_hardware_probe_0p03_r01_diagnosis.md)を参照する。次は既に別方式で実機確認済みの0.05を、同じchallenge方式で1イベントだけ確認する。

### 0.05停止状態実機試験

challenge＋hardware、3連、0.05、0.5秒、1イベントを実施した。command/statusは18/18、active applyは9/9、fault 0件、応答p95 1.175 ms、最終CLEAR停止0.786 msで、自動判定はPASSだった。操作者は3回の振動を明確に知覚し、終了時も`shutdown`で正常停止した。

archive名は`0p03_r02`だったが、内部設定と全command/statusは0.05で一致している。詳細は[0.05 r01診断](phase5_challenge_hardware_probe_0p05_r01_diagnosis.md)を参照する。0.05・3連を採用条件とし、強度はこれ以上上げない。

### 録画TTC challenge hardware再生

過去の0.20 m/s接近sessionを30 Hzで再生し、challenge方式でG923まで出力した。command/statusは630/630、activeは13/13、fault 0件、challenge age最大26.13 ms、active応答最大4.47 msで、自動判定はPASSだった。操作者は意図したWARNINGの3連振動を明確に知覚した。

その約1.9秒後に短い振動も1回知覚した。ログ上は録画内の短い`UNKNOWN → CLEAR → UNKNOWN`によるactive 4件であり、通信欠落、watchdog、hardware faultではなかった。現行方針ではUNKNOWNもactiveで、WARNINGとUNKNOWNはいずれもadapter上限0.05へ制限され、共通の3連cadenceを使う。このため通知意味の区別が不十分である。

経路検証はPASSとするが、カメラ＋模擬ODOM試験の前に、WARNING/CRITICALは3連、UNKNOWNは単発または物理出力なし、という通知方針を決定する。詳細は[録画TTC hardware再生 r01診断](phase5_challenge_hardware_recorded_replay_r01_diagnosis.md)を参照する。

## 承認後の実機試験順

1. adapterだけをchallenge＋hardware、上限0.03で起動し、起動直後が無出力であることを確認する。
2. カメラを使わず、challenge対応probeを3連・0.03・1イベントだけ送る。
3. CLEAR、command停止によるwatchdog、Ctrl+Cの各停止を確認する。
4. 異常がなければ、既に物理確認済みの0.05へ上げ、録画再生由来の1イベントだけ確認する。
5. 最後にKobuki停止・模擬ODOMで、カメラ→TTC→command→G923の1イベントを確認する。
6. 走行しながらの試験は別段階とし、ここでは行わない。

## 中止条件

急回転、残留力、異音、発熱、意図しないAutocenter変化、writer競合、fault、challenge期限超過、watchdog不作動、USB切断後も異常が残る場合は直ちに中止する。

## 根拠

- [r02診断](phase5_callback_fix_dryrun_r02_diagnosis.md)
- [Linux Kernel Force Feedback仕様](https://www.kernel.org/doc/html/latest/input/ff.html)
- [ROS 2 Humble QoS](https://docs.ros.org/en/humble/Concepts/Intermediate/About-Quality-of-Service-Settings.html)
- FFB側`implementation_plan.md`のPhase 4・Phase 5、安全条件、ロールバック
