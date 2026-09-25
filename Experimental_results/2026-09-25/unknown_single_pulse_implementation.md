# UNKNOWN単発FFB実装（2026-09-25）

## 結論

2026-09-24の録画TTC hardware再生で判明した通知意味の混同に対応し、`WARNING`・`CRITICAL`は従来の3連、`UNKNOWN`は最大0.10秒の単発として送信するよう変更した。物理出力、強度、TTC判定、challenge期限、watchdogは変更していない。

本日の確認はコード、自動テスト、純粋ロジックのofflineシミュレーションまでであり、G923への物理出力は行っていない。

## 背景

従来の`VirtualFfbPolicy`は、認識が無効または不明な状態をfail-silentにせず、`UNKNOWN`、`pattern=pulse`、要求強度0.15としていた。しかし`CollisionFfbCadenceController`はpatternを区別せず、設定された3連cadenceをすべてのactive状態へ適用していた。

さらにhardware adapter上限0.05により、WARNINGの要求0.25とUNKNOWNの要求0.15はいずれも0.05へ制限される。継続時間が十分なUNKNOWNは衝突警告と同じ3連になり、操作者が通知の意味を区別できない可能性があった。

## 実装仕様

| リスク状態 | cadence | 最大送信時間 | 要求強度 | reason |
|---|---|---:|---:|---|
| WARNING / WARNING_HOLD | 設定値（v8は3連） | 0.50秒 | 0.25 | `...:cadence_triple` |
| CRITICAL | 設定値、WARNINGからの昇格時は再始動 | 0.50秒 | 0.40 | `...:cadence_triple` |
| UNKNOWN | 単発 | 0.10秒 | 0.15 | `invalid_or_unknown_perception:cadence_single` |
| CLEAR / PATH | 停止 | 0秒 | 0 | `no_alert`等 |

UNKNOWNが0.10秒を超えて継続しても再発火せず、`unknown_pulse_complete`としてinactiveを維持する。CLEAR/PATHでラッチを解除し、その後に新たなUNKNOWNへ入った場合だけ再通知する。UNKNOWNからWARNINGへ変化した場合は、衝突警告の3連を新規に開始する。

単発時間は`collision_ffb_unknown_pulse_duration_sec`で記録し、許容範囲を`0 < value <= 0.1`秒に制限した。preflightログには`ffb_unknown=single:0.1s`と表示する。

## 変更ファイル

- `src/collision_ffb_publisher.py`
  - hazardとUNKNOWNのcadenceラッチを分離。
  - UNKNOWNを最大0.10秒の単発に固定。
  - metadataへUNKNOWN cadenceを追加。
- `src/bird_eye.py`
  - UNKNOWN単発時間の既定値とpublisherへの引渡しを追加。
- `src/preflight_field_experiment.py`
  - 0.10秒上限の検査と起動ログ表示を追加。
- `src/replay_collision_ffb_commands.py`
  - `--unknown-pulse-duration`を追加。
  - replay JSON/MarkdownへUNKNOWN cadenceを記録。
- `src/bird_eye_config_ttc_v8_ffb_distinct_unknown_challenge_20260925.json`
  - v7 challenge設定を維持し、UNKNOWN単発時間0.10秒だけを明示した次期候補設定。
- `tests/test_collision_ffb_publisher.py`
  - UNKNOWN単発、継続時の非再発火、UNKNOWN→WARNING遷移、上限違反を検査。
- `tests/test_preflight_field_experiment.py`
  - v8設定と0.10秒上限を検査。
- `tests/test_replay_collision_ffb_commands.py`
  - replay成果物へ単発条件が残ることを検査。

## 検証結果

### 純粋ロジックシミュレーション

30 Hz、0.5秒、同じ状態を15フレーム継続した。

| 入力 | active pattern | active件数 | 判定 |
|---|---|---:|---|
| WARNING | `111001110011100` | 9 | 従来の3連を維持 |
| UNKNOWN | `111000000000000` | 3 | 最初の約0.10秒だけ単発 |

### 自動検査

| 検査 | 結果 |
|---|---:|
| 対象publisher試験 | 16/16 PASS |
| preflight試験 | 16/16 PASS |
| ROS interfaceをsourceした全unittest | 178/178 PASS |
| Python compile | PASS |
| v8 JSON構文 | PASS |
| v7 challengeとの差分 | UNKNOWN単発時間0.1秒の1項目だけ |
| replay JSON/Markdown provenance smoke test | PASS |
| `git diff --check` | PASS |

通常シェルでは`pytest`コマンドが導入されていないため、pytest形式のreplay試験群は直接実行していない。今回追加した成果物provenance検査と同じ処理は一時ディレクトリを使ったsmoke testでPASSした。既存のunittest 178件はFFB workspaceのROS interfaceをsourceして全件PASSした。

### 隔離ROS 2 dry-run

`ROS_DOMAIN_ID=117`、`ROS_LOCALHOST_ONLY=1`、`output_mode=dry_run`で、45フレームの合成riskを30 Hz再生した。入力はCLEAR 5、WARNING 15、CLEAR 5、UNKNOWN 15、CLEAR 5フレームで、終了CLEARを含む46 command/statusを記録した。G923 deviceは指定しておらず、hardware accessは無効だった。

| 指標 | 結果 |
|---|---:|
| 自動判定 | PASS |
| command / status | 46 / 46 |
| active command / status | 12 / 12 |
| WARNING active | 9、3連 |
| UNKNOWN active | 3、単発 |
| fault | 0 |
| 最大adapter適用値 | 0.05 |
| 最終状態 | inactive |

WARNINGのstatus reasonは9件すべて`ttc_warning:cadence_triple`、UNKNOWNは3件すべて`invalid_or_unknown_perception:cadence_single`だった。UNKNOWN継続中の残り12件は`unknown_pulse_complete`としてinactiveを維持した。

入力fixture、command、status、JSON、Markdownは[ROS dry-run結果](unknown_single_pulse_ros_dryrun/)へ保存した。

### 9月8日実録画のROS 2 dry-run

昨日のhardware再生と同じ`approach_center_v0p20_r02_v6holdout_20260908_163811_391`を、元archive`202609081640.tar.xz`から30 Hzで再生した。archive SHA-256は`7a38ec860b9bf5af3ef380332582ed154c4ca5dad4b12c44b4f38485e20facf7`である。

| 指標 | 結果 |
|---|---:|
| 自動判定 | PASS |
| command / status | 630 / 630 |
| active command / status | 13 / 13 |
| WARNING active | 9、`cadence_triple` |
| UNKNOWN active | 4、`cadence_single` |
| active応答中央値 / 最大 | 1.22 / 1.44 ms |
| fault | 0 |
| 最大adapter適用値 | 0.05 |
| 最終状態 | inactive |

UNKNOWNが4 activeなのは、元録画が2フレームUNKNOWN、1フレームCLEAR、2フレームUNKNOWNと2回入り直すためである。各UNKNOWN区間は単発として開始し、昨日操作者が一度の短い「ブルッ」と知覚した区間に対応する。継続UNKNOWNが3連へ変化しないことは、前項の15フレーム合成試験で確認した。

したがって本変更はUNKNOWN通知を消去するものではない。認識不明を短く通知するfail-not-silent方針を維持しながら、継続WARNINGの3連と継続UNKNOWNの単発を区別する。実録画の結果は[recorded risk v8 dry-run](recorded_risk_v8_ros_dryrun/)へ保存した。

合成riskと実録画の要求・適用波形は[成果報告用グラフ](report_assets/README.md)へ保存した。本日は新しいカメラ録画を行っていないため、生カメラ画像は追加していない。

## 次の作業

1. 最新コードをKobuki PCへ反映する。
2. G923を使わず、録画TTC再生と`dry_run` adapterでWARNING 3連、UNKNOWN単発、fault 0、最終inactiveを確認する。
3. dry-runがPASSした後、必要な場合だけKobuki停止状態でUNKNOWN単発を1回体感確認する。
4. 通知が識別できれば、v8設定で実カメラ・専用模擬ODOM・challenge・hardwareの停止状態統合試験へ進む。
5. 実走行は停止状態統合の完了後に別途判断する。
