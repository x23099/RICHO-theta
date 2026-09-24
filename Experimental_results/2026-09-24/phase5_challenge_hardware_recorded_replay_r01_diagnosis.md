# Phase 5 challenge方式・録画TTC hardware再生 r01診断（2026-09-24）

## 判定

**通信・adapter・G923出力経路はPASS。体感した「3回＋短い1回」はログと一致し、後半の短い振動は録画内の`UNKNOWN`判定による別イベントだった。**

意図したTTC `WARNING`では約0.5秒の3連通知が1回発生し、操作者も3回の振動を知覚した。その約1.9秒後、認識状態が短時間`UNKNOWN → CLEAR → UNKNOWN → CLEAR`と変化し、現行FFB方針が`UNKNOWN`にも通知を割り当てているため、2つの短い出力区間が発生した。両区間の開始間隔は約103 msであり、操作者が一度の「ブルッ」として知覚した結果と整合する。

これはchallenge期限切れ、watchdog、通信欠落、G923の自発的な誤作動ではない。ただし、衝突警告の3連通知と認識不明通知を物理的に明確に区別できていないという設計上の課題が見つかった。

## 入力

| 入力 | SHA-256 |
|---|---|
| `phase5_challenge_hardware_recorded_replay_r01.tar.xz` | `392b22a798e166e26fbbfafc5a5c10bcbb625e7ab594f0a8ad654b864faaaf79` |
| `aaa`（adapter console/statusログ） | `80dd8b9b11ad28049951b4bebbd324679569af68ecd42a54f76a63d099e19fff` |

展開した結果とconsoleログは`phase5_challenge_hardware_recorded_replay_r01/`へ保存した。

## 実験条件

| 項目 | 値 |
|---|---:|
| 入力session | `approach_center_v0p20_r02_v6holdout_20260908_163811_391` |
| replay rate | 30 Hz |
| output mode | hardware |
| freshness mode | challenge |
| cadence | triple / 0.5秒 / 30 Hz |
| adapter最大強度 | 0.05 |
| physical output acknowledgement | true |

## 自動検査結果

| 項目 | 結果 |
|---|---:|
| 自動判定 | PASS |
| command / status | 630 / 630 |
| active command / status | 13 / 13 |
| sequence対応 | 630 / 630 |
| active対応不一致 | 0 |
| fault | 0 |
| 最大適用強度 | 0.050 |
| challenge age 平均 / p95 / 最大 | 9.93 / 19.10 / 26.13 ms |
| 全command→status 平均 / p95 / 最大 | 4.88 / 8.63 / 28.87 ms |
| active command→status 中央 / p95 / 最大 | 3.82 / 4.33 / 4.47 ms |
| 最終状態 | inactive、faultなし |

全challenge ageは50 msの設定上限内で、active 13件はすべてhardwareへ0.05で適用された。command欠落、status欠落、active対応不一致はなかった。

## 体感とログの対応

### 1. 意図したTTC警告

| pulse | sequence | 開始時刻（試験elapsed） | active frame数 | reason |
|---:|---:|---:|---:|---|
| 1 | 149 | 10.110 s | 3 | `ttc_warning:cadence_triple` |
| 2 | 154 | 10.281 s | 3 | `ttc_warning:cadence_triple` |
| 3 | 159 | 10.452 s | 3 | `ttc_warning:cadence_triple` |

pulse開始間隔は170.8 ms、170.7 msで、操作者が知覚した1組の3連振動と一致する。WARNING要求は0.25、adapter適用値は安全上限の0.05だった。

### 2. 後から感じた短い振動

| 区間 | sequence | 開始時刻（試験elapsed） | active frame数 | reason |
|---:|---:|---:|---:|---|
| 1 | 215–216 | 12.357 s | 2 | `invalid_or_unknown_perception:cadence_triple` |
| 2 | 218–219 | 12.460 s | 2 | `invalid_or_unknown_perception:cadence_triple` |

最初の3連開始から約1.9秒後に`UNKNOWN`通知が始まった。sequence 217で一度CLEARとなり、sequence 218で再びUNKNOWNへ入ったためcadenceが再始動している。2区間の開始間隔は約103 ms、各区間は約2 frameと短く、体感上は一度の「ブルッ」にまとまり得る。

現行`VirtualFfbPolicy`は未知・無効な認識状態をfail-silentにせず、`UNKNOWN`、要求強度0.15、`pulse`としてactiveにする。一方、adapter上限0.05によりWARNING 0.25とUNKNOWN 0.15はいずれも物理出力0.05へ制限される。さらに現在のtriple cadenceは両者へ共通適用されるため、十分長いUNKNOWNでは衝突警告と同じ3連になる可能性がある。

## 結論と次の対応

録画TTC再生によるPC間challenge、FFB command、hardware adapter、G923までの実経路は正常に動作した。意図した3連通知も再現できたため、経路検証の目的は達成した。

カメラ＋模擬ODOM試験へ進む前に、通知の意味を次のように固定することを推奨する。

1. `WARNING`・`CRITICAL`は現在の3連通知を維持する。
2. `UNKNOWN`は衝突警告と区別できる単発通知にするか、物理FFBを無効にしてログ/statusだけへ残す。
3. 方針決定後、録画再生による自動テストとdry-runでWARNINGとUNKNOWNの回数を確認する。
4. 必要な場合だけ停止状態のG923で短い確認を行い、その後にカメラ＋模擬ODOMへ進む。

今回は、通信やhardware異常を理由とする再試験は不要である。
