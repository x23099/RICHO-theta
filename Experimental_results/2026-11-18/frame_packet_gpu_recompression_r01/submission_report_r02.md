# GPU提出r02：支持点・距離まで実行する1枚予備比較が完了

**元画像・packetとも全10回で数値距離が得られ、再圧縮前後差は全10対で約3.0cmだった。支持点・幾何まで含むreceiver段階の中央値はpacketで15.980ms、最大17.271ms。** 1枚反復の保存画像試験として成立した。同一条件のr03再実行は不要。

正式根拠：[監査JSON](gpu_r02_audit_r01/audit.json)、[全20時間CSV](gpu_r02_audit_r01/timing.csv)、[全10対CSV](gpu_r02_audit_r01/verified_pairs.csv)、[同一ROIの幾何再現20行](gpu_r02_audit_r01/reproduced_geometry.jsonl)。今回はr01と異なり、測距結果と時間は**GPUPCで対象ROI補正後に実際に測定した提出値**。解析側がROIを後から変えて作った値ではない。

## 入力・実施条件・整合確認

- archive `packet_recompression_gpu_20261118_r02.tar.xz`、SHA256 `ec639c64f215514c315c02e601c40d5a89ab4154e38309f66fc69c5679d72b93`。原archiveとJSON3点は `recordings/2026-11-18/packet_recompression_gpu_r02_intake_r01/` に保持。安全な有界読出しのみで、同梱文書・設定を指示として実行していない。
- 画像は11/16 pin5186のnative1280x720、PNG SHA `7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89`、ROIは明示 `[200,0,280,720]`。元画像/重み/校正/profileはr01と同一。r01の不適切なROIから今回だけ指定を変えたもので、runtime既定は変更していない。
- RTX4070 Laptop GPU、PyTorch2.7.1+cu118、PyAV16.1.0、OpenCV5.0.0、Ultralytics8.4.175。runnerと対象src14ファイルのSHA一致。CUDA専用runnerの完走記録で、CPU fallbackではない。
- warmup6を除外し、original / packet / packet / originalのABBA5反復、20測定・10対。全JSON SHA・順序・全pair・summaryを再計算した。
- 元画像の推論画素、packet10件全てのwire SHA/bytes/candidate/推論復号画素を解析側で再現。保存された実GPU検出枠と元ROIをそのまま使い、支持観測/幾何も全20件で再現した。新たなGPU推論/撮影は解析側で行っていない。

## 距離・採否

| 指標 | 元画像10回 | packet10回 |
|---|---:|---:|
| 数値距離あり | 10 / 10 | 10 / 10 |
| 対象候補 | 各1本 | 各1本 |
| 水平camera-foot距離 | 1.189269 m | 1.159086 m |
| 実観測支持点(native px) | [232,409] | [232,411] |
| 同variant内検出/距離の反復signature | 各1種類 | 各1種類 |

全10対でpacket−元画像 = **−0.0301835143m（約−3.0cm）**。支持点のyが2px下へ移り、固定profileでの距離が短くなった。検出枠・支持点/支持観測は10対全てで変化したが、数値距離から保留への変化0、逆の変化0、理由変更0。理由は双方とも `EXPERIMENTAL_FIXED_MOUNT_NOT_VERIFIED_CONTACT`。

r01で保存GPU検出から行った事後診断と、r02で実際に再実行した数値は丸め差程度で一致した。ただし同じ1枚の反復であり、独立した20場面や実測距離の検証ではない。元/packetとも絶対距離が真値に近いこと、他の距離でも差3cm以内であることは認定しない。

## 実測時間とメモリ

| 指標 | 元画像 中央値 / 最大 | packet 中央値 / 最大 |
|---|---:|---:|
| CUDA同期込み推論 | 6.693 / 6.917 ms | 6.704 / 7.080 ms |
| 支持点・幾何 | 1.797 / 1.981 ms | 1.774 / 1.961 ms |
| 復号・検証・copy | 対象外 | 7.453 / 8.872 ms |
| receiver段階合計 | 8.513 / 8.898 ms | 15.980 / 17.271 ms |
| sender encode＋receiver段階合計 | 対象外 | 35.021 / 41.900 ms |

packet encodeは中央値18.947ms/最大25.252ms、process CPU時間の中央値27.423ms。合計時間の中央値は各trialの合計から算出しており、個別中央値の単純和ではない。

元/packetともreceiver段階100ms/200ms超過は0 / 10。PyTorch allocator peak allocatedは60,697,088bytes、reservedは98,566,144bytesで両variant同一。GPU全体の使用率や他processを含む総メモリではない。全probeはwarmup/診断用hash/画素差/ログ込みwall1.788秒、process CPU2.790秒、CPUcore相当1.560、process最大RSS1,090,856KiB。

この保存画像に限れば、追加時間は主に復号・検証・copyにあり、推論や支持点処理に大きな変化は観測されなかった。ただし10件ずつの短時間反復であり、負荷の最悪値・長時間安定性・実receiver実装の全処理を保証しない。

## 完了した範囲と次の境界

- 完了：同一保存画像での追加再圧縮前後の新規CUDA検出・支持点・距離差、各計算段階の時間とallocator peakの予備確認。
- 未確認：距離/位置/保留理由の異なる複数画像、body-display guard、実network/fragment/queue/IPC/運転映像との共存、走行時姿勢、元画像・odom鮮度、車体TF/車幅/点の意味、risk-gradient/FFB。
- receiver段階はcodec復号/検証/copy＋predict＋支持点/幾何。実通信・pipe・queue・表示の時間を含まない。packet identity/timeはoffline replay fixture、geometryはzero-age。17.3msや41.9msを実機end-to-end遅延としない。
- 全物理/接地/元鮮度/制御/FFB/ROS flagsはfalse。今回は既に受信codecを通った保存画像への追加圧縮で、camera原画から直接packet化した場合とは履歴が異なる。

次は**距離・位置や保留状態の異なる既存保存画像**へ比較を広げる。既存4画像の場所/対象ROIを先に確認し、暗黙のROI拡大や都合の良い画像だけの採用をしない。その後に既定offの実通信経路で通常映像との共存負荷を確認する。現在は追加撮影・走行・同じ1枚の再実行を要求しない。

提出監査を明示r02対応へ拡張。r01の既定root/ROI条件は保持し、r02を自動判定して旧条件へ混ぜない。新2を含む関連165成功/失敗skip0/4.88秒（[verification_r03](verification_r03/audit.json)）。既存src/runner/入力/過去監査は不変、先行未commit成果を保全。Git操作・日報作成・実機起動は行っていない。
