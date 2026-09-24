# 2026年9月24日 日報

## 本日の到達点

Phase 5のPC間FFB経路について、challenge受信不安定の原因をROS 2 callback処理まで切り分け、challengeとODOMを専用executorで継続受信するよう修正した。修正後の実カメラ・模擬ODOM・PC間`dry_run`では、青箱検知からTTC WARNING、3連FFB command、adapter statusまで同一sequenceで接続できた。

続いて、FFB側へchallenge方式hardware専用の安全ゲートと自動テストを追加した。Kobuki停止状態で0.03と0.05を段階的に確認し、0.03は知覚できなかったが、0.05では3回の振動を明確に知覚できた。最後に、過去の0.20 m/s接近録画を使ったPC間hardware再生を実施し、意図したTTC WARNINGの3連振動を確認した。

録画再生では、3連振動の約1.9秒後に短い振動も1回知覚した。解析の結果、通信障害やG923の誤作動ではなく、録画内の短い`UNKNOWN → CLEAR → UNKNOWN`に現行FFB方針が反応したものだった。したがって、**challenge方式のカメラ側処理、PC間通信、安全ゲート、G923物理出力までの経路検証はPASS**とする。一方、衝突警告と認識不明通知の物理パターンを区別する設計は次回へ持ち越す。Kobukiを走行させながらのFFB試験は行っていない。

## 使用環境と安全条件

| 項目 | 内容 |
|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5`：360度カメラ、`bird_eye.py`、模擬ODOM、FFB command送信 |
| ハンコン接続PC | `hsr-Alienware-m16-R2`：G923、challenge発行、hardware adapter、status記録 |
| ROSドメイン | 両PCとも`88` |
| 実験対象 | 青箱、および9月8日の0.20 m/s接近録画 |
| 車体 | 停止状態。実走行なし |
| FFB上限 | 0.05。有限3連、effect 120 ms、watchdog 100 ms |
| freshness | PC間wall clock比較ではなく、受信側monotonic clockを使うchallenge方式 |

## 1. challenge受信停止の原因診断

最初のr01では、ハンコン接続PCが発行したchallengeはKobuki PCのbagへ約50 Hzで連続到着していたが、`bird_eye.py`は912フレーム中489フレームで`no_recent_receiver_challenge`として送信を見送った。録画区間に対応するchallenge token 1,542件は両PCで全件一致し、PC間欠落は0件だった。ODOMもbagには90件存在した一方、カメラCSVに0.25 m/sとして残ったのは28フレームだけだった。

この結果から、主因をネットワークやPC間時刻ではなく、カメラフレームごとのゼロ待ち`spin_once`へ依存したcallback処理と特定した。録画では画面全体が一時的に青へ偏って青箱検知0/912となったが、その後の`bird_eye.py`単体起動では検知へ復帰したため、HSVしきい値は変更していない。

詳細は[challenge受信診断r01](../Experimental_results/2026-09-24/phase5_challenge_reception_diag_r01_diagnosis.md)を参照する。

## 2. callback安定化の実装

challengeとODOMをそれぞれ専用`SingleThreadedExecutor`スレッドで受信し、画像処理側はlockで保護された最新値を読む構成へ変更した。challenge受信数・age・session/token、ODOM受信数を録画CSVと標準解析へ追加し、送信側のchallenge利用期限を60 msへ設定した。executor異常時や期限切れ時は指令を送らないfail-closedを維持した。

| 検証 | 結果 |
|---|---:|
| Python compile | PASS |
| カメラ側全単体・回帰試験 | 174/174 PASS |
| challenge単独ローカル受信 | 5/5 PASS |
| ODOM単独ローカル受信 | 5/5 PASS |
| challenge・ODOM同時受信 | 各10/10 PASS |

実装内容は[callback安定化記録](../Experimental_results/2026-09-24/challenge_callback_stabilization_implementation.md)へ保存した。

## 3. 修正後の実カメラ・PC間dry-run

最終確認の`phase5_callback_fix_dryrun_r02`では、青箱検知、模擬ODOM、TTC WARNING、3連FFB、両PCのbag、adapter statusまでを照合した。

| 指標 | 実測 |
|---|---:|
| 録画フレーム / 動画3種 | 897 / 各897 |
| 青箱検知・観測採用・追跡 | 各897/897 |
| challenge受信増分 | 1,529件、約30.6秒で期待値約1,530件 |
| challenge age 平均 / p95 / 最大 | 9.77 / 19.19 / 29.89 ms |
| 60 ms超過・3フレーム以上停止 | 0 / 0 |
| FFB publish | 897/897成功 |
| active command/status | 9/9、両PCで同一sequence |
| adapter | 全件`dry_run`、最大適用0.05、fault 0 |
| command→status | 0.211～0.682 ms |
| 実効FPS | 29.286 FPS |

challenge/FFB機能はPASSした。標準解析の自動FAILは30 FPS±1%の品質基準だけによるもので、raw・BEV・detection・CSVの欠損はない。同条件の再録画は不要と判断した。詳細は[r02診断](../Experimental_results/2026-09-24/phase5_callback_fix_dryrun_r02_diagnosis.md)を参照する。

## 4. challenge方式hardware安全ゲート

FFB側リポジトリで、challenge＋hardwareを無条件に解禁せず、起動ごとの明示承認`challenge_hardware_armed=true`、challenge期限100 ms以下、watchdog 100 ms以下を必須化した。既存の`hardware_armed`、初回実機試験gate、0.05上限、120 ms有限effect、安定device path、writer lockは維持した。

fake backendで有効token、未知・期限切れtoken、watchdog、challenge発行例外、CLEAR、shutdown、device write失敗を検査した。対象安全系・probe試験100件、ROS package buildはPASS。package全体の機能試験は99件PASS・1件skipで、既存ファイル由来のlint 2件だけが既知のFAILだった。安全条件と結果は[hardware安全レビュー](../Experimental_results/2026-09-24/phase5_challenge_hardware_safety_review.md)へ記録した。

## 5. 停止状態hardware probe

| 条件 | command/status | active適用 | fault | 応答p95 | 操作者の体感 | 判定 |
|---|---:|---:|---:|---:|---|---|
| 0.03・3連・0.5秒 | 18/18 | 9/9 | 0 | 1.036 ms | 振動を知覚できず | 経路PASS、通知強度不採用 |
| 0.05・3連・0.5秒 | 18/18 | 9/9 | 0 | 1.175 ms | 3回を明確に知覚 | PASS・採用 |

0.05試験の元archive名は`0p03_r02`だったが、内部設定、command、status、adapterログはすべて0.05で一致したため、実条件に合わせて0.05 r01として整理した。0.05を現行上限として維持し、これ以上は上げない。

## 6. 録画TTCによるPC間hardware再生

9月8日の`approach_center_v0p20_r02_v6holdout`を30 Hzで再生し、challenge方式でG923へ物理出力した。

| 指標 | 実測 |
|---|---:|
| 自動判定 | PASS |
| command / status | 630 / 630 |
| active command / status | 13 / 13 |
| sequence対応 / active不一致 | 630/630 / 0 |
| challenge age 平均 / p95 / 最大 | 9.93 / 19.10 / 26.13 ms |
| active command→status 中央 / p95 / 最大 | 3.82 / 4.33 / 4.47 ms |
| fault / 最大適用強度 | 0 / 0.050 |
| 最終状態 | inactive、faultなし |

意図したWARNINGはsequence 149～161で、3パルス開始間隔は170.8 ms、170.7 msだった。操作者は1組の3連振動を知覚した。

約1.9秒後、sequence 215～216と218～219で`invalid_or_unknown_perception`がactiveになった。2区間の開始間隔は約103 msで、操作者が一度の短い振動として知覚した結果と一致する。現行`VirtualFfbPolicy`はUNKNOWNをfail-silentにせず0.15のpulseとして出力するが、adapter上限によりWARNING 0.25と同じ0.05へ制限され、triple cadenceも共通適用される。詳細は[録画TTC hardware再生r01診断](../Experimental_results/2026-09-24/phase5_challenge_hardware_recorded_replay_r01_diagnosis.md)を参照する。

## 本日の判断と残課題

- challenge/ODOM callback停止は専用executor化で解消した。
- 時刻同期に依存しないchallenge方式は、dry-runとhardwareの双方で期限・sequence・停止を含めて成立した。
- 0.05・3連は知覚可能であり、現段階の衝突警告条件として採用する。0.03は通知用途には弱い。
- 録画再生の追加振動はhardware異常ではなく、短いUNKNOWN判定への仕様どおりの反応だった。
- WARNING/CRITICALとUNKNOWNの通知意味が物理的に区別できていない。カメラ＋模擬ODOMのhardware試験前に方針を固定する。
- 実カメラからG923までのhardware統合、および走行中のFFBは未実施である。

## 成果物

- [2026-09-24実験結果](../Experimental_results/2026-09-24/)
- [成果報告用画像・グラフ](../Experimental_results/2026-09-24/report_assets/README.md)
- [hardware probe 0.03診断](../Experimental_results/2026-09-24/phase5_challenge_hardware_probe_0p03_r01_diagnosis.md)
- [hardware probe 0.05診断](../Experimental_results/2026-09-24/phase5_challenge_hardware_probe_0p05_r01_diagnosis.md)
- [録画TTC hardware再生結果](../Experimental_results/2026-09-24/phase5_challenge_hardware_recorded_replay_r01/)

代表資料として、challenge受信とカメラ側見送りの比較グラフ、callback修正後のchallenge age/FFBグラフ、修正前後の無編集生カメラフレームを保存した。画像は元映像と同じ1280×720で、切り抜き、注釈、リサイズ、色補正をしていない。元の大容量録画archiveは`/home/robo25/Downloads/`等に保持し、Gitへ追加していない。

## 次回作業

1. `UNKNOWN`を衝突警告と区別できる単発通知にするか、物理FFBを無効にしてstatus・ログだけへ残すか決定する。fail-silentを避けつつ意味を区別できる単発通知を第一候補とする。
2. 方針を自動テストへ固定し、今回の録画を使ってWARNINGは3連、UNKNOWNは選択したパターンになることをoffline/dry-runで回帰確認する。
3. 必要な場合だけ、Kobuki停止状態でG923の短い確認を1回行う。
4. その後、実カメラ・青箱・専用`/phase5/mock_odom`からG923までのhardware統合試験へ進む。
5. 実走行試験は、停止状態の統合がPASSした後の別段階とする。

## Git

RICHO-thetaの本日先行コミットは`9ec8b5f`、`7f03eee`、`274c622`、`a6f9081`。FFB側の安全ゲート実装は`8c2f99a`で、両リポジトリとも当該先行コミットは`origin/main`へ反映済みである。本日最後の録画TTC再生結果、診断、安全レビュー追記、日報は追加コミットとして管理する。
