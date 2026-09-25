# PC間challenge遅延回復処理 実装記録

## 結論

2026-09-25の実カメラUNKNOWN試験で確認したchallenge配送不安定に対し、カメラPC側の送信処理をfail-safeに修正した。受信側adapterの期限判定、最大許容時間0.10秒、watchdog、出力上限は変更していない。

この修正により、カメラ処理中にchallenge callbackが停止した場合、復帰直後の遅延tokenをそのまま返送せず、0.10秒の回復期間で受信キューが最新状態へ追いつくのを待つ。また、1個のtokenを複数フレームで再利用せず、通信中断によって3連cadenceが先頭から再開することも防ぐ。

コード単体・回帰試験はPASSした。PC間の実配送でfaultが0件になることはまだ実測していないため、hardwareへ進む前にv9設定を使ったdry-run再試験が必要である。

## 修正根拠

対象試験の診断は `phase5_v8_camera_unknown_dryrun_r01_diagnosis.md` に記録した。録画区間ではadapter faultが24件あり、内訳は`unknown_receiver_token` 23件、`expired_receiver_token` 1件だった。

代表sequence `4738`では、カメラ処理が記録したcallback後のchallenge ageは3.24 msだった一方、HSR側bagで観測したchallengeからcommandまでの時間は約167 msだった。この差から、challengeがPCへ到着してからPython callbackが実行されるまでの停止時間を、従来のsender ageだけでは検出できないと判断した。

## 実装内容

### `src/collision_ffb_publisher.py`

- 同一session内でtokenが増加しないchallengeを最新値として採用しない。
- 送信済みの`session_id + token`を再利用しない。
- challenge callback間隔が設定期限を超えた場合、executor/DDSの滞留を疑い、設定時間だけ送信を停止する。
- sender側でchallenge age超過を検出した場合も同じ回復期間へ入る。
- 回復の原因（`callback_gap`または`sender_age`）と検出時間を録画CSVへ残す。
- challengeが使えない間は、新しいWARNING・CRITICAL・UNKNOWN cadenceを開始しない。
- 開始済みcadenceはchallenge欠落中も経過時間を進め、通信復帰時に先頭から再開しない。
- `challenge_max_age_sec`と`challenge_recovery_sec`はともに0より大きく0.10秒以下に制限する。

### `src/bird_eye.py`

- `collision_ffb_challenge_recovery_sec`を設定から送信bridgeへ渡す。
- 未指定時の既定値は0.10秒とする。

### `src/preflight_field_experiment.py`

- 回復時間が`(0, 0.10]`秒であることを事前確認する。
- 実験開始ログへchallenge回復時間を表示する。

### v9候補設定

`src/bird_eye_config_ttc_v9_ffb_challenge_recovery_20260925.json`を追加した。v8からの機能差分は次の1項目だけである。

```json
"collision_ffb_challenge_recovery_sec": 0.1
```

TTC閾値、UNKNOWN単発0.10秒、WARNING/CRITICALの3連cadence、challenge age 0.06秒、FFB強度は変更していない。

FFB adapter側リポジトリは変更していない。今回faultを返した受信側検証は正しくfail-safeに動作していたためである。

## 検証結果

| 検証 | 結果 |
|---|---:|
| FFB publisher単体テスト | 22件 PASS |
| preflight単体テスト | 17件 PASS |
| 全回帰テスト | 185件 PASS |
| Python構文確認 | PASS |
| v9 JSON構文確認 | PASS |

追加テストでは、tokenの単回使用、同一sessionの逆順token除外、sender age超過後の回復待ち、167 msのcallback停止後の回復待ち、通信断後に3連cadenceを再開しないこと、0.10秒を超える設定の拒否を確認した。

## 安全上の境界と未確認事項

- adapter側の受信時計によるtoken検証は変更していない。遅延tokenは引き続き拒否される。
- 回復期間は遅延を許容するための緩和ではなく、遅延中の送信を止めるための措置である。
- ネットワークまたはDDS自体の往復時間が常時0.10秒を超える場合、この修正後もadapterはcommandを拒否する。その場合に期限を延ばして回避してはならない。
- 終了時CLEARがchallenge不足で送れない場合も、adapter側watchdogが0.10秒以内に出力を停止する設計は維持される。
- 次はv9設定・`dry_run`で、adapter fault 0件、active commandとactive statusの全件対応、最終inactiveを確認する。これらを満たすまではhardware試験へ進めない。
