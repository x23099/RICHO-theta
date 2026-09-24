# Phase 5 challenge方式・hardware probe 0.03 r01診断（2026-09-24）

## 判定

**通信・安全制御・hardware適用経路はPASS。0.03の振動は知覚できなかった。**

challenge方式専用gateを有効にしたhardware adapterが正常起動し、0.03の3連指令9件をすべてhardware出力として適用した。3つのactive区間はそれぞれCLEARで停止し、faultは0件、最後のCtrl+Cでも`shutdown`として停止した。

操作者からは「特に振動は感じなかった」と報告された。したがって0.03は安全な初回確認には使用できたが、危険通知としての知覚強度は不足している。これは以前のclock方式hardware試験で0.03を知覚できなかった結果とも一致する。

## 入力

| 入力 | SHA-256 |
|---|---|
| `phase5_challenge_hardware_probe_0p03_r01.tar.xz` | `9366038c231a54ccc4e3372d68ab405cc342f0d1d015bb6f41dc5bbcf80bcd04` |
| adapter・statusログ | `22196f037625329ba1c347ae44b2c5e1b047952554558a73c0c02f37288e27f3` |

## 起動ゲート

adapter起動ログで次を確認した。

- `mode=hardware`
- `freshness=challenge`
- `challenge hardware gate armed`
- `hardware backend armed`
- watchdog 0.100秒
- 最大適用強度0.03

起動からprobe送信まで意図しないapplyは記録されていない。

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
| 最大適用強度 | 0.030 |
| 応答時間平均 / p95 | 0.830 / 1.036 ms |
| 最終CLEAR応答 | 0.568 ms |

全18 commandは同一の非0 session IDと非0 tokenを持ち、adapterに受理された。archiveにはchallenge発行時刻そのものがないため個々のchallenge ageは再計算できないが、受信側の100 ms期限検証を通過したことは全statusの`fault=false`から確認できる。

## 停止確認

- 各active区間後のCLEARで`action=stop`、`output_active=false`になった。
- 追加CLEARでは`action=none`のinactiveを維持した。
- 終了時は`reason=shutdown`、`output_active=false`、`fault=false`だった。
- ログ上、watchdog fault、期限切れtoken、hardware error、残留activeはない。

## 体感評価

- 0.03の3連振動: 知覚できず
- 通信・適用・停止: ログ上正常
- 危険通知としての採用: 0.03は不可

## 次の作業

既にclock方式で知覚と停止を確認済みの0.05へ上げ、同じchallenge方式・3連・0.5秒・1イベントだけを再試験する。`hardware_initial_test_passed=true`を明示し、それ以外の期限、watchdog、effect長は変更しない。

0.05試験でも急回転、残留力、異音、発熱、意図しないAutocenter変化があれば直ちに中止する。

