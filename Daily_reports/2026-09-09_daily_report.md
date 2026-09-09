# 2026年9月9日 日報

## 1. 本日の目的と到達点

本日は、前日に実装したTTC連動FFBの安全ポリシーを、ROS 2のdry-run adapter、
`RICHO-theta`のライブ衝突リスクpublisher、G923の物理出力へ段階的に接続した。

本日の主な到達点は次のとおりである。

1. Phase 2として、G923を開かないdisabled/dry-run対応adapterとstatus topicを実装した。
2. Phase 3として、`bird_eye.py`の最終衝突リスクを`/collision/ffb_command`へpublishする経路を実装した。
3. 過去録画2,502フレームと合成ROS通信で、オフライン評価とライブ要求の一致を確認した。
4. Phase 4として、有限時間effect、強度gate、writer排他、停止・eraseを備えたhardware backendを実装した。
5. G923停止状態試験で、正弦波は知覚できず、同じ強度の矩形波は知覚できることを確認した。
6. 実機結果に基づき、collision FFBの全active patternを矩形波へ変更した。

Kobukiを走行させながらのTTC連動FFB試験は行っていない。物理試験中のKobuki PCは使用せず、
G923を接続したPC上で合成要求だけを使用した。

## 2. 使用PCと役割

| 呼称 | ホスト名 | 本日の役割 |
|---|---|---|
| ハンコン接続PC | `hsr-Alienware-m16-R2` | G923、`collision_ffb_node` hardware mode、status監視、合成要求送信 |
| Kobuki PC | `matunuc-NUC13ANHi5` | Kobuki、カメラ、`bird_eye.py`、`/odom`。Phase 4物理試験では未使用 |

今後も「ハンコン接続PC」と「Kobuki PC」を区別して手順を記載する。

## 3. Phase 2: dry-run ROS adapter

`FFB_feedback_control`側へ`collision_ffb_node`と`CollisionFfbStatus`を追加し、
意味付きFFB要求を受信して安全ポリシーを適用し、結果をstatusとログへ出力できるようにした。

主な実装内容は次のとおりである。

- 出力モードを`disabled`、`dry_run`、`hardware`に限定した。
- 既定は`disabled`とし、明示的に選択しない限り物理デバイスを開かない。
- source、sequence、生成時刻、risk、pattern、active、強度を検証する。
- 不正値、古い要求、状態不整合、通信断をfail-closedでSTOPへ変換する。
- active要求を設定上限へclampし、既定では要求0.25を0.05へ制限する。
- 最後の妥当な要求から100 ms経過すると、watchdog STOPを一度だけ発行する。
- `/collision/ffb_status`へ適用値、action、停止理由、faultをpublishする。

| 検証 | 結果 |
|---|---|
| policy・adapter対象テスト | 43件PASS |
| ROS 2 Humble build | `oit_interfaces`、`oit`の2パッケージPASS |
| dry-run時のG923アクセス | 0回 |
| 要求0.25のclamp | 適用値0.05 |
| publisher停止後のwatchdog | 約104 msでSTOP、1回のみ |

## 4. Phase 3: `bird_eye.py`からのライブpublisher

`RICHO-theta/src/collision_ffb_publisher.py`を追加し、`bird_eye.py`がヒステリシス適用後の
最終衝突リスクをフレームごとに`CollisionFfbCommand`へ変換するようにした。

主な実装内容は次のとおりである。

- オフライン解析と同じ`VirtualFfbPolicy`をライブpublisherでも再利用した。
- 既定設定ではFFB publisherを無効とし、専用v6設定でのみ明示的に有効化した。
- 終了時は最後にCLEARを送ってからROS nodeを破棄する。
- recording metadataと`detections.csv`へsequence、要求強度、pattern、active、送信結果を保存する。
- preflightへFFB設定と`oit_interfaces.msg`の検査を追加した。

### 4.1 過去録画による回帰確認

入力は2026年9月8日の`202609081640.tar.xz`、比較先は既存の
`virtual_ffb_replay.csv`とした。

| session | frames | active frames | events | peak demand | 結果 |
|---|---:|---:|---:|---:|---|
| approach r01 | 625 | 29 | 2 | 0.25 | MATCH |
| approach r02 | 629 | 69 | 3 | 0.25 | MATCH |
| approach r03 | 626 | 22 | 4 | 0.25 | MATCH |
| omake | 622 | 15 | 1 | 0.25 | MATCH |

4セッション計2,502フレームで、activeフレーム数、リスク別フレーム数、event数、最大要求強度が
既存のオフライン解析結果と一致した。

### 4.2 実ROS 2 dry-run接続

| risk | publisher要求 | adapter適用値 | 結果 |
|---|---:|---:|---|
| CLEAR / PATH | 0.00 | 0.00 | inactive |
| WARNING | 0.25 | 0.05 | active |
| WARNING_HOLD | 0.25 | 0.05 | active |
| CRITICAL | 0.40 | 0.05 | active |

- 30 commandを1.000秒、30.0 Hzで送信し、30件すべてのapply statusを確認した。
- active送信停止から約100 ms後に`watchdog_timeout`でinactiveになった。
- publisher close時のCLEARとadapter終了時のshutdownでもinactiveを確認した。
- `RICHO-theta`の全159テストとFFB環境を読み込んだpreflightがPASSした。

以上からPhase 3の完了条件を満たした。

## 5. Phase 4: G923 hardware backendと安全対策

物理出力前に、次の安全機構を実装した。

- evdevを遅延importし、disabled/dry-runではG923を開かない。
- `FF_PERIODIC`を有限時間で再生し、1 effectを更新して使用する。
- 1回のeffect長を最大120 msに制限する。
- CLEAR、watchdog、例外、Ctrl+C、通常終了でstopとeraseを試行する。
- `/tmp/oit-g923-ffb-writer.lock`を使い、FFB writerの多重起動を拒否する。
- 安定した`/dev/input/by-id/*-event-joystick`だけをhardware modeで許可する。
- 初回は`hardware_armed=true`と`max_magnitude<=0.03`を必須にする。
- 初回確認後のみ`hardware_initial_test_passed=true`を明示して0.05まで許可する。
- Phase 4では0.05を超えるhardware設定を常に起動拒否する。
- 既存の`ffb_follow`、`spring`、`periodic`にも同じwriter lockを適用した。

| 検証 | 結果 |
|---|---|
| 初期hardware backend・policy・adapter対象テスト | 60件PASS |
| 0.05段階gate追加後 | 62件PASS |
| 矩形波反映後の最終対象テスト | 65件PASS |
| 変更対象のflake8 / pydocstyle / diff check | PASS |
| ROS 2クリーンビルド | 2パッケージPASS |
| リポジトリ全体colcon test | 対象60件PASS、1件skip、既存lint 2件のみ既知FAIL |

## 6. G923停止状態の物理出力試験

### 6.1 試験条件

- G923を接続したハンコン接続PCだけを使用した。
- Kobukiは走行させず、カメラ・TTCとは接続しなかった。
- 合成`CollisionFfbCommand`を30 Hzで15件、約0.5秒送信した。
- 終了時はCLEARを3件送り、node終了時にもstopを実行した。
- effect長は120 ms、adapter watchdogは100 msとした。

### 6.2 結果

| 波形 | 正規化強度 | 代表継続時間 | ソフトウェア結果 | 操作者の体感 |
|---|---:|---:|---|---|
| 正弦波 | 0.03 | 約0.501秒 | apply後に正常停止、faultなし | 知覚できず |
| 正弦波 | 0.05 | 約0.503秒 | apply後に正常停止、faultなし | 知覚できず |
| 矩形波 | 0.05 | 約0.503秒、2回 | 両方ともapply後に正常停止、faultなし | 知覚できたが危険通知としては弱い |

矩形波試験では、両試行ともsequence 0で`requested=0.050`、`applied=0.050`、
`pattern=3`、`fault=false`となり、sequence 15のCLEARで`action=stop`、
`output_active=false`へ遷移した。追加CLEARは停止状態を維持し、Ctrl+C時もshutdown STOPを確認した。

急回転、異音、発熱、Autocenterの異常など、ハンドル側の問題は報告されなかった。

### 6.3 判断

- ROS topic、adapter、evdev、G923の物理出力、CLEAR停止までの経路はPASSと判断する。
- 同じ0.05で正弦波は知覚できず矩形波は知覚できたため、主因は単純な通信不良ではなく波形差である。
- 実機結果を受け、collision FFB backendの`STEADY`、`STEADY_HOLD`、`PULSE`をすべて矩形波へ変更した。
- 0.05は知覚可能だが危険通知として弱いため、最終強度としては未確定である。
- 強度不足を理由に即座に上限を上げず、0.05の安全上限を維持した。

Phase 4は部分完了である。物理振動と停止は確認できたが、変更後の通常WARNING経路、effect slotの
再起動前後比較、警告強度・時間パターンの決定が残っている。

## 7. 本日のGit履歴

### RICHO-theta

- `2c46e4f`: 衝突リスクをFFB dry-runへ接続

### FFB_feedback_control

- `4ee2e99`: 衝突警告FFBのdry-runノードを追加
- `55f8d14`: Phase 3のdry-run接続結果を記録
- `491c5fa`: 実機FFB試験前の安全機構を実装
- `37feb0b`: G923初回物理出力試験を記録
- `3e6f815`: 0.05実機試験の段階的安全ゲートを追加
- `ba7e80c`: 衝突警告FFBを実機確認済み矩形波へ変更

日報作成前の確認では、両リポジトリとも`main`と`origin/main`が一致し、作業ツリーはcleanだった。

## 8. 成果物

- Phase 3検証結果:
  `Experimental_results/2026-09-09/phase3_ffb_dry_run_validation.md`
- G923物理試験記録:
  `/home/robo25/FFB_feedback_control/FFB_feedback_control/docs/2026-09-09_phase4_initial_hardware_test.md`
- TTC連動FFB実施計画:
  `/home/robo25/FFB_feedback_control/FFB_feedback_control/implementation_plan.md`

## 9. 未完了事項

1. 実機結果を反映した最新コードをハンコン接続PCでpull・buildし、通常の
   `WARNING / STEADY`が矩形波として知覚できることを1回確認する。
2. 0.05は危険通知として弱いため、波形周期・通知cadence・継続時間と強度を安全に比較する必要がある。
3. 0.05を超える場合は、現行gateを迂回せず、次段階の上限と停止条件を別変更として承認・テストする。
4. effectの反復後・node再起動後に利用可能slot数が減らないことを確認する。
5. Phase 5として、Kobuki停止状態で`bird_eye.py → ROS topic → adapter → G923`の全経路を接続する。
6. Phase 5ではWARNING開始からG923要求までのソフトウェア遅延p95と、CLEAR・カメラ停止時の停止を記録する。
7. 走行中のTTC連動FFBはPhase 5完了後に別計画として扱う。
8. YOLOによる一般物体検知は本日の対象外であり、未着手のままである。

## 10. 次回作業

次回は、まずハンコン接続PCで`ba7e80c`以降を反映して再ビルドし、G923を固定した停止状態で
通常WARNINGの矩形波0.05を1イベントだけ確認する。

その結果が今回と同じ「知覚できるが弱い」で、急回転、異音、発熱、Autocenter異常がない場合は、
通知cadenceまたは次段階強度の比較案を作成する。強度を上げる場合は0.05超過を許可する安全gate、
単発時間、停止手順、合格・中止基準を先に実装・検証してから物理出力する。

通常WARNINGの確認後は、Kobukiを停止したまま青箱または安全な再生入力を使い、Phase 5の
end-to-end接続へ進む。走行を伴う実験には自動的に進まない。
