# Recorded collision FFB dry-run replay

- 自動判定: **PASS**
- input: `/home/robo25/Downloads/recoding/202609081640.tar.xz`
- session: `approach_center_v0p20_r02_v6holdout_20260908_163811_391`
- replay rate: `30.0 Hz`

| 項目 | 値 |
|---|---:|
| command数 | 630 |
| active command数 | 69 |
| status数 | 630 |
| active status数 | 69 |
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

本結果は、録画済みriskから`CollisionFfbPublisherBridge`、ROS topic、dry-run adapter、
status記録までを対象とする。映像認識の再計算とG923物理出力は行っていない。
