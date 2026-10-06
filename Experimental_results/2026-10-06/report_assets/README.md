# 2026-10-06 成果報告用画像

カメラの`raw.avi`から元解像度1280×720のフレームをPNGとして保存した。注釈、合成、切り抜き、リサイズ、色・明るさ補正は行っていない。

| ファイル | 録画 | frame | 録画経過 | 内容 |
|---|---|---:|---:|---|
| `phase5_v12_live_warning_raw_frame_0309.png` | `phase5_v12_live_kobuki_dryrun_r01_20261006_135700_661` | 309 | 10.285秒 | TTC WARNING成立およびtriple cadence開始時 |
| `phase5_v12_live_stop_raw_frame_0337.png` | 同上 | 337 | 11.297秒 | 停止完了直後、CLEAR復帰時 |
| `phase5_v12_live_hardware_warning_raw_frame_0372.png` | `phase5_v12_live_kobuki_hardware_r01_20261006_143236_125` | 372 | 12.390秒 | 実走行hardwareでTTC WARNINGと物理FFBが成立した時点 |
| `phase5_v12_live_hardware_stop_raw_frame_0396.png` | 同上 | 396 | 13.190秒 | hardware走行の停止完了直後、CLEAR状態 |

定量判定は`../phase5_v12_live_kobuki_dryrun_r01_diagnosis.md`、`../phase5_v12_live_kobuki_hardware_r01_diagnosis.md`と各CSV/JSONを参照すること。
