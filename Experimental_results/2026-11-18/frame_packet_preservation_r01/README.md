# 保存画像の判定維持：可逆圧縮で画素は保てるが帯域が約10倍になる

**測距・色閾値を変更せずに、元画像の数値/保留を維持できる候補を確認した。** PNG既定・PNG level3・zlib level1は4原本×5反復で全画素一致。既存GPU検出の同じ入力画素で支持点/幾何も元のまま再現された。一方、データ量はPNG既定で約1MB/枚となり、5Hzで約40Mbpsが必要。現在のVP8 packet形式に互換な変更を実装したわけではなく、ライブ採用は未決定。

[計画](implementation_plan.md)、[比較コード](compare.py)、[正式比較](results_r03/audit.json)、[80試行CSV](results_r03/trials.csv)、[183＋新11＝関連194試験の検証](verification_r01/audit.json)、[pytest出力](verification_r01/tests.txt)。

## 比較条件

- 原画像4枚：11/16 pin5186、11/13 28980/37696/44793。過去提出の原PNG・推論画素・code・GPU bboxを照合。都合の良い数値例だけでなく、元の保留3枚も含めた。
- 現行VP8はGPU提出のpacket画像/検出枠を使い、再生成したpacket wire SHA・推論画素が一致することを確認。可逆候補は元GPU入力画素と完全一致した場合だけ、その画素に対応する元GPU検出を使用した。
- 新たなGPU/YOLOは起動していない。検出を新実行した試験ではなく、**既存GPU推論画素と厳密に同一であることを確認したcodec往復＋支持点/幾何の再計算**。旧支持点/ROI/HSV/校正/取付モデルを変更していない。
- 4方式×4枚×5反復＝80試行。方式の実行順を反転する反復も含める。warmup除外0でcold startが含まれ得る。圧縮/復号はメモリ内のみで、原本変更や派生画像保存なし。
- 解析PCのCPUによる時間で、GPUPC/matsunucの実時間ではない。OpenCV/zlib versionは監査environment欄。PNG既定はパラメータ未指定の実装依存条件で、そのversionでの結果。PNG level3/zlib level1は明示指定。

## 判定維持

| 方式 | 全BGR画素一致 | 数値/保留/支持点/距離の維持 | 保留→数値 |
|---|---:|---:|---:|
| 現行VP8 | 0 / 20 | 5 / 20 | 10 / 20 |
| PNG既定 | 20 / 20 | 20 / 20 | 0 / 20 |
| PNG level3 | 20 / 20 | 20 / 20 | 0 / 20 |
| zlib level1 | 20 / 20 | 20 / 20 | 0 / 20 |

ここで判定維持は、distance_available/reason/整数支持点/水平距離/モデル別距離の一致をいう。浮動小数の計算順による末尾差だけは既存監査と同じ1e-10許容で比較、全画像画素はSHA256による完全一致。補助的な色seed数・bbox由来の診断情報は別のsupport_observation一致欄へ記録し、保留理由が同じでも診断情報だけ違う場合を数値判定変更と混同しない。

元の数値は5186だけ（約1.189m）、3枚は輪郭が解析範囲に触れるため保留。可逆候補はこの状態を全反復で維持した。VP8は5186の距離/支持点変更、28980/44793の保留→数値、37696の保留維持を再現した。

これは**元画像を測距入力として保存する性能**であり、元の距離が実測真値、元の保留が物理的正解、あるいはFFBへ使えるという認定ではない。cameraや既存RTP段階で既に失われた情報をlossless再圧縮で戻すものでもない。

## サイズ・CPU時間・帯域の比較

中央値。VP8だけは既存packetのframing/検証/copyを含む時間・全packet bytes、他はcodec payloadとnative復号までの時間であり、同じ処理範囲の厳密な速度比較ではない。

| 方式 | bytes/枚 | encode / decode | 5Hzのデータ量 | 10Hzのデータ量 |
|---|---:|---:|---:|---:|
| 現行VP8 packet | 98,212 | 34.23 / 15.94ms | 3.93Mbps | 7.86Mbps |
| PNG既定 payload | 1,005,464 | 37.79 / 20.11ms | 40.22Mbps | 80.44Mbps |
| PNG level3 payload | 837,660 | 111.61 / 21.99ms | 33.51Mbps | 67.01Mbps |
| zlib level1 payload | 1,140,940 | 63.33 / 15.20ms | 45.64Mbps | 91.28Mbps |

帯域欄はbytes×rate×8の単純量で、実network測定ではない。losslessにはさらにpacket/header/SCTP/DTLS/UDP/IP/再送や既存運転映像の負荷が加わる。今回の4枚は全て既存2MiB payload上限内だが、別のノイズ画像でも入る保証はなく、上限を広げて通さない。

PNG既定の理想直列化時間中央値は15Mbpsで536ms、30Mbpsで268ms、100Mbpsで80ms。15/30Mbpsを仮定すると転送だけで現在の初片から200msの窓を超える。この数字は仮想帯域の下限計算であり、実回線が15/30/100Mbpsだと測ったわけではない。100Mbpsなら80msで済む計算でも、encode/decode/GPU/queue/映像共存を含む期限を認定しない。senderとreceiverの別時計を換算して足した計測値でもない。

## 現時点の選択と次の作業

1. 判定条件を緩めたり、今回だけ通す閾値へ変更する対応はしない。画素をそのまま保持する方式を第一の比較候補にする。
2. 検査した可逆候補ではPNG既定を**次の試作候補**にする。PNG level3はデータ削減に対してCPU時間増が大きく、zlib level1はPNG既定より大きくencodeも遅かった。この保存4枚/解析PCでの比較であり、方式のライブ採用ではない。
3. 次は可逆payloadをsource metadataと厳密に束ねる**独立したoffline packet試作**と、現在の上限・初片期限・通常映像との併走を考慮した容量評価へ進む。既存VP8 channelにPNGをそのまま流さず、codec識別/寸法/bytes/破損/期限/旧scope混入の検査を残す。5/10Hzを黙って変更したり、期限を延ばして採用扱いにしない。

実通信/カメラ/ROS/機体/G923は起動せず、実行中の設定は不変。**現在、ユーザー側の追加撮影・GPU再試験は不要。** 実機/GPU/通信での確認が必要になる時点でPC別の手順を提示する。物理/接地/元鮮度/制御/FFB/ROS flagsはfalseのまま。

## 検証・履歴

新11を含む関連194試験成功、失敗/skip0、6.75秒。lossless画素一致/元入力不変、PNG IHDRをdecode前に制限、zlibの出力長/EOF/trailing/未消費データ拒否、2MiB上限、誤ったGPU画素へのbbox転用拒否、数値と診断の区別、全80行再集計、既存runtime SHA不変を確認。

results_r01は浮動小数の末尾差をJSON hashで比較して5186の判定維持を過小計数した履歴。results_r02は末尾差を分離したが補助観測情報と最終判定を同じ一致欄に含めた履歴。正式results_r03で、画素は完全一致、最終判定と補助観測を分離し、数値丸め差だけ1e-10を許容する明示定義へ修正。元の測距・物理精度条件は変更していない。過去出力を上書きしていない。

今回追加した実験コード/テスト/資料だけを変更。旧packet/runtime/距離/codec/画像/過去manifestは不変。Git commit/push/pull・日報作成なし。

## 公式仕様と再現

PNGの指定は[OpenCV公式imgcodecs flags](https://docs.opencv.org/4.8.0/d8/d6a/group__imgcodecs__flags.html)、zlibのlevel/出力上限/EOF確認は[Python公式zlib](https://docs.python.org/3/library/zlib.html)を参照。新しい依存パッケージは追加していない。

解析PC用。GPUPCへこの解析をそのまま実行させる必要はない。未使用の出力先が必要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_preservation_r01/compare.py \
  --output-dir Experimental_results/2026-11-18/frame_packet_preservation_r01/results_r04
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_preservation_r01/check.py \
  --results Experimental_results/2026-11-18/frame_packet_preservation_r01/results_r04 \
  --output-dir Experimental_results/2026-11-18/frame_packet_preservation_r01/verification_r02
```
