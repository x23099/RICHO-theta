# Phase 5 challenge方式・hardware probe 0.05 r01診断（2026-09-24）

## 判定

**PASS。challenge方式のhardware経路、3連通知の知覚、CLEAR・shutdown停止を確認した。**

adapterはchallenge＋hardware専用gateを有効にして起動し、0.05の3連指令9件をすべてG923へ適用した。操作者は3回の振動を明確に知覚できた。各active区間はCLEARで停止し、faultは0件、終了時も`shutdown`でinactiveになった。

## 入力と命名上の注意

| 入力 | SHA-256 |
|---|---|
| `phase5_challenge_hardware_probe_0p03_r02.tar.xz` | `cf05dcfc5672642871ba5d92daec6536441d91cf6399bac92db79cac2ff71ce6` |
| adapter・statusログ | `17ce07e3eb56f27e7761de88339fe47b9f2617bfedb3690f5b56860501c29870` |

archive名と内部フォルダ名は`0p03`だが、`trial_summary.json`、command、status、adapter起動ログはすべて0.05を示している。解析結果は実際の条件に合わせて`phase5_challenge_hardware_probe_0p05_r01`として保存した。

## 実験条件

| 項目 | 値 |
|---|---:|
| output mode | hardware |
| freshness mode | challenge |
| challenge hardware gate | armed |
| hardware initial test | passed |
| 最大強度 | 0.05 |
| challenge最大age | 0.05秒 |
| watchdog | 0.10秒 |
| effect長 | 120 ms |
| cadence | triple |
| probe時間 | 0.5秒 |
| 送信rate | 30 Hz |

challenge期限は計画上限100 msより厳しい50 msで実行され、全commandが受理された。

## probe集計

| 項目 | 結果 |
|---|---:|
| 自動判定 | PASS |
| command / status | 18 / 18 |
| active command | 9 |
| matched active sequence | 9/9 |
| active apply coverage | 1.000 |
| active区間 | sequence 0–2、5–7、10–12 |
| CLEAR停止 | sequence 3、8、13 |
| fault | 0 |
| 最大適用強度 | 0.050 |
| 応答時間平均 / p95 | 0.890 / 1.175 ms |
| 最終CLEAR応答 | 0.786 ms |

全18 commandは同一の非0 session IDと非0 tokenを持ち、adapter側のchallenge期限検証を通過した。active要求・適用値はすべて0.05で一致した。

## 体感・停止評価

- 3連振動: 明確に3回と知覚できた
- active中: `output_mode=hardware`、`action=apply`、`output_active=true`
- 各区間終了: CLEARで即時STOP
- probe終了: inactiveを維持
- node終了: `reason=shutdown`、`output_active=false`、`fault=false`
- ログ上の残留active、watchdog fault、期限切れtoken、hardware error: なし

## 結論と次段階

0.05・3連をchallenge方式の停止状態hardware通知条件として採用できる。0.03は知覚できず、0.05は明確に知覚できたため、現行上限0.05を維持し、これ以上強くしない。

次は同じ0.05上限と安全ゲートを維持し、手動probeではなく録画済みTTCリスク列をPC間で1イベントだけ再生する。その後、Kobuki停止・模擬ODOMでカメラ→TTC→command→G923の経路へ進む。走行試験はまだ行わない。

