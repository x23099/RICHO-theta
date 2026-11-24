# 2026-11-24 代表資料：G923 M/A/B FFB実験

今日はG923の実機でM（大きさのみ）/B（側ベース）を実施した。A（勾配方向）は未実施。
代表資料はログ要約3点で、動画は含めない（元archiveは各345 MB程度で`~/Downloads`にあり、Git管理外）。

| ファイル | 出典 | 用途 |
|---|---|---|
| [M_r012_summary.json](M_r012_summary.json) | `~/Downloads/ffb_M_r012_20261124_193913_440.tar.xz` の`detections.csv` | Mの代表run。active 109、WARNING 49、CRITICAL 60、requested 0.4が27 frame、direction 0。振動は体感3。 |
| [B_r03_summary.json](B_r03_summary.json) | `~/Downloads/ffb_B_r03_20261124_201259_417.tar.xz` の`detections.csv` | Bの代表run。箱は左、active 97、direction -1が29 frame、requested 0.4が29 frame。方向の重さは体感されず。 |
| [ffb_chain_active_check.txt](ffb_chain_active_check.txt) | 2PCでの`ros2 topic echo`の手控え | `ffb_command active 0.4/direction 1`と`ffb_status applied 0.05/pattern 1/output_active true`。force pathが通った証拠。 |

## 条件

- カメラPC：`matunuc-NUC13ANHi5`、`~/theta_ws`、`bird_eye`＋relay（v12 baseから生成したM/B config）。
- ハンコンPC：`hsr-Alienware-m16-R2`、`~/yopi_ws`、`collision_ffb_node` hardware、`max_magnitude=0.05`。
- 駆動：`ros2 launch oit kobuki_launch.py`。`handle`単体では動かない。
- 箱：前方1.2〜1.3 m、速度0.35〜0.49 m/s。Mは中央・操舵なし。Bは左0.1〜0.2 m・箱側へ短く操舵。
- FFB adapter：再ビルド後の`oit_interfaces`（`int8 direction`あり）。Bでは`direction_enabled=true`、`constant_direction_sign=1.0`。

## 注意

- M r012の要約は`detections.csv`から生成。`applied_magnitude`/`pattern`はadapter statusの別途live確認による。
- Mの`pattern=3`（振動）は、liveのUNKNOWN/direction 0のstatusと体感からの推定。Mのstatusを全frameで記録したわけではない。
- B r03の`applied 0.05/pattern 1`は、別のB接近時のlive status（direction +1、箱は右）で確認した。B r03は箱左でdirection -1。符号は箱の側に従う。
- カメラ画像は含めない。`raw.avi`/`detection.avi`/`bev.avi`はarchive内にあり、日報の数値根拠は`detections.csv`。
- 物理距離・接地・FFB権限の認定ではない。`usable_for_ffb=false`。
- Aは未実施。評定は[record_2026-11-24.csv](../ffb_policy_comparison_r01/record_2026-11-24.csv)にまとめた。
