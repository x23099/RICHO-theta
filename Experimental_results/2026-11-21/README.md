# 2026-11-21 実験手順：下辺接触フォールバックと N≥30 のVP8比較

## 目的

1. **① 下辺接触**：`bottom_extension_probe`のguarded候補をobserverへ足したとき、f044793型の「下辺接触で保留」が安全条件を保ったまま数値化できるか。
2. **② N≥30**：同一sessionの連続30 frameで、元画像とVP8 packetの距離差・gate反転率・下辺フォールバックの効果を測る。

どちらもGPUPCのオフライン比較。機体は停止、カメラは固定、G923/ROS/FFBは使わない。

## 0. 事前確認（GPUPC）

```bash
cd /home/hsr/yopi_ws/RICHO-theta
ls -l Experimental_results/2026-11-21/cones_vp8_suite_r01/prepare_manifest.py \
      Experimental_results/2026-11-21/cones_vp8_suite_r01/run_with_manifest.py \
      Experimental_results/2026-11-10/bottom_extension_probe_r01/probe.py
./yolo-env/bin/python3 -c "import torch,cv2,av;print(torch.cuda.is_available())"
```

`True`でなければ実行しない（CPU fallbackなし）。重みは `/home/hsr/Downloads/cone_distance_v03.pt`。

## 0.5 黄色コーンしかない場合（重要）

**検出器は単一クラス`traffic_cone`で、赤・黄色の両方を学習対象にしている。** 色分離の支持点もHSVで赤・黄色の両方を扱い、seed領域で優勢な色（≥90%）を選ぶ。**赤専用ではない。**

ただし、**距離・gate・完了処理の最近の検証はすべて赤コーン**（保存4枚も赤）。黄色には既知のリスクがある。

- 黄色HSVの下限S=80は、ベージュ/木目床（実測Hue≈18, S≈81〜83）を拾い、床とコーンのmaskが連結する（10/30に発生）。
- seedに赤と黄色が混在すると`ambiguous_upper_body_colour`（優勢率<90%）で保留になる。
- 黄色で距離が数値化された実績が、現行gate条件では未確認。

### 2 frame予備確認（30 frame採取の前に必ず）

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-21/cones_vp8_suite_r01/prepare_manifest.py \
  --input-dir recordings/2026-11-21/yellow_precheck_frames_r01 \
  --roi 270 0 350 720 \
  --output recordings/2026-11-21/yellow_precheck_manifest_r01.json
./yolo-env/bin/python3 Experimental_results/2026-11-21/cones_vp8_suite_r01/run_with_manifest.py \
  --manifest recordings/2026-11-21/yellow_precheck_manifest_r01.json -- \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount --repetitions 1 --warmup 1 \
  --output-dir recordings/2026-11-21/yellow_precheck_run_r01 \
  --archive /home/hsr/Downloads/yellow_precheck_20261121_r01.tar.xz
./yolo-env/bin/python3 Experimental_results/2026-11-21/cones_vp8_suite_r01/inspect_samples.py \
  --samples /home/hsr/Downloads/yellow_precheck_20261121_r01.tar.xz
```

判定：

| 表示 | 判断 |
|---|---|
| `colour=yellow`で`distance`が数値 | そのまま30 frame採取へ進む |
| `colour=yellow`だが`colour_contour_reaches_roi_edge` | ROI/構図を調整（端に触れない）。下辺接触なら①フォールバックの対象 |
| `ambiguous_upper_body_colour` | seedに他色が混入。背景・照明・コーン位置を変える |
| `support_not_connected_to_body_seed` | 床や別物体とmaskが連結。ベージュ床を避ける／白・灰色の背景にする |
| `colour=red`または`None` | 色選択が意図と違う。コーンと照明を確認 |

黄色で予備確認が通らない場合、**無理に進めず**、赤コーンが使えるか、背景（ベージュ床を避ける）を変えるかを選ぶ。数値を出すためにHSV閾値やROIをその場で調整しない。

## 1. フレーム採取（カメラのみ・機体停止）

コーンを**これまでと同じ画角**（front-left画像のx≈290〜330に写る位置）へ置く。ROIは`270 0 350 720`を使うため、**コンターがROI端に触れない**構図にする。

距離を3段階（例 1.0 / 1.5 / 2.0 m）、各10 frame、合計30 frameを保存する。

```bash
# matsunuc: 診断送信
cd /home/matunuc/theta_ws
bash src/start_theta_stream_rtc.sh --diagnostic --receiver-ip 150.89.169.96 --device /dev/video0 --fps 30
```

```bash
# GPUPC: 診断受信（Sキーで未注釈1280x720を保存）
cd /home/hsr/yopi_ws/RICHO-theta
bash src/start_theta_receive_rtc.sh --diagnostic \
  --output-dir recordings/2026-11-21/vp8_suite_frames_r01 \
  --duration-sec 300
```

- 表示の`S`キーで1 frame保存。距離を変えながら**30回**押す。
- `received_frames.csv`に受信frameが残る。PNGは`decoded_<session>_f<frame>.png`。
- 同じframeは二重保存できない。押しすぎたら次frameを待つ。
- 保存後、1枚を開いてコーンがROI内に収まっていることを確認する。

## 2. manifest作成（GPUPC）

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-21/cones_vp8_suite_r01/prepare_manifest.py \
  --input-dir recordings/2026-11-21/vp8_suite_frames_r01 \
  --roi 270 0 350 720 \
  --output recordings/2026-11-21/vp8_suite_manifest_r01.json
```

`images: 30`程度になること。SHA・1280x720・重複を検査し、不正なら停止する。

## 3. 比較実行（GPUPC、2run）

### 3.1 フォールバックなし（基準）

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-21/cones_vp8_suite_r01/run_with_manifest.py \
  --manifest recordings/2026-11-21/vp8_suite_manifest_r01.json -- \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount \
  --output-dir recordings/2026-11-21/vp8_suite_nofb_r01 \
  --archive /home/hsr/Downloads/vp8_suite_nofb_20261121_r01.tar.xz
```

### 3.2 下辺フォールバックあり

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-21/cones_vp8_suite_r01/run_with_manifest.py \
  --manifest recordings/2026-11-21/vp8_suite_manifest_r01.json --bottom-fallback -- \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount \
  --output-dir recordings/2026-11-21/vp8_suite_fb_r01 \
  --archive /home/hsr/Downloads/vp8_suite_fb_20261121_r01.tar.xz
```

各runで `state: complete`、`image_count: 30`、`paired_samples: 300` を確認する（5反復×2 variant×30枚）。

## 4. 提出

- `vp8_suite_nofb_20261121_r01.tar.xz`
- `vp8_suite_fb_20261121_r01.tar.xz`
- 各出力先の `manifest_run.json`（harness/runner/manifest SHAと引数）
- `vp8_suite_manifest_r01.json`

## 5. 判定

| 見る点 | 合格の目安 |
|---|---|
| 元画像の保留率 | フォールバックなしで下辺接触の保留が残る（基準） |
| フォールバックの適用数 | f044793型だけが数値化し、**元のlower support・点が保存**されている |
| 距離差（元−packet） | 中央値と最大を記録。±3 cmを超える外れ値の有無 |
| gate反転率 | 30 frame中、保留↔数値が変わる枚数 |
| 再現性 | 同一frame・同一variantで距離・理由が一致 |

フォールバック適用時も`floor_contact_verified=false`、`controlling_distance=false`、`usable_for_ffb=false`のまま。数値が出たことを接地や精度の認定にしない。

## 6. 失敗時の切り分け

- `state`が`failed`：tracebackとsummaryを保存し、同じ出力先へ再実行しない。原因確認後`r02`。
- `image_count`が30未満：manifestの`images`数を確認。足りなければ追加採取。
- 元画像の保留が多い：ROIが端に触れている。ROIを広げるか構図を変えて再採取（ROIを変えたら別manifest名にする）。
- CUDA不可：停止。driver/依存を変更しない。

## 7. 注意

- 機体は停止。走行・G923出力・ROS送信は行わない。
- 診断受信は`INTAKE ONLY`（距離なし）。保存PNGは**カメラ原画ではなく復号RTP frame**で、生パイプラインの入力と同じ。
- 追加のYOLO学習・モデル変更・閾値調整はしない。
