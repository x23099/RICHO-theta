# 完了bbox許容の比較試験 r01（2026-11-20）

> **結果：[results_r01.md](results_r01.md)。** t1でf028980の元画像だけが数値化（1.5834 m / packet 1.6108 m、差2.74 cm）。f044793の下辺接触は残り、gate反転は2件→1件。

## 目的

11/18の保存画像で、**元画像の保留が「完了点が元bboxの外」という0.8 px差で拒否されていた**ことを確認した（[VP8評価](../vp8_packet_assessment_r01/README.md) 4.1節）。今回、その1条件だけに明示的な許容（0〜8 px）を与えたとき、保留gateの反転が解消するかを実GPUで確かめる。

比較するのは同一sessionの連続3枚で、`--tolerance-px 0`（従来）と`1`（0.8 px差を吸収する最小値）。

## 何を変えるか（パイプライン本体は不変）

既存のGPU runnerと`src/`は**1バイトも変更しない**。過去のmanifest・回帰guardをそのまま保つため、許容は実験用harness `run_tolerance.py` で**後処理**として与える。

- 元のobserverをそのまま呼ぶ。
- 戻り値が`completion_reason="completed_point_outside_original_bbox"`のときだけ、**画素support・成分・2 context一致など既存の全検査を通った後**の最後のbbox比較を、指定pxだけ緩めて再評価する。
- それ以外の失敗理由（下辺接触など）は一切変更しない。
- 変更したことを`completion_reason="experiment_bbox_tolerance_applied"`と`tolerance_harness.json`へ記録する。
- `controlling_distance` / `physical_metric_verified` / `floor_contact_verified` / `usable_for_ffb` はfalseのまま。

harnessのSHA、元runnerのSHA、引数、許容値は出力先の`tolerance_harness.json`に残る。

## 前提

- GPUPCに今回のharnessをGitで反映済みであること。
- GPUPCのPythonは`./yolo-env/bin/python3`、重みは`/home/hsr/Downloads/cone_distance_v03.pt`。
- 入力は11/13保存の3枚（SHA allowlist済み）。追加撮影・走行・カメラ・ROS・G923は不要。
- 実行中は他のGPU/受信処理を起動しない。

## 実行（GPUPC）

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-20/bbox_tolerance_sweep_r01/run_tolerance.py \
  --tolerance-px 0 -- \
  --image recordings/2026-11-13/guarded_motion_evidence_r02/decoded_24aad0a8d31d46eeb33ef252b0d18475_f028980.png \
  --image recordings/2026-11-13/guarded_motion_evidence_r02/decoded_24aad0a8d31d46eeb33ef252b0d18475_f037696.png \
  --image recordings/2026-11-13/guarded_motion_evidence_r02/decoded_24aad0a8d31d46eeb33ef252b0d18475_f044793.png \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount \
  --target-roi 270 0 350 720 \
  --output-dir recordings/2026-11-20/bbox_tolerance_t0_r01 \
  --archive /home/hsr/Downloads/bbox_tolerance_t0_20261120_r01.tar.xz
```

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-20/bbox_tolerance_sweep_r01/run_tolerance.py \
  --tolerance-px 1 -- \
  --image recordings/2026-11-13/guarded_motion_evidence_r02/decoded_24aad0a8d31d46eeb33ef252b0d18475_f028980.png \
  --image recordings/2026-11-13/guarded_motion_evidence_r02/decoded_24aad0a8d31d46eeb33ef252b0d18475_f037696.png \
  --image recordings/2026-11-13/guarded_motion_evidence_r02/decoded_24aad0a8d31d46eeb33ef252b0d18475_f044793.png \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --experimental-rigid-mount \
  --target-roi 270 0 350 720 \
  --output-dir recordings/2026-11-20/bbox_tolerance_t1_r01 \
  --archive /home/hsr/Downloads/bbox_tolerance_t1_20261120_r01.tar.xz
```

各runで `state: complete`、`image_count: 3`、`paired_samples: 10` を確認する。既存出力先へ再実行しない。失敗時は原因確認後に`r02`へ変える。

## 提出

- `/home/hsr/Downloads/bbox_tolerance_t0_20261120_r01.tar.xz`
- `/home/hsr/Downloads/bbox_tolerance_t1_20261120_r01.tar.xz`
- 各runの出力先にある `tolerance_harness.json`（2点）。archiveはrunnerが先に作るため、harnessの記録は別途提出する。

`tolerance_harness.json` には許容px、harness SHA、元runner SHA、runner引数が入る。これが無いと、どのrunにどの許容を適用したか監査できない。

## 期待と判定

| 画像 | t0（従来） | t1（予測） |
|---|---|---|
| f028980 元画像 | 保留（完了点 y=385 が bbox y2=384.2027 の外、0.8 px） | **数値**（許容1 pxで受理） |
| f028980 packet | 数値 | 数値（変化なし） |
| f037696 元/packet | 保留/保留 | 変化なし（下辺接触で完了対象外） |
| f044793 元 | 保留（下辺接触） | **変化なし**（対象外） |
| f044793 packet | 数値 | 数値 |

- t1でf028980の元画像が数値化し、その距離がpacket側と一致すれば、**0.8 pxの境界差**だったと確認できる。
- f044793が残る場合、下辺接触は別課題（下方向の余白・完了条件）として切り分ける。
- この結果で「VP8で距離判断が安定する」とは認定しない。ROI検証・N増加・時間方向の一致は別途。
