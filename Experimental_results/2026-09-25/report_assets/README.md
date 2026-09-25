# 2026-09-25 成果報告用資料

## `synthetic_warning_unknown_cadence.png`

- 内容: 30 Hzの合成riskに対するpublisher要求値とdry-run adapter適用値。
- 入力: CLEAR 5、WARNING 15、CLEAR 5、UNKNOWN 15、CLEAR 5フレーム。
- 結果: WARNINGは0.25要求の3連、UNKNOWNは0.15要求の単発。adapterはいずれも上限0.05を適用。
- 元データ: `../unknown_single_pulse_ros_dryrun/replayed_commands.csv`および`adapter_status.csv`。
- SHA-256: `d76d333d39ffc9ee50cc729a321b8b67d0a4514cc313e9c8e10768c5375cb0ac`

## `recorded_risk_v8_dryrun.png`

- 内容: 9月8日の0.20 m/s接近r02を新しいUNKNOWN単発仕様で再生した要求値とdry-run adapter適用値。
- 結果: 約5秒地点にWARNINGの3連、約7.2秒地点に短いUNKNOWN通知が現れる。faultは0。
- 元データ: `../recorded_risk_v8_ros_dryrun/replayed_commands.csv`および`adapter_status.csv`。
- 元archive: `/home/robo25/Downloads/recoding/202609081640.tar.xz`。
- archive SHA-256: `7a38ec860b9bf5af3ef380332582ed154c4ca5dad4b12c44b4f38485e20facf7`
- 画像SHA-256: `017abf593ebeebc461776807229ae77ace9936ad3903f553096890b1d0a0f6bf`

## 再生成

両グラフは既存の`src/create_ffb_report_assets.py`にある`plot_replay`を使用した。再生成例:

```bash
PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from create_ffb_report_assets import plot_replay

output = Path("Experimental_results/2026-09-25/report_assets")
plot_replay(
    Path("Experimental_results/2026-09-25/unknown_single_pulse_ros_dryrun"),
    output / "synthetic_warning_unknown_cadence.png",
)
plot_replay(
    Path("Experimental_results/2026-09-25/recorded_risk_v8_ros_dryrun"),
    output / "recorded_risk_v8_dryrun.png",
)
PY
```

本日は新しいカメラ録画を行っていないため、生カメラ画像は追加していない。
