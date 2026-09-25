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

## `phase5_v8_warning_raw_frame_0407.png`

- 内容: v8実カメラ・模擬ODOM・PC間dry-runで、WARNINGの3連FFB commandが開始した時点の生カメラ画像。
- 元録画: `phase5_v8_camera_mock_odom_dryrun_r01_20260925_153955_320.tar.xz`内の`raw.avi`。
- session: `phase5_v8_camera_mock_odom_dryrun_r01_20260925_153955_320`
- CSV frame / time: `407` / `13.673189 s`
- 条件: 青箱検出・観測採用、模擬ODOM `0.25 m/s`、TTC `4.1068 s`、risk `WARNING`、FFB sequence `9369`。
- 画像処理: なし。切り抜き、リサイズ、注釈、色調整は行っていない。元解像度`1280×720`のフレームをPNG化した。
- archive SHA-256: `5d60214d91b299d536b915d1aab01fce68cfb4d59e7127fea4a3d5f597cc4c93`
- 画像SHA-256: `8f35c03b1c387ed492fd3ea8e09e7d086f4079bae8f5a6d55a7819175d1b2b2e`

## `phase5_v8_unknown_raw_frame_0502.png`

- 内容: v8実カメラUNKNOWN単発試験で、青箱遮蔽後にUNKNOWN activeが開始した時点の生カメラ画像。
- 元録画: `phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310.tar.xz`内の`raw.avi`。
- session: `phase5_v8_camera_unknown_dryrun_r01_20260925_160415_310`
- CSV frame / time: `502` / `17.322468 s`
- 条件: 青箱未検出、模擬ODOM `0.25 m/s`、risk `UNKNOWN`、FFB sequence `4906`、reason `invalid_or_unknown_perception:cadence_single`。
- 画像処理: なし。切り抜き、リサイズ、注釈、色調整は行っていない。元解像度`1280×720`のフレームをPNG化した。
- archive SHA-256: `dfc8fee1182bcce184186fa883590b5a602129fa674bf352635b41424f62deed`
- 画像SHA-256: `ebab2521e2fefa6220b951b640ebdd67c0fd7cc496d256c23f4817cc9fe9330c`

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

後続の実カメラ試験から、WARNING開始フレームを生画像のまま追加した。
