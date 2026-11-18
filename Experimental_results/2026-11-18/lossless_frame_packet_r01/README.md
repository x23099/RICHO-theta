# PNG原画素と運動情報の一体packet：offline試作結果

正式結果: [results_r02/audit.json](results_r02/audit.json)、[全20試行](results_r02/trials.jsonl)、[回帰検証](verification_r01/audit.json)。作業日2026-11-18。実通信へは未接続。

## 結論

保存4原画×5回で、**全20回の全画素SHA・source candidate・元GPU保存bboxによる支持点/幾何/保留判定が一致**した。数値化できた件数を増やすためのHSV/ROI/支持点条件変更なし。これは元の数値1枚・保留3枚の保存入力との一致であり、真の距離精度や接地を新たに検証した結果ではない。

新規27を含む関連**221テスト成功、失敗・skip 0、8.04秒**。元のVP8 codec/channel/runtime/UI/操縦系はSHA不変。追加撮影・CUDA推論・カメラ/ROS/G923起動・Git操作なし。原画像は変更せず、PNG化/復号はメモリ内だけで行った。

## 形式・異常時動作

- [driver_lossless_frame_packet.py](../../../src/driver_lossless_frame_packet.py): 別magic/schema/codec、source candidateとmedia PTS・元BGR画素SHAを一つのpacketへ格納。既存checked_candidateを共用し、元鮮度/露光/物理/制御/FFB/ROS falseを維持。既存VP8形式は相互拒否する。
- payload上限2MiB、header上限8KiBを維持。native 1280×720 RGB8/非interlaceのIHDR・IDAT・IENDだけを受理する。CRC、chunk数/順序、末尾、解凍出力量/EOF、filter番号、復号画素SHAを検査。一般PNGファイルすべてを受ける実装ではない。
- chunk構造/CRCの根拠は[W3C PNG仕様](https://www.w3.org/TR/png-3/#5DataRep)。digestは偶発破損・混線検出であり、認証や「撮影と運動が物理的に正しい組」の証明ではない。
- [driver_lossless_frame_fragments.py](../../../src/driver_lossless_frame_fragments.py): PNG専用の別fragment magic、最大16KiB/片、1packet分だけ有界保持。欠損・重複・順序入替え・混線・改変・旧sequence・時計逆行を検証。重複で初片時刻を更新せず、新sequenceが古いpacketを置換する。
- 初片から200msを再構成/復号前後/takeに共用。decode中に期限を超えたpacketも旧数値も返さない。送受信PC時計の差分やRTP映像との同一フレーム照合を使わない。
- 単一worker owner用で、callback内処理やlive sender schedulerではない。take後の推論/表示にも同じdeadlineを引き継ぐ必要があり、今回その統合までは行っていない。

## サイズと時間

解析PC CPU、warmup除外0、20試行。新GPU計測ではない。

| 項目 | 中央値 | 最大 |
|---|---:|---:|
| PNG full packet | 1,006,745.5 bytes | 1,025,933 bytes |
| fragment数 | 62 | 63 |
| fragment header込み | 1,012,201.5 bytes | 1,031,477 bytes |
| encode+PNG検査 | 61.84 ms | 87.81 ms |
| fragment生成+再構成+検査 | 43.18 ms | 58.91 ms |
| decode+検査+copy | 45.54 ms | 62.31 ms |
| 初片からtake（無通信の実測） | 67.28 ms | 94.92 ms |

fragment生成段階には**初片前の送信側検査**も含むため、その段階全体と初片後の時間は足し合わせない。初片後には受信側検査・decode・copyが含まれる。実ネットワーク・GPU推論・IPC・表示時間は含まれない。

5Hzの単純データ量中央値40.49Mbps、10Hz80.98Mbps。fragment headerを含むが、SCTP/DTLS/IP・再送・queue・通常の運転映像は含まない。

| 仮想データレート | 転送だけで初片200ms内 | 今回の受信CPU時間も加算して200ms内 |
|---|---:|---:|
| 15 Mbps | 0/20 | 0/20 |
| 30 Mbps | 0/20 | 0/20 |
| 100 Mbps | 20/20 | 20/20 |

モデルはmessageの直列化終了を到着時刻とし、初片到着から期限を数える。実測した初片後のCPU仕事を保守的に直列加算し、通信/CPUの重なりを仮定しない。**100Mbpsという回線を測った結果でも、100Mbpsなら実運用できるという保証でもない**。encodeを含む送信側期限、backpressure、同時運転映像、5/10Hz連続処理、欠損時の有効率は未検証。

results_r01は受信CPUの加算に初片前の送信側検査まで含めた旧モデルで、100Mbpsのpostdecodeは19/20だった。r02では初片後の実測区間を加算する定義へ修正し、期限・上限・元測距条件は変更していない。旧結果は上書きせず保持した。

## 検証内容と制限

27新テストは実PNG往復、readonly・元画素不変、no-odom保留、codec相互拒否、JSON重複/非有限値、改変/末尾、CRC/chunk/寸法/deflate膨張上限、ランダム画の2MiB超過拒否、scope/PTS/order、復号前後の期限、one-shot、旧値消去、fragment欠損/重複/再生/置換/時計逆行を確認する。[テスト](../../../tests/test_driver_lossless_frame_packet.py)。SHAは旧runtimeと実験入力も前後検査する。

保存画像に付けたcandidateは**offline受理用の合成fixture**であり、その撮影時に記録された運動・露光時刻ではない。ここから元の走行に使える運動/鮮度を復元したとは扱わない。新YOLO推論はせず、元GPU入力と画素SHAが一致したことを条件にその保存bboxを使う。

## 次に進めること

1. offlineの有界sender/backpressure・5/10Hz連続処理モデルで、有効packet率と欠損/queue時の最新値の扱いを確認する。今回のPNGを既存VP8 channelへそのまま通さない。
2. モデルで成立する条件を整理後、GPUPC/送信側の処理時間・利用可能帯域・通常映像との共存を、制御/FFBから分離した計測で確認する。今回のCPU値をGPUPCやmatsunucへ転用しない。
3. 形式と期限の成立後に元鮮度・接地/車体基準・G923への受け渡しを別に検証する。現段階の追加撮影/実機走行は不要。

## 再現（解析PC、毎回未使用の出力先）

```bash
cd /home/robo25/theta_ws/RICHO-theta
OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/lossless_frame_packet_r01/run.py --output-dir Experimental_results/2026-11-18/lossless_frame_packet_r01/results_r03
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/lossless_frame_packet_r01/check.py --results Experimental_results/2026-11-18/lossless_frame_packet_r01/results_r03 --output-dir Experimental_results/2026-11-18/lossless_frame_packet_r01/verification_r02
```

現在はユーザー側での実行不要。結果JSONだけGit対象、原画と録画はrecordings配下のまま。環境のpytest自動plugin衝突を避け、checkerは従来どおりPYTEST_DISABLE_PLUGIN_AUTOLOAD=1を明示する。
