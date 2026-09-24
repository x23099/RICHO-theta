# 2026-09-24 成果報告用資料

## `raw_phase5_challenge_reception_diag_r01_frame_000466.png`

- 内容: 模擬ODOM 0.25 m/s区間に近い、生カメラ映像の元解像度フレーム。正面に青箱が写る一方、画面全体が青へ偏っている。
- 元録画: `/home/robo25/Downloads/phase5_challenge_reception_diag_r01_20260924_161045_968.tar.xz`
- session: `phase5_challenge_reception_diag_r01_20260924_161045_968`
- member: `raw.avi`
- frame: 466（1始まり）、動画内時刻約15.5秒
- 解像度: 1280x720
- SHA-256: `d84eac6a3467bbcbf52b2f85bc8949da0ec6eb555ad5c7793de1ac71638a031b`
- 編集: なし。切り抜き、注釈、色補正、リサイズなし。

## `challenge_delivery_vs_camera_skip.png`

- 内容: Kobuki側bagで受信した1秒ごとのchallenge件数と、同じ時間帯のカメラ側FFB送信見送り率。
- 元データ: `../phase5_challenge_kobuki_r01_events.csv`と上記録画内`detections.csv`。
- 見方: challengeは約50件/秒で届き続ける一方、カメラ側では長い区間で全フレームを見送っている。
- 生成: `src/create_phase5_20260924_report_assets.py`。

再生成例:

```bash
python3 src/create_phase5_20260924_report_assets.py \
  --detections /path/to/extracted/session/detections.csv \
  --events Experimental_results/2026-09-24/phase5_challenge_kobuki_r01_events.csv \
  --output Experimental_results/2026-09-24/report_assets/challenge_delivery_vs_camera_skip.png
```
