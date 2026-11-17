# 11/18：保存画像によるvideo＋packet encode併走負荷

**追加30Hzは現在の方式の採用候補から外し、次の接続比較を10Hz以下へ絞る。** 解析PCではvideo約30Hzを維持しつつ追加10Hzを概ね処理できたが、120件中1件の最新優先破棄があり、無欠測/実機共存/FFB期限達成を認定しない。5Hzは全60件完成した一方、名目更新間隔自体が200msなので、FFB向けの安全な既定値へ自動採用しない。

[計画](implementation_plan.md)、[benchmark](bench.py)、[生encode CSV](results_r01/samples.csv)、[offer/sendイベントCSV](results_r01/events.csv)、[試行単位progress](results_r01/trial_progress.jsonl)、[実行環境・16試行の監査](results_r01/audit.json)、[CSV再集計](analysis_r02/audit.json)、[8条件の表CSV](analysis_r02/profiles.csv)、[関連270試験](verification_r01/tests.txt)。

## 測定条件と比較層

- **解析PC**、8 logical CPUs、Linux x86_64、aiortc1.14.0/PyAV16.1.0/NumPy1.24.4。matunuc/GPUPCで測った結果ではない。CPU clock/affinity/環境設定の変更や新dependency導入なし。OPENBLAS_NUM_THREADS=1を当該processへ指定。
- videoはinstalled `Vp8Encoder`の持続インスタンスをworkerで使用。1280×720 BGR/30Hz、target_bitrateを**比較用に1.5Mbpsへ固定**。実runtimeのmotion-native BGR入力と同じ寸法・codec層を模しているが、実trackやcamera readerを起動してはいない。frame packingをworker内へ含めているため、実event loop上の処理配置まで同一の再現ではない。
- 追加側は前段の実`FramePacketChannelSender`/専用worker/fragment schedulerを使用。独立VP8 keyframeを毎回encodeする現在の方式。message上限16KiB、buffer policy32KiB、sender admission代用age200ms。fake sinkは即時drain・queue0、受信decodeなし。SCTP/DTLS/回線制限/映像受信decode/YOLO/ROS/操縦/G923の負荷は含めない。
- baseline追加0Hzと5/10/30Hz。各条件warmup0.5秒＋計測3秒、2反復。2反復目は条件を逆順に実施。計16試行、encode記録1,977行、packet offer/send記録1,010行を保存。性能しきい値を下げてPASSにするのではなく、欠落・置換・延長を数値として残した。
- process CPU/window wallを**使用core相当値**として記録する。host全体の使用率やnative codecの各thread単独CPU、FFB latencyではない。短い反復試行であり、温度/周波数/他process等の影響を分離した長時間性能保証ではない。

「1.5Mbps設定」は厳密な短時間の生成上限ではなく、独立packetを毎回作る全体が1.5Mbpsへ抑制される意味でもない。実runtimeのCLI `--bitrate 15M`や現接続の有効bitrateを今回確認したわけでもない。[installed aiortc source](https://github.com/aiortc/aiortc/blob/1.14.0/src/aiortc/codecs/vpx.py)の500kbps初期値/1.5Mbps clampと持続codecを読んで、比較設定を明示した。

## 原本と合成fixture

原本4枚のSHAを11/13・11/16の既存supplied-file監査へ照合。メモリ上もread-onlyとし、処理前後でfile/画素hashが不変。切抜き・resize・補正・注釈・圧縮/復号画像の再保存は行っていない。

| 入力 | 保存先（recordings/配下） | 由来 |
|---|---|---|
| 11/16 pin5186 | `2026-11-16/body_display_full_intake_r02/comparison/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png` | 前段benchmarkと同じ無加工復号PNG |
| 11/13 frame28980 | `2026-11-13/guarded_motion_full_intake_r02/logs/evidence/decoded_24aad0a8d31d46eeb33ef252b0d18475_f028980.png` | 保存withheld evidence |
| 同frame37696 | 同フォルダの`decoded_24aad0a8d31d46eeb33ef252b0d18475_f037696.png` | 同じ元sessionの保存画像 |
| 同frame44793 | 同フォルダの`decoded_24aad0a8d31d46eeb33ef252b0d18475_f044793.png` | 同じ元sessionの保存画像 |

`static_repeat`はpin1枚を反復。`discontinuous_cycle`は4枚を順次切替える負荷試験で、**撮影時刻順の連続動画や実走行の再現ではない**。間のframeを補間したり、source sessionを同じ撮影と偽って結合したりしていない。

candidateの時刻/連番/odom0は再生時に作った合成fixture。合成callbackとreplay admissionの同PC monotonicを使い、画像の実capture/露光や当該画像の実odomと称さない。sender admission→fake sendは計測したlocal待ち時間だが、元画像の鮮度・通信遅延ではない。物理/鮮度/FFB/ROS flagsはfalseのまま。

## 結果（各行2反復、計測計6秒）

生成Mbpsはencodeしたpayload/packet bytesの和で、実回線上のrateではない。videoはVP8 payload descriptorを含むRTP payload、packetは一体packet（fragment wrapper/DTLS/SCTP等は除く）。送れなかったpacketも生成量へ含める。

| 入力 | 追加Hz | video出力/180投入枠 | packet完了/offer | CPU core相当 | video生成Mbps | packet生成Mbps |
|---|---:|---:|---:|---:|---:|---:|
| static | 0 | 178 | — | 0.735 | 1.283 | 0 |
| static | 5 | 180 | 30/30 | 1.002 | 1.277 | 4.081 |
| static | 10 | 179 | 59/60 | 1.318 | 1.254 | 8.162 |
| static | 30 | 180 | 83/180 | 1.849 | 1.277 | 24.487 |
| 切替 | 0 | 180 | — | 0.965 | 2.150 | 0 |
| 切替 | 5 | 180 | 30/30 | 1.234 | 2.150 | 4.040 |
| 切替 | 10 | 180 | 60/60 | 1.557 | 2.150 | 7.892 |
| 切替 | 30 | 180 | 64/180 | 2.130 | 2.150 | 23.694 |

すべてtimer tickのskipは0、videoのcodec emptyも0。staticのbaselineで待機置換2件、10Hz条件で待機置換1件があり、「追加処理だけがvideo欠落を生んだ」とは断定しない。video完成rateは約29.67〜30Hzで、各frameの33.3ms以内完了や無jitterを保証する数字ではない。

### 処理時間と更新間隔

| 入力・追加Hz | packet encode P95 ms | admission→fake send P95 ms | 完了間隔の最大 ms |
|---|---:|---:|---:|
| static 5 | 56.32 | 61.27 | 228.90 |
| static 10 | 59.17 | 65.19 | 186.11 |
| static 30 | 35.30 | 32.45 | 566.03 |
| 切替 5 | 50.23 | 55.81 | 217.12 |
| 切替 10 | 53.19 | 58.65 | 125.12 |
| 切替 30 | 34.72 | 32.41 | 297.57 |

**30Hzの成功分P95が小さいことを改善と解釈しない。** 新入力が待機中だと旧encode完了をpublishせず、新offerでも準備済みslotを失効する現在の最新優先policyにより、遅い仕事が落ち、成功分だけに偏る。実CPUが8 coreすべて飽和した証拠でも、fake回線で通信損失が起きた結果でもない。encode済みだが完了引渡しされない仕事のCPU/生成bytesも無駄になる。

10Hzの破棄1件はstatic/反復1/合成sequence28。encode102.877ms、投入→encode完了109.414msの間に次sequence31のofferがあり、旧結果を公開しない条件と一致する。source age200ms超過やfake sinkのbuffer待ちではない（schedulerのexpired/held_for_bufferは0）。全破棄をworker内のどちらのslot失効箇所で落としたかの個別counterはないため、全件の内部reasonを断定しない。原時刻はsamples/eventsから追跡できる。

5Hz/10Hzとも、このlocal結果をFFB期限達成に読み替えない。5Hzは名目200ms間隔、10Hzでも実完了間隔最大186msであり、ここへ実通信/受信decode/認識が加わる。既存FFBのchallenge/watchdog/期限を緩めて通す判断はしない。

## 検証・履歴

CSVからencode時間の方程式/各統計、payload合計、offer/encode/sendのsequenceとadmission一致、欠測集合、初期期限、queue上限、終了flag、CPU比を再計算。**16試行すべて整合**。analysis_r01は完了間隔追加前、正式analysis_r02は同じ生データへ完了間隔を追加したもの。元のbenchmarkや過去結果は書き換えていない。

新12試験と前段258試験を合わせ**270成功、0失敗/skip、4.38秒**。[監査](verification_r01/audit.json)。上限/rate選択、空統計を0で補完しない、event重複/無offer/不正clock/期限延長拒否、fake sinkのmessage計数等を追加。旧codec/source/channel/runtime SHAを前段正式結果へ照合し不変。今回src/既存通信/測距/ROS/FFB変更なし。

先行実行では、installed streaming codecの時刻丸め（3000→2999等、90kHzで1tick）を完全一致とした実験側assertが停止した。streaming codec診断を1tick以内として記録し、**独立packetの厳密identity gateは変更していない**。次の先行実行は最後のversion採取で`opencv-python` distribution metadata不在により停止。cv2 moduleのversion/pathを事前取得し、試行ごとのprogressをflushする形に修正してから、全16試行を再実行して正式結果を保存した。先行コンソール値を正式表へ混ぜていない。

新日報作成・Git書込み・外部送信・時計設定・実機起動なし。今回の新成果はローカル未commit/未push。

## 判断と次の境界

1. **現在の独立keyframe＋最新slot方式を追加30Hzのまま実接続する案は見送る。** 完了147/360、生成約24Mbpsであり、成功分の短いlatencyだけで採用しない。将来30Hzを必要とする場合は、encode完了のpublish公平性、再encodeの重複、帯域と画質/測距への影響を改めて比較する。
2. 次のopt-in受け渡し比較は**10Hzを上限候補、5Hzを低負荷比較**とする。これは解析PCでの候補絞りであり、ライブdefault/risk-gradient入力rateの承認ではない。試験policyの200msもFFBの鮮度へ転用しない。
3. 次はsenderのcapture/odom履歴・接続scope・receiver認識入力へ、起動しない既定offのopt-in接続を設計する。runtimeへの接続変更は今回まだ行っていない。その後、matunuc/GPUPCで同じ短い比較を行い、実video/telemetry/操縦との負荷、欠測/終了を確認する。

現時点の追加撮影/走行やGPUPC操作は不要。実機確認の入口を準備する前に同じ撮影を依頼しない。車体TF/車幅/障害物点の定義、元観測鮮度、risk-gradient/抵抗FFB接続は別の未完了gate。

## 再現（解析PC、未使用の出力先）

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_load_r01/bench.py --output-dir Experimental_results/2026-11-18/frame_packet_load_r01/results_r02
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_load_r01/report.py --input-dir Experimental_results/2026-11-18/frame_packet_load_r01/results_r02 --output-dir Experimental_results/2026-11-18/frame_packet_load_r01/analysis_r03
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_load_r01/check.py --output-dir Experimental_results/2026-11-18/frame_packet_load_r01/verification_r02
```

元4 PNGと既存監査が必要。基準SHAに対応する旧runtime等を将来変更した場合は、過去SHAを上書きせず新監査へ進む。所要はbenchmark約1分＋照合/回帰。GPUPCへこの解析PC絶対パスをそのまま入力する指示ではない。
