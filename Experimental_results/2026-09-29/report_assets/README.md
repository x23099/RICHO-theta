# 2026-09-29 report assets

録画アーカイブ `rokuga_phase5_v11_reliability_dryrun_r01_20260929_153520_912.tar.xz` 内の `raw.avi` から、そのままPNGへ書き出した無加工フレームである。クロップ、描画、色調補正、リサイズは行っていない。解像度はすべて1280×720。

| ファイル | frame | 録画経過時間 | 用途 | SHA-256 |
|---|---:|---:|---|---|
| `phase5_v11_unknown1_raw_frame_0963.png` | 963 | 32.654 s | 1回目のUNKNOWN発生時 | `32fea78e9f48f6342d86b3d6e616e4a12945441cabd2f3005594cf2a0a5d1e2b` |
| `phase5_v11_unknown2_raw_frame_1069.png` | 1069 | 36.188 s | 再arm後の2回目のUNKNOWN発生時 | `2c509b7ab6c6d25f198085998be62913f1872c26ca0a3b852cf4cb434b33f145` |
| `phase5_v11_short_return_raw_frame_1104.png` | 1104 | 約37.36 s | 青色が短時間だけ戻った場面。再armされないことの確認用 | `27cac8fbf384bcbb806eac161fbcd72a214c13720ece6df931bb8de1b18d2c80` |
| `phase5_v11_rearmed_warning_raw_frame_1161.png` | 1161 | 39.256 s | 有効測定復帰後のWARNING発生時 | `eee088584d4ecb6f151bbbd60615748b92f4e106c605e065aaee864475678512` |

画像は成果報告資料へ使用できるが、判定根拠は各CSVおよび `phase5_v11_reliability_dryrun_r01_diagnosis.md` を参照すること。
