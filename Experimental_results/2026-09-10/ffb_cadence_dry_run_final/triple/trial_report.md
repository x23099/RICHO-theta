# Collision FFB probe report

- 自動判定: **PASS**
- pattern: `steady`
- cadence: `triple`
- magnitude: `0.050`
- duration: `0.500 s`
- rate: `30.0 Hz`
- expected output mode: `dry_run`

## 集計

| 項目 | 値 |
|---|---:|
| command数 | 18 |
| active command数 | 9 |
| status数 | 18 |
| active apply coverage | 1.000 |
| fault数 | 0 |
| 最大適用強度 | 0.050 |
| 応答時間p95 | 2.477 ms |
| 最終CLEAR停止時間 | 1.129 ms |

## チェック

- PASS: `status_received`
- PASS: `expected_mode_only`
- PASS: `active_apply_coverage`
- PASS: `no_fault`
- PASS: `magnitude_within_limit`
- PASS: `final_clear_observed`
- PASS: `final_inactive`

この判定はROS adapterの状態に対する判定であり、G923の体感強度を自動判定するものではない。
