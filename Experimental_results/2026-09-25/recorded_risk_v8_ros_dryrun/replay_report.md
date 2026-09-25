# Recorded collision FFB replay

- 自動判定: **PASS**
- input: `/home/robo25/Downloads/recoding/202609081640.tar.xz`
- session: `approach_center_v0p20_r02_v6holdout_20260908_163811_391`
- replay rate: `30.0 Hz`
- expected output mode: `dry_run`
- freshness mode: `clock`
- physical output acknowledged: `False`
- FFB cadence: `triple` / `0.500 s` / `30.0 Hz`
- UNKNOWN cadence: `single` / `0.100 s`

| 項目 | 値 |
|---|---:|
| command数 | 630 |
| active command数 | 13 |
| status数 | 630 |
| active status数 | 13 |
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
