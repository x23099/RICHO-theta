# 2026-09-29 report assets

録画アーカイブ `rokuga_phase5_v11_reliability_dryrun_r01_20260929_153520_912.tar.xz` 内の `raw.avi` から、そのままPNGへ書き出した無加工フレームである。クロップ、描画、色調補正、リサイズは行っていない。解像度はすべて1280×720。

| ファイル | frame | 録画経過時間 | 用途 | SHA-256 |
|---|---:|---:|---|---|
| `phase5_v11_unknown1_raw_frame_0963.png` | 963 | 32.654 s | 1回目のUNKNOWN発生時 | `32fea78e9f48f6342d86b3d6e616e4a12945441cabd2f3005594cf2a0a5d1e2b` |
| `phase5_v11_unknown2_raw_frame_1069.png` | 1069 | 36.188 s | 再arm後の2回目のUNKNOWN発生時 | `2c509b7ab6c6d25f198085998be62913f1872c26ca0a3b852cf4cb434b33f145` |
| `phase5_v11_short_return_raw_frame_1104.png` | 1104 | 約37.36 s | 青色が短時間だけ戻った場面。再armされないことの確認用 | `27cac8fbf384bcbb806eac161fbcd72a214c13720ece6df931bb8de1b18d2c80` |
| `phase5_v11_rearmed_warning_raw_frame_1161.png` | 1161 | 39.256 s | 有効測定復帰後のWARNING発生時 | `eee088584d4ecb6f151bbbd60615748b92f4e106c605e065aaee864475678512` |

画像は成果報告資料へ使用できるが、判定根拠は各CSVおよび `phase5_v11_reliability_dryrun_r01_diagnosis.md` を参照すること。

## v12 reliability dry-run

録画アーカイブ `rokuga_phase5_v12_reliability_dryrun_r01_20260929_162234_202.tar.xz` の `raw.avi` から、元解像度のままPNGへ書き出した無加工フレームである。

| ファイル | frame | 録画経過時間 | 内容 | SHA-256 |
|---|---:|---:|---|---|
| `phase5_v12_warning_raw_frame_0305.png` | 305 | 10.142 s | 青箱を正面に置いたWARNING発生時 | `e06882866804e91aa3a03d6035eba8a957605483a4c4e78a2451abd747792c4f` |
| `phase5_v12_unknown1_raw_frame_0367.png` | 367 | 12.208 s | 黒い遮蔽物で青箱を隠し、1回目のUNKNOWNが発生した場面 | `320d226c42650b0808c1a5422171dbfa7aa6f02d1279a4d21c6368898784e33a` |
| `phase5_v12_recovered_warning_raw_frame_0433.png` | 433 | 14.434 s | 青箱を再び見せ、有効測定とWARNINGへ復帰した場面 | `ff5e61973d1f694583c16cbd2c681c60e47e1aaafdfd23de791993d43abb0729` |
| `phase5_v12_unknown2_raw_frame_0730.png` | 730 | 24.307 s | 再arm後に再び遮蔽し、2回目のUNKNOWNが発生した場面 | `883f838ef0070292244f9ec34147c691fd94938d5f2ea862b481a74004fa8d5a` |

v12の詳細判定は `../phase5_v12_reliability_dryrun_r01_diagnosis.md` を参照すること。

## v12 hardware UNKNOWN

録画アーカイブ `rokuga_phase5_v12_hardware_unknown_r01_20260929_184546_956.tar.xz` の `raw.avi` から、元解像度のままPNGへ書き出した無加工フレームである。

| ファイル | frame | 録画経過時間 | 内容 | SHA-256 |
|---|---:|---:|---|---|
| `phase5_v12_hardware_unknown_raw_frame_0556.png` | 556 | 19.127 s | 黒い遮蔽物で青箱を隠し、実機UNKNOWN単発が始まった場面 | `41b901f0e8cd699593446ec816eab7d4bbf23b0590d641375d92be4edf0eae80` |
| `phase5_v12_hardware_recovery_raw_frame_0617.png` | 617 | 21.117 s | 青箱を再び見せ、有効測定とWARNINGへ復帰した場面 | `08a26fb5c4a1cfb8ed6e98037b3e6b96f5f1d7212a0d982f69bdf994d9ce5328` |

hardware UNKNOWN試験の判定は `../phase5_v12_hardware_unknown_r01_diagnosis.md` を参照すること。
