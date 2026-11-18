# GPUPC：別の既存3画像を一括比較

**11/16 pin5186の1枚予備確認は完了したので繰り返さない。次は11/13の既存3画像を1起動・1提出で確認する。** 遮蔽がある遠方2枚＋近方1枚を含み、保留の維持/変化も結果に残す。実測距離の1/1.5/2mに対応すると推測しない。

[計画](implementation_plan.md)、[一括runner](run_suite.py)、[入力・実行テスト](../../../tests/test_frame_packet_saved_suite.py)、[検証結果](verification_r01/audit.json)。旧GPU runnerとsrcのcodec/YOLO/支持点/幾何/操縦は変更していない。

## GPUPCで行うこと

このPCの追加ファイルをユーザー側でGit commit/pushし、GPUPCでpullして反映する。こちらからGit書込みはしていない。カメラ・matsunuc・映像送信・走行・画面録画・G923は不要。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-18/frame_packet_saved_suite_r01/run_suite.py run \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --output-dir recordings/2026-11-18/packet_recompression_multi_gpu_r01 \
  --archive /home/hsr/Downloads/packet_recompression_multi_gpu_20261118_r01.tar.xz
```

recordings/Experimental_results内の固定ファイル名を有界探索してSHA一致した3枚だけを使う。過去の解析PC専用intakeパスをGPUPCに要求しない。CUDA modelは既存1個を使い回し、各画像6warmup＋20測定、全体で**18warmup除外・60測定・30対比較**。新しい検出結果を使い、保存bboxで測距を救済しない。

最後の表示が `state: complete`、`images: 3`、`measured_samples: 60`、`paired_samples: 30` となり、Downloadsに `packet_recompression_multi_gpu_20261118_r01.tar.xz` ができる。その1ファイルを提出する。旧runnerの内部完走表示だけでなく、最後の圧縮完了とarchiveの存在まで確認する。

失敗時はERROR出力を確認する。同じ出力先を消してやり直さず、原因確認後に新規r02を使う。途中失敗の結果は提出用archiveにしない。

## 原画像が見つからない場合

GPU起動前に `known saved images missing (no GPU started)` で止まる。この場合、撮り直しや別画像への差替えは不要。解析PCに用意した入力packをGPU Downloadsへコピーし、次を実行する。

入力pack：`/home/robo25/theta_ws/RICHO-theta/recordings/2026-11-18/packet_saved_suite_inputs_20261118_r01.tar.xz`（2,563,792bytes、SHA256 `86692750b6130c6a76b6a0a955cdf9e7646efbe4f7b6ec04c956e167d583b512`）。原PNG3枚と固定manifestだけで、PNGの再保存・加工なし。Gitへrawを追加しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-18/frame_packet_saved_suite_r01/run_suite.py run \
  --input-archive /home/hsr/Downloads/packet_saved_suite_inputs_20261118_r01.tar.xz \
  --weights /home/hsr/Downloads/cone_distance_v03.pt \
  --output-dir recordings/2026-11-18/packet_recompression_multi_gpu_r01 \
  --archive /home/hsr/Downloads/packet_recompression_multi_gpu_20261118_r01.tar.xz
```

探索失敗だけならGPUもoutputも作られていないため同じr01でよい。途中まで実行してoutputが既にある場合は新規r02を使う。入力packを汎用展開せず、固定名/manifest/SHA/サイズを検査して一時コピーを読み、終了時にその一時コピーだけを片付ける。元archiveや元画像は変更しない。

## 対象と固定条件

| 元session/画像frame | 場面 | native対象ROI |
|---|---|---|
| 24aad0a8… / 28980 | 人が横切る・コーン下部付近の遮蔽 | x=270..350、y=0..720 |
| 同 / 37696 | 人が前に立つ・遮蔽/隣接領域 | 同上 |
| 同 / 44793 | より近いコーン・下部輪郭 | 同上 |

原画像と保存sidecarの旧bbox中心がこのROI内にあることを確認した。ただし新YOLO検出が変わってROI外になっても自動拡大しない。元sidecarはいずれも当時colour_contour_reaches_roi_edgeの保存例で、今回の新検出/upper-completion処理がどうなるかは未測定。都合の良い結果だけを残さない。

従来どおり、1.5Mbps設定の現行packet VP8 encode/decode、CUDA専用の同じweights/config/profile、observe_upper_completion/MotionRangeEngine、ABBA5反復。旧runner SHA `00111723b8149310573432d77ffac0499d5326c0f8f044412d2e1122cba2a78b` を検査して無断の版混在を拒否。画像によって床や取付条件を新認定しない。camera-foot水平距離の診断のみ。

旧summary/samples/pairsに加え、**各画像別のper_image_summary.json**とsuite_manifest.jsonを圧縮する。測距が全件保留の画像も採否・理由・時間として残る。全体距離差が小さくても、その画像が距離差集計に入っていない場合を隠さない。原PNG/重み/再圧縮画像を結果archiveへ入れない。

## 今回の確認範囲

ローカルは新10を含む関連175成功/失敗skip0/5.03秒。[verification_r01](verification_r01/audit.json)。実原画像3枚とbyte同一packの往復、実codec/既存幾何＋**合成predictor**の60測定/30対、画像別集計を確認。これはGPU結果ではなく、実CUDA結果は提出待ち。

最初の新規テスト1件は空JSONLを想定して集計件数エラーを期待したが、実際には先に非空ファイル条件で拒否された。1行だけの不足JSONL fixtureへ変更して件数拒否の経路を検証し、production条件を緩めず最終175件を再実行した。

この比較後に実通信の運転映像共存・queue/pipe/期限を確認する。GPU単体時間をend-to-end遅延とせず、5/10Hzのlive採用やsource鮮度/車体座標/FFB認定へ進めない。全認定/制御/FFB/ROS flagsはfalse。今回はGit操作・日報・実機操作なし。前回までの未commit成果も保持。

### ローカル準備検証の再現（解析PC用、GPUでは不要）

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_saved_suite_r01/check.py \
  --input-pack recordings/2026-11-18/packet_saved_suite_inputs_20261118_r01.tar.xz \
  --output-dir Experimental_results/2026-11-18/frame_packet_saved_suite_r01/verification_r02
```
