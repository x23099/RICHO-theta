# 2026-11-26 代表資料：G923 A/Bベンチ・連続cadence・autocenter

今日はA（勾配方向）、B（側ベース）のベンチ、continuous cadence、autocenter 15を実機で確認した。
代表資料はログ要約4点。動画・スクリーンキャストは含めない（元archiveは`~/Downloads`、Git管理外）。

| ファイル | 出典 | 用途 |
|---|---|---|
| [A_r01_summary.json](A_r01_summary.json) | `ffb_A_r01_20261126_153717_062.tar.xz` | A r01。箱左でdirection +1（Aの勾配反転）。0.4の定常36 frameは体感されず、0.25/direction 0の振動を1回。 |
| [bench_r03_summary.json](bench_r03_summary.json) | `bench_r03_20261126_174048_545.tar.xz` | ベンチ0.15（triple cadence）。pattern steadyだがactiveが3〜4 frame ON/OFF（`cadence_gap:triple`）。0.10/0.15で「ドッドッド」。 |
| [B_continuous_path_r01_summary.json](B_continuous_path_r01_summary.json) | `ffb_B_continuous_0.15_test_20261126_191349_683.tar.xz` | B continuous 0.15。最初のCRITICALは箱が青い経路内（1.21 m、direction -1、steady）。最後は箱が真横/経路外でUNKNOWN pulse 0.15。 |
| [B_continuous_autocenter_r01_summary.json](B_continuous_autocenter_r01_summary.json) | `ffb_B_continuous_0.15_test_20261126_202728_979.tar.xz` | B continuous 0.15 + autocenter 15。箱左（x≈-0.42）、direction -1が61 frame、pattern steady 46/hold 26、corridor 63/72。0.15の方向定常は左でも感じず。右が軽いのは逆側で正しい。 |

## 条件

- カメラPC：`matunuc-NUC13ANHi5:~/theta_ws`、`bird_eye`＋relay、B/A config、continuous cadence。
- GPU/ハンコンPC：`hsr-Alienware-m16-R2:~/yopi_ws`、`collision_ffb_node` hardware、`max_magnitude=0.15/0.20`、`autocenter=15`（`ffset`）。
- 駆動：`kobuki_launch_no_ffb_follow.py`（`ffb_follow`を外したローカルlaunch）。`handle`/`twist_mux`/`cmd_vel_mirror`。
- FFB：`oit_interfaces`の`direction`付きへ再ビルド。`bench_mode`/`bench_max_magnitude`、`autocenter`、`direction_enabled`、`constant_direction_sign=1.0`。

## 注意

- 要約は各`detections.csv`から生成。`applied_magnitude`/adapter patternの一部はadapter statusのlive確認による。
- A r01の`pattern`はpublisherの`steady`。direction 0/0.25の体感振動はadapter側のdirection 0パターンと推定。
- bench r03のdirection +1は箱左に対するA（gradient）config相当。Bの側なら-1。B continuousはdirection -1。
- 0.15の方向定常は感じられず、0.20/0.25/0.30の段階試験が必要。0.5は最後の手段。
- カメラ画像は含めない。物理距離・接地・FFB権限の認定ではない。`usable_for_ffb=false`。
