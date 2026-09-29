# Phase 5 v12 reliability実装記録

## 目的

2026-09-29のv11実PC間dry-runで、challenge受信間隔が一時的に60～129 msへ伸びた際、relayがchallenge流を未安定へ戻し、その後1秒間active intentを見送った問題を修正する。また、一人試験でpreflight用publisherからシナリオpublisherへ切り替えた際に、両PCのrosbagが0.25 m/s区間を捕捉できなかった問題を解消する。

## 変更内容

### 1. challenge鮮度とstream継続性を分離

`collision_ffb_relay.py`へ `challenge_stream_timeout_sec` を追加した。未指定時は `challenge_max_age_sec` と同値にしてv10/v11の挙動を維持し、v12だけが0.2秒を明示する。

- `challenge_max_age_sec=0.06`: 各commandが使用するchallengeの最大年齢。従来どおりで緩和しない。
- `challenge_stable_sec=1.0`: relay起動またはreceiver session変更後に必要な安定時間。
- `challenge_stream_timeout_sec=0.2`: challenge流を再起動扱いにする持続的な受信断。

challengeが60 msより古い瞬間のintentは従来どおりfail-closedで見送る。一方、新しいchallengeが200 ms以内に再到着した場合は、それまで積み上げた1秒のstream安定状態を維持する。receiver session変更または200 ms超の受信断では安定時間をリセットする。

診断JSONには以下を追加した。

- `challenge_previous_gap_sec`
- `challenge_stream_timeout_sec`
- `challenge_stream_restart_count`

### 2. v12設定

実験済みv11設定は変更せず、`src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`を追加した。v11との差分は `collision_ffb_challenge_stream_timeout_sec: 0.2` の1項目だけである。

preflightはstream timeoutがchallenge max age以上、1.0秒以下であることを検証する。ワンコマンド起動も新しい引数をrelayへ明示的に渡す。

### 3. 同一publisherの一人用ODOM待機

`publish_mock_odom_scenario.py`へ `--wait-for-enter` を追加した。

- 起動直後から同じROS publisherで速度0を指定レートで送信する。
- Enter入力後もpublisherを作り直さず、停止→0.25 m/s→停止へ移行する。
- 待機中の送信もCSVへ `phase=waiting_for_start` として保存する。
- 従来のシナリオ行では `actual_elapsed_sec` をシナリオ開始基準のまま維持する。
- 新しい `run_elapsed_sec` は、待機を含むプロセス起動後の経過時間を全行へ記録する。

これにより、別のpreflight用 `ros2 topic pub` を停止して新しいpublisherを起動する手順が不要になる。rosbag、preflight、カメラはすべて同一publisherを継続して観測できる。

## 9月29日bagによるオフライン回帰

Kobuki PC bagのchallengeとintentを記録時刻順にv12ゲートへ再入力した。

| 指標 | v11実記録 | v12オフライン再生 |
|---|---:|---:|
| recording window intent | 2,411 | 2,411 |
| active intent | 27 | 27 |
| active転送・許可 | 12 | 26 |
| active見送り | 15 | 1 |
| `stream_not_stable`見送り（全intent） | 567 | 0 |
| stream restart | 多数 | 初回1回のみ |

見送りが残ったsequence 3053は、個々のchallenge ageが60 msを超えていたための正しいfail-closedである。同じUNKNOWN pulseの後続3054～3056は許可されるため、UNKNOWNイベント自体は失われない。

詳細な機械可読結果は `phase5_v12_relay_offline_replay.json` に保存した。

## 自動テスト

次を追加・更新した。

- 実測最大値相当の129 ms gapではstream安定状態を維持する。
- 200 msを超える持続的gapではstream安定状態をリセットする。
- stream timeoutがchallenge max age以下、1秒超、非有限値の場合は拒否する。
- relay診断JSONへ新しいgap・timeout・restart情報が入る。
- 待機中はEnterまで同一処理から速度0 publishを続ける。
- v12設定がpreflightを通り、relay起動引数へ0.06秒と0.2秒が別々に渡る。

## 検証結果

| 検証 | 結果 |
|---|---:|
| Python構文確認 | PASS |
| relay・ODOM・起動・preflightの関連テスト | 48/48 PASS |
| ROS/FFB workspaceをsourceした全テスト | 211/211 PASS |
| v12ワンコマンド起動 `--dry-run` | PASS |
| ODOMシナリオ `--wait-for-enter --dry-run` | PASS |
| 9月29日Kobuki bagのrelayゲート再生 | PASS（active 26/27、イベント群は全群残存） |
| 短縮ODOMシナリオのCSV生成 | PASS（待機→停止→0.25 m/s→停止） |

短縮ODOM smoke testは隔離したROS domain 199で実行し、同一プロセスから待機行と3 phaseを1つのCSVへ保存できた。実行環境ではDDSのUDP socket作成がsandboxに拒否されたため、別subscriberからの受信確認は未実施である。実PC上の通信確認は次回2PC dry-runで行う。

## 安全判断

- command単位のchallenge鮮度60 msは変更していない。
- 古いchallengeを使ったcommandは引き続き転送しない。
- receiver session変更と200 ms超の受信断では1秒の再安定化を要求する。
- 変更はrelayと専用mock ODOMだけであり、Kobuki実機の `/odom` へ模擬値を送らない。
- 実機hardware出力は未実施。次は必ず2PCの`dry_run`で確認する。
