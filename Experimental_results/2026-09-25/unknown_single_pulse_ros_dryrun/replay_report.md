# Recorded collision FFB replay

- 自動判定: **PASS**
- input: `/tmp/ffb_distinct_cadence_fixture.csv`
- session: `tmp`
- replay rate: `30.0 Hz`
- expected output mode: `dry_run`
- freshness mode: `clock`
- physical output acknowledged: `False`
- FFB cadence: `triple` / `0.500 s` / `30.0 Hz`
- UNKNOWN cadence: `single` / `0.100 s`

| 項目 | 値 |
|---|---:|
| command数 | 46 |
| active command数 | 12 |
| status数 | 46 |
| active status数 | 12 |
| fault数 | 0 |
| 最大適用強度 | 0.050 |

## チェック

- PASS: `all_commands_published`
- PASS: `status_received`
- PASS: `expected_mode_only`
- PASS: `no_fault`
- PASS: `active_path_observed`
- PASS: `adapter_cap_respected`
- PASS: `final_inactive`

本結果は、録画済みriskからCollisionFfbPublisherBridge、ROS topic、dry-run adapter、status記録までを対象とする。G923物理出力は行わない。
