# 2026-11-21 代表資料

日報 [2026-11-21_daily_report.md](../../../Daily_reports/2026-11-21_daily_report.md) の図表。保存済みarchiveとJSONから再生成できる。

## 1. roi_coverage.csv / .png

- 内容：黄色コーンS=170で、ROI 270..350（80 px）とROI 150..450（300 px）の**数値率**を距離帯ごとに比較。
- 出典：`recordings/2026-11-21/yellow_grid_intake_r01/yellow_grid_s170_20261121_r01.tar.xz`（9枚）と`yellow_grid_wide_s170_20261121_r01.tar.xz`（10枚）のsamples.jsonl。
- 位置の割り当て：撮影順に「1.0 m 3枚、1.5 m 3枚、2.0 m 4枚（重複1）」として数値/保留を数えた。**撮影順は操作者申告で、archive内に位置ラベルはない。**
- 狭いROI：1.0 m 33%、1.5 m 33%、2.0 m 100%。広いROI：1.0 m 67%、1.5 m 100%、2.0 m 100%。

## 2. gradient_dry_run.csv / .png

- 内容：実測距離（中央・左右25 cm × 1.0/1.5/2.0 m）を使った勾配の、yawに対する符号。速度0.4 m/s。点線はデッドバンド±0.1。
- 出典：`Experimental_results/2026-11-21/gradient_dry_run_r01/results_r01/dry_run.json`。
- 図は3位置（1.0 m左、1.5 m右、2.0 m左）を抜粋。**同じ側へ切ったyawで符号が反転**する例が読める。
- 全120評価の内訳：デッドバンド内71、側期待と符号逆13、±1 cm揺れで方向変化4。

## 再生成

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-21/report_assets/make_assets.py
```

matplotlib 3.10.6。カメラ画像は使用していない（当日の代表画像は別途保存していない）。
