# 2026-09-24 成果報告用資料

## `raw_phase5_callback_fix_dryrun_r02_active.png`

- 内容: callback修正後r02のWARNING/FFB active区間における生カメラ映像。正面の青箱と実験環境を確認できる。
- 元録画: `/home/robo25/Downloads/phase5_callback_fix_dryrun_r02_20260924_172351_631.tar.xz`
- session: `phase5_callback_fix_dryrun_r02_20260924_172351_631`
- member: `raw.avi`
- 動画内時刻: 約16.2秒
- 解像度: 1280x720
- SHA-256: `9e34a988ee336af9f645b065f87658feb5b09813ef28ead219a2c924a5cb0ce7`
- 編集: なし。切り抜き、注釈、色補正、リサイズなし。

## `callback_health_and_ffb_r02.png`

- 内容: challenge age、送信側60 ms期限、FFB activeフレーム、録画開始後のchallenge受信累計を表示。
- 結果: ageは全897フレームで60 ms未満。受信累計は理想50 Hz線と重なり、停止区間がない。
- 元データ: 上記r02録画内`detections.csv`。
- 生成: `src/create_phase5_callback_fix_assets.py`。
- SHA-256: `16e618dbb8665e24f923b3a3a76ce4b84d54752ccb3297c60d6c0aaf73529db6`

再生成例:

```bash
python3 src/create_phase5_callback_fix_assets.py \
  --input /path/to/phase5_callback_fix_dryrun_r02.tar.xz \
  --output Experimental_results/2026-09-24/report_assets/callback_health_and_ffb_r02.png
```

## `raw_phase5_callback_fix_dryrun_r01_motion.png`

- 内容: callback修正後r01の0.25 m/s模擬ODOM区間における生カメラ映像。正面の青箱と実験環境が確認でき、前回の画面全体の青偏りはない。
- 元録画: `/home/robo25/Downloads/phase5_callback_fix_dryrun_r01_20260924_170947_310.tar.xz`
- session: `phase5_callback_fix_dryrun_r01_20260924_170947_310`
- member: `raw.avi`
- 動画内時刻: 約11.5秒
- 解像度: 1280x720
- SHA-256: `75d74d1571b964551971563dea84d9e756d6b16c9a018350bbf4d2256afb61de`
- 編集: なし。切り抜き、注釈、色補正、リサイズなし。

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
