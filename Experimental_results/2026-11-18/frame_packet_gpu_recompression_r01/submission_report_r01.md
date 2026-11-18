# GPU提出r01：実CUDA完走、対象範囲外による測距保留と事後診断

**提出は正常。CUDA YOLO/codecの測定は完走した。ただし私が案内したROI x=270..350と保存画像の対象位置が合っておらず、元画像・packetとも全件no_candidateだった。** 距離差0や精度合格と報告してはいけない。提出・操作の間違いではなく試験入力に対する案内条件の問題。

正式根拠：[監査JSON](submission_audit_r02/audit.json)、[全時間CSV](submission_audit_r02/timing.csv)、[事後距離10対CSV](submission_audit_r02/posthoc_pairs.csv)、[事後幾何20行](submission_audit_r02/posthoc_geometry.jsonl)。r01監査はJSON数値overflow拒否・回帰試験追加前の同一提出診断履歴、正式はr02。

## 原本・条件と再現確認

- archive：`/home/robo25/Downloads/packet_recompression_gpu_20261118_r01.tar.xz`、SHA256 `ba4fe5a6b64742a53be07f7b9283458ed377bee9200b4f1cfcfd9f15778257ec`。
- archiveと原JSON3点を `recordings/2026-11-18/packet_recompression_gpu_intake_r02/` に保持。全memberを有界検査し、path traversal/symlink/重複を拒否。archive内の文章・設定を指示として実行していない。
- 11/16 pin5186、PNG SHA `7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89`、native1280x720。既存原本PNG/画素とも不変。派生画像保存なし。
- RTX4070 Laptop GPU、PyTorch2.7.1+cu118、PyAV16.1.0、OpenCV5.0.0、Ultralytics8.4.175。runnerと対象src14ファイルのSHAが解析側と全一致。weights/config/profile SHAも既存設定一致。
- warmup6呼出しを除外、ABBA5反復・20測定・10対。全sample/pair SHA、順序、全summary再集計、当初ROIの幾何を独立再現。元報告のactual_cuda_inference=trueはCUDA専用runnerと環境記録を伴う。

## 提出時の結果

| 指標 | 元画像10回 | packet10回 |
|---|---:|---:|
| 対象ROI内候補 | 0 | 0 |
| 数値距離 | 0 | 0 |
| 保留理由 | no_candidate 10回 | no_candidate 10回 |
| CUDA同期込み推論 中央値 | 6.694 ms | 6.582 ms |
| codec復号/検証/copy 中央値 | 対象外 | 7.465 ms |
| receiver段階 中央値 / 最大 | 6.749 / 7.673 ms | 14.059 / 17.554 ms |
| receiver段階100/200ms超過 | 0 / 0 | 0 / 0 |
| PyTorch peak allocated | 60,697,088 bytes | 60,697,088 bytes |
| PyTorch peak reserved | 98,566,144 bytes | 98,566,144 bytes |

packet encode中央値16.959ms、CPU時間24.972ms。encode＋receiver段階合計中央値31.047ms/最大37.392ms。全probeはwarmup/診断/ログ込みwall2.121秒、process CPU2.757秒、CPUcore相当1.300。これらはGPU全体使用率や機体側CPU負荷、実通信・5/10Hz pacingの結果ではない。

支持点処理は候補選択で返っているため、今回のreceiver段階時間は**コーンを採用して支持点・距離まで求めた場合の時間ではない**。採用時の負荷を「17.6ms以内」と一般化しない。

元画像の前方コーンbbox中心x=239.340、packetで239.306。どちらも270未満で、指定ROI外。raw detectorはコーンを検出している。rear側の別候補も存在するが、対象選択の根拠として混ぜていない。検出枠の厳密signatureは10対全て異なるものの、各variant内の10反復はそれぞれ同一で、検出消失10件という意味ではない。

## 保存GPU検出を使った事後の距離差

新しいYOLO実行や撮影はせず、**保存された実GPU bbox**を使用した。元PNGから現行codecで各sequenceのpacketを再生成し、packet全体SHA・candidate・bytes・GPUへ渡した復号画素SHAが全10件で一致した。元画像側の推論画素も一致。従って任意の似た画像へbboxを流用した再計算ではない。

対象範囲を後からx=200..280、y=0..720に変えたことを明記し、既存observer/幾何・profileのままoffline計算した。元の提出measurementやsummaryは編集していない。

| 事後計算の指標（10対全て同一） | 元画像 | packet |
|---|---:|---:|
| 対象候補 | 1 | 1 |
| 実観測支持点(native px) | [232,409] | [232,411] |
| camera-foot水平距離 | 1.189269 m | 1.159086 m |

packet−元画像 = **−0.030184m（約−3.0cm）**。全10対で支持点yが2px下へ変わり、固定profileでの距離が約3cm短くなった。これは「追加再圧縮の前後差」であり、実測に対する絶対誤差ではない。1枚反復で全距離・場面の精度を保証しない。

事後処理にGPU推論をやり直したわけではないので、ROI補正後のGPU全処理時間は得ていない。全物理/接地/元鮮度/制御/FFB/ROS flagsはfalse。ライブ距離採用や抵抗FFBへの接続を承認しない。

## 次の一手

追加撮影なし。同じGPUPC・同じrunner・同じ画像で、`--target-roi 200 0 280 720` を明示し、出力/archiveをr02へ変えて実行する。既存srcやrunnerの変更は不要で、この再試験のためのGit再反映も不要。支持点・距離まで実際に処理したCUDA試験の数値/時間を確認する。[r02コマンド](README.md#次のgpupc操作r02対象範囲を補正した同画像試験)

今回追加した監査の新8を含む関連163試験成功、失敗/skip0、4.67秒（[検証](verification_r02/audit.json)）。試験はローカルでGPUを起動せず、提出解析自体もGPU未起動。既存src/runner/画像/過去manifest不変。Git操作・日報・実機操作なし。
