# 3画像GPU提出：完走したが、圧縮で保留→数値が2画像で発生

**60測定/30対は正常に完走した。一方、元画像では3枚とも保留、再圧縮後は2枚で数値に変わった。これは精度改善と認定できず、現方式の実通信採用判断は保留する。** 同じ画像のGPU再実行や追加撮影は今は不要。

[正式監査](submission_audit_r01/audit.json)、[画像別再集計](submission_audit_r01/per_image_summary.json)、[全60時間CSV](submission_audit_r01/timing.csv)、[画像×検出枠の切分け](submission_audit_r01/pixel_box_matrix.json)、[代表measurement](submission_audit_r01/representative_measurements.json)。

## 提出整合

- 元archive：`packet_recompression_multi_gpu_20261118_r01.tar.xz`、SHA256 `3823324d6fc12b5855134f00c24621f9003f914a67130c61a5842f671e7a83d0`。原archiveとJSON5点は `recordings/2026-11-18/packet_recompression_multi_gpu_intake_r01/` に保持。
- 既知PNG3枚をGPUPC既存の `recordings/2026-11-13/guarded_motion_evidence_r02/` で発見して実行。input_packは使われていない。対象ROIは全画像 `[270,0,350,720]`、18warmup除外/ABBA5反復/60測定/30対。旧5186は再実行していない。
- CUDA専用旧runner SHA・suite runner SHA・対象src14件・weights/config/profile/全PNGのSHA一致。JSON SHA・全sample順序・全30対・画像別集計・全体summaryを再計算し一致。
- 全30packetのwire SHA/bytes/candidate/推論復号画素を再現し、元画像側の推論画素も一致。GPU検出枠を使った既存ROIの支持観測/距離結果を全60件で再現。追加YOLO/撮影や、画像の加工/派生保存は行っていない。

## 画像別の採否

| 画像frame | 元画像10回 | 再圧縮後10回 | 数値同士の比較対 |
|---|---|---|---:|
| 28980（人が横切る場面） | 保留10 | 数値10：1.610815m、支持点[306,384] | 0 |
| 37696（人/遮蔽の場面） | 保留10 | 保留10 | 0 |
| 44793（近方コーン） | 保留10 | 数値10：0.983259m、支持点[305,419] | 0 |

全て元画像の保留理由は `colour_contour_reaches_roi_edge`。packetで数値になった2画像の理由は `EXPERIMENTAL_FIXED_MOUNT_NOT_VERIFIED_CONTACT`。全体では元画像0/30数値、packet20/30数値、保留→数値20対、数値→保留0対、共通数値対0。

従って**今回の3画像について距離誤差・前後差を計算する対はない**。nullを誤差0にせず、packetだけの1.611m/0.983mを正しい実測値や改善としない。前回5186の約3cm差は別の1画像の結果であり、今回全画像の精度保証に広げない。各variant/画像内の10反復は検出/metric signatureがそれぞれ1種類で、今回の短時間反復では一定の変化だった。

## 原因切分け：画像とbboxを入れ替える事後計算

保存された実GPUの元bbox/packet bboxと、wire/推論画素一致を確認した元画像/packet画像で4通りを計算した。これは追加GPU推論でなく、支持点・幾何の診断。

| 入力画像 | 元bbox使用 | packet bbox使用 |
|---|---|---|
| 元画像 | 28980/44793とも保留 | 同じく保留 |
| packet画像 | 28980/44793とも数値 | 同じ数値 |

37696は全4通りで保留。今回の2画像の採否変化は、わずかなYOLO bbox変化より**圧縮による画素・色マスク変化**で説明される。補完処理が新たに救済した結果ではなく、packet画像では通常の色分離輪郭が受理されていた。

同じ元bbox・同じ固定HSV閾値で輪郭診断を採った。

| 画像 | 同一解析crop(native座標) | 元の輪郭境界・接触 | packetの輪郭境界・接触 |
|---|---|---|---|
| 28980 | [288,301,331,389] | min x=288、左端接触 | min x=289、接触なし |
| 37696 | [289,301,337,388] | max y=387、下端接触 | max y=387、下端接触を維持 |
| 44793 | [275,294,350,422] | max y=421、下端接触 | max y=419、接触なし |

この「crop」は輪郭計算の内部範囲で、元画像を切り抜いて保存/配信した意味ではない。元画像/閾値/ROI/幾何は変更していない。現行の境界接触条件が1～2pxのマスク変化に敏感だったと確認できる。一方、元の保留が過剰だったのか、packetの数値が物理的に不適切かは独立した接地点/実測がないため未判定。

## 時間・負荷

| 画像frame | 元receiver段階 中央値/最大 | packet receiver段階 中央値/最大 |
|---|---:|---:|
| 28980 | 10.806 / 11.231ms | 15.364 / 16.414ms |
| 37696 | 7.917 / 8.594ms | 15.143 / 16.318ms |
| 44793 | 8.300 / 8.900ms | 15.435 / 15.770ms |

packet全30件の中央値15.303ms、最大16.414ms。100/200ms超過0。PyTorch allocator peak allocated60,697,088bytes / reserved98,566,144bytesは双方・全画像で同一。GPU全体使用率やシステム総メモリではない。

これはcodec復号/検証/copy＋CUDA同期込み推論＋支持点/幾何の段階時間で、実network/fragment/queue/IPC/表示/通常映像との共存を測った値ではない。現GPU予備試験では処理時間は短かったが、採否変化があるため「速度も精度も問題なし」とは判断しない。

## 判断と次の作業

1. この提出の整合確認とGPU保存画像比較は完了。同じ試験の繰返し、撮り直し、環境の再導入は不要。
2. 元の輪郭境界に依存する保留が圧縮で変わる事象を再現fixtureとして保持し、保存画像だけで判定安定性/圧縮方式の候補を比較する。都合よくHSV閾値やROIを変えて今回だけ通さず、元数値の維持・保留の維持・新規数値を分けて評価する。
3. その判断後に、既定offの実通信経路で通常映像と共存させる試験へ進む。実機・操縦・G923出力を今ここで起動する指示ではない。

全source/物理/接地/制御/FFB/ROS認定flagsはfalse。今回は監査・診断コードと資料だけを追加し、測距runtime/旧runner/元画像/過去manifestは変更していない。Git操作や日報・実機操作なし。

新8を含む関連183成功/失敗skip0/5.74秒（[verification_r03](verification_r03/audit.json)）。初回の新テスト2件はPython直生成fixtureのROI tupleが実JSONのlistになっていない問題で失敗し、実際のJSON往復をfixtureに加えて修正。production検査を緩めていない。verification_r02は失敗ログの履歴、正式はr03。これらのローカル試験は合成predictorで、GPU実測値とは別。
