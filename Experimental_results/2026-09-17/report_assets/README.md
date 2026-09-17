# 2026-09-17 成果報告用グラフ

## `challenge_availability_r06.png`

- 内容: r06録画中の1秒ごとのFFB送信見送り率、WARNING区間、実際に出たactive指令の位置。
- 元データ: `/home/robo25/Downloads/202609171821.tar.xz` 内の `phase5_challenge_camera_mock_odom_r01_20260917_181900_391/detections.csv`。
- SHA-256: 録画アーカイブ `f664cef4e639a3512fde36ca96604792165e05476b4b351ab2909258079feea4`。
- 注意: 「送信見送り」は `collision_ffb_publish_success=0` であり、ハンコン側がchallengeを発行していなかったことを意味しない。

## `active_command_status_comparison.png`

- 内容: r03、r05、r06におけるハンコン接続PCのbag上のactive指令数と、adapterがactiveとしたstatus数。
- 元データ: 同日フォルダの `phase5_live_dryrun_r03_bag_summary.json`、`phase5_live_r05_bag_summary.json`、`phase5_challenge_live_r06_bag_summary.json`。
- 注意: r03とr06はdry-run、r05はhardwareモードだが時刻検査で拒否された。棒の数は振動の体感強度ではない。

両グラフは無加工の生カメラ画像ではなく、集計値の可視化である。再生成コマンド:

```bash
python3 src/create_phase5_20260917_report_assets.py \
  --camera-archive /home/robo25/Downloads/202609171821.tar.xz
```
