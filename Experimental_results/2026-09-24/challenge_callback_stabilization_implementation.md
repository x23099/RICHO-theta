# Challenge/ODOM callback安定化（2026-09-24）

## 結論

2026-09-24の3入力を照合した結果、challengeはハンコン接続PCからKobuki PCへ50 Hzで欠落なく届いていた一方、`bird_eye.py`内では長時間利用されていなかった。ODOMにも同様の差があった。このため、ネットワークやPC間時刻同期ではなく、カメラフレームごとのゼロ待ち`spin_once`に依存したcallback処理を修正した。

challengeとODOMは、それぞれ専用の`SingleThreadedExecutor`スレッドで継続受信する。GUI/画像処理側はlockで保護された最新値を読むだけにした。executor異常時は指令を送らず、従来どおり安全側へ停止する。

## 実装内容

- `src/ros_executor_thread.py`
  - ROS nodeを専用executorスレッドで処理する共通クラスを追加。
  - 非同期例外の検出と、上限時間付きshutdownを実装。
- `src/collision_ffb_publisher.py`
  - challenge subscriptionをフレーム処理から独立。
  - 受信累計、最新challengeのage、session ID、tokenを各フレームのCSVへ記録。
  - executor異常または期限切れ時はpublishせずfail-closed。
- `src/ros_odometry.py`
  - ODOM subscriptionをフレーム処理から独立。
  - callback共有値をlockで保護し、受信累計を保持。
- `src/bird_eye.py`
  - `odom_received_count`を録画CSVへ追加。
  - challengeの送信側期限をconfigからpublisherへ渡す。
- `src/summarize_live_trials.py` / `src/analyze_field_recording.py`
  - ODOM/challenge受信増分、challenge age p95/max、FFB publish成功率、challenge見送り数を標準解析へ追加。
- `src/bird_eye_config_ttc_v7_ffb_triple_challenge_dryrun_20260917.json`
  - 受信側の100 ms期限に余裕を残すため、送信側のchallenge利用期限を60 msに設定。
- `src/preflight_field_experiment.py`
  - challenge利用期限が`0 < age <= 0.1 s`であることを事前検査。

## 青箱検知について

対象録画では画面全体の青偏りによって検出0/912だったが、その後の`bird_eye.py`単体起動では青箱検知へ復帰した。恒常的なしきい値不良とは判断せず、HSVしきい値は変更していない。次回は本録画前の10秒pilotで輪郭表示を確認する。

## 検証

- Python compile: PASS
- 全単体・回帰試験: **174/174 PASS**
- 実ROS 2単独ローカル結合試験:
  - challenge 5/5件、ODOM 5/5件をそれぞれ受信
  - 最新challengeを使ったCLEAR publish成功
- 実ROS 2同時ローカル結合試験:
  - 2つの専用executorを同時起動し、challenge 10/10件、ODOM 10/10件を受信
  - 最新session/token `88/10`、challenge age 19.73 ms
  - `linear.x=0.25 m/s`を取得し、CLEAR publish成功

### 実機2台・カメラ負荷下の確認

`phase5_callback_fix_dryrun_r02`で最終確認を実施し、callback安定化とPC間dry-run FFB経路はPASSした。

- challenge受信増分1,529件（約30.6秒、期待値約1,530件）
- challenge age平均9.77 ms、p95 19.19 ms、最大29.89 ms
- 60 ms超過、3フレーム以上の受信停止、`no_recent_receiver_challenge`: すべて0件
- FFB publish: 897/897成功
- active 9 sequenceがカメラ・両PC bag・adapter statusで完全一致
- adapter: 全件`dry_run`、active 9/9件を0.05で適用、fault 0件、最終inactive

詳細は[callback修正後r02診断](phase5_callback_fix_dryrun_r02_diagnosis.md)を参照。標準解析の全体FAILは実効FPS 29.286によるもので、callback/FFB機能はPASSとして分離評価した。

## 合格条件の結果

1. 青箱連続検知: PASS（897/897）
2. challenge受信累計の単調増加: PASS
3. challenge age 0.06秒以内: PASS（最大0.02989秒）
4. `no_recent_receiver_challenge`なし: PASS
5. 模擬ODOM中の受信: PASS
6. WARNING/activeとdry-run status対応: PASS（9/9 sequence）

challenge方式をhardwareへ展開する前の安全レビューを別作業として実施した。詳細は
[challenge方式hardware展開前安全レビュー](phase5_challenge_hardware_safety_review.md)を参照する。

レビュー結果は、コード実装は条件付きGO、現時点の物理出力はNO-GOである。現行adapterの
challenge＋hardware禁止を単純に削除せず、専用の明示gate、challenge期限100 ms以下、
watchdog 100 ms以下を追加してfake backend試験を完了してから、別途承認を得て停止状態の実機試験へ進む。
