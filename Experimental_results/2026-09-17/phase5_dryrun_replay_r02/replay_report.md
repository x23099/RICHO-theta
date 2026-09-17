# Recorded collision FFB dry-run replay

- 自動判定: **PASS**
- input: `/home/matunuc/theta_ws/src/recordings/2026-09-17_phase5_live_dryrun/v2/phase5_camera_mock_odom_dryrun_r02_20260917_145834_900/detections.csv`
- session: `phase5_camera_mock_odom_dryrun_r02_20260917_145834_900`
- replay rate: `30.0 Hz`
- FFB cadence: `triple` / `0.500 s` / `30.0 Hz`

| 項目 | 値 |
|---|---:|
| command数 | 1036 |
| active command数 | 9 |
| status数 | 1006 |
| active status数 | 9 |
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
