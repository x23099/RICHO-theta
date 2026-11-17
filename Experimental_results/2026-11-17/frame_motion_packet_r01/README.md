# 11/17扱い：画像と運動情報の一体packetをローカル検証

**画像bitstreamと送信元運動candidateを一つの有界packetへまとめ、欠落後も独立decodeできる試作を実装・検証した。** PC間時計の同期/換算、受信映像PTS originの推定は使わない。既存WebRTC映像・操縦・telemetry・測距・challenge・FFBへは接続していない。

ユーザー指定の作業日ラベルは2026-11-17。11/16の日報と成果物は先にcommit **c05ff48** としてorigin/mainへpush完了後に着手した。OS時計/Git時刻や元画像の11/16日付を変更していない。実行UTCは[正式結果](results_r01/audit.json)にそのまま保存。

[計画と方式比較](implementation_plan.md)、[試作module](../../../src/driver_frame_packet.py)、[23ケースの試験](results_r01/tests.txt)、[codec比較5試行](results_r01/codec_samples.csv)。

## 検証できたこと

- 各画像を独立したVP8 keyframeにし、capture sequence・sender media PTS・元odom candidateと同じpacketに格納する。前frameの参照が不要なので、先頭/途中のframeが欠けても次のpacketだけから画像と当該metadataを復元できる。
- ヘッダ/画像payload全体を同じSHA256へ含め、長さ・上限・schemaを検査。途中切断、余剰bytes、metadata/payload入替え、破損を拒否。**SHAは認証ではなく、意図的な改ざんを防ぐものではない。** 送信callerが誤った画像とcandidateを最初から組にした場合まで検出する仕組みでもない。
- 1280×720の可視VP8 keyframeだけをdecode前に許可。参照frame、別寸法、未知schema、不正型、重複JSON key、NaN、認定flagの昇格を拒否。
- 既存sender candidateを再検査し、採用された元odomだけからlocal候補が再現することを確認。保留packetへ前の速度を載せない。停止0・後退/ヨーの符号を維持。
- 受信器は明示sender/stream IDと順序を検査し、別接続、重複、逆順を拒否。失敗時は旧画像/運動組を消し、closeや受信時計逆行後に復活させない。未取得を0へ補完しない。
- 受信後経過だけをreceiver内時計で判定し、sender時刻との差を計算しない。この経過はネットワーク遅延や元計測の鮮度ではない。

これは**同じpacket内の画像をdecodeする別入力方式**の試作。従来のRTPで受信した既存画像へmetadataを正しく貼れたという結果ではない。source candidateのreceiver_frame_identity_verified、露光/計測鮮度/物理/FFB/ROS flagsもfalseのまま。capture readerとodom callback全件履歴の実際の取得点への接続はまだない。

## 保存画像によるcodec比較

入力は11/16提出から保存したpin frame5186、session e52bb32f03d6488ebf37d769f46ec37aの元PNG。SHA `7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89` を正式監査へ照合し、処理前後で元fileと入力画素が不変であることを確認した。**この画像へ付けた運動は合成fixtureで、当該画像の実odom計測ではない。** 圧縮/復号のカメラ画像は再保存していない。

解析PC、PyAV16.1.0、NumPy1.24.4で同じ画像を5回処理。新dependencyの導入やaiortc/OSの変更はなし。

| 項目 | 中央値 | 範囲 |
|---|---:|---:|
| VP8画像＋metadata packet | 101,927bytes | 101,924〜101,960 |
| うちVP8画像payload | 99,903bytes | 全試行同じ |
| PNG比較payload | 1,021,907bytes | 全試行同じ |
| VP8 packet encode | 26.415ms | 24.687〜27.389 |
| packet検査/decode/結果copy | 14.535ms | 14.221〜15.437 |
| PNG encode | 37.323ms | 36.257〜40.950 |

raw BGRは2,764,800bytes。単純に30fpsを仮定したpayload量はVP8 packet約24.46Mbps、PNG約245.26Mbps、raw約663.55Mbps。**測定したネットワーク帯域・実FPS・matunuc/GPUPC性能ではない。** WebRTC/DTLS/SCTP等のoverheadや既存映像/操縦との同時負荷は含まない。追加encodeが必要な構成では、既存のvideo encode時間とも別に負荷が増える。

VP8は非可逆で、この1枚の画素値の平均絶対差は約1.816/255。画像の構図/解像度は同じでも元画像とpixel hashが同じとはしない。測距精度やYOLO結果の同一性を認定する数字ではない。PNGはpixel一致を確認したが、重いためライブ採用の結論にはしない。

## 現時点の判断と次に残す作業

一体packet方式では、時計同期を必須にせず「どの画像のcandidateか」を構造的に保持できる。**一方、実ライブ方式への採用は未決定。** 特に約100KBのpacketを、そのまま単一DataChannel messageで送れるとは仮定しない。試作はpacketヘッダ最大8KiB/画像最大2MiB、media PTS uint32のspan内で、新streamへの更新が必要。

次は以下を実機なしで進められる。

1. DataChannel等への分割/再構成を行うなら、有界メモリ・途中欠落・再接続・新旧混在・期限切れ・backpressure時の最新優先破棄を設計/試験する。画像圧縮とdecodeをRTC callbackへ直接置かない。
2. 既存video/操縦を維持しつつ追加圧縮/帯域を許容できるか比較する。必要なら負荷の低い統合方式を再検討し、private RTP monkey patchを無断導入しない。
3. 方式を選んでからsenderのcapture/odom履歴とGPU測距入力へopt-in接続し、初めて実通信確認の手順を提示する。元計測鮮度、現取付の車体TF/車幅/障害物点の意味、FFB接続は別のgate。

現在、GPUPC反映・追加撮影/走行・時計設定・challenge/G923の再試験をユーザーへ求める段階ではない。

## 検証と再現

新23＋前日のsender-frame30＋既存odom/操縦/FFB/受信記録/native codec等を合わせて**197成功、0失敗、3.39秒**。先行の1失敗/52成功は、テストがPyAV C拡張の変更不能なcreate属性をmockしようとしたため。mock対象をmodule属性へ修正し、productionの検査を緩めず全件再実行した。正式checkのpacket23件も成功・skip0。

前日のsender-frame部品と既存sender/receiver/capture/odom/FFB relay/publisherはbyte不変、旧距離/表示12ソースも正式監査SHAと一致。ネットワーク・ROS・カメラ・G923は起動せず、今回分はローカル未commit/未push。11/16終了commitとは分離している。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-17/frame_motion_packet_r01/check.py --output-dir Experimental_results/2026-11-17/frame_motion_packet_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_driver_frame_packet.py tests/test_driver_frame_motion.py tests/test_driver_odometry_observation.py tests/test_driver_motion_integration.py tests/test_collision_ffb_relay.py tests/test_collision_ffb_publisher.py tests/test_driver_sender_clock_observation.py tests/test_driver_telemetry_recording.py tests/test_theta_rtc_diagnostic.py
```

解析PC向けの再現コマンド。output名は未使用にする。GPUPCへこの絶対パスを入力する手順ではない。

## 設計の出典

[VP8 RFC6386 §9.1](https://www.rfc-editor.org/rfc/rfc6386#section-9.1)のkeyframe header/寸法と、[aiortc1.14.0 VP8実装](https://github.com/aiortc/aiortc/blob/1.14.0/src/aiortc/codecs/vpx.py)を確認。実装はPyAV公開CodecContext/Packetを用いる。既存RTPのorigin問題は[11/16実codec試験](../../2026-11-16/sender_frame_motion_r01/README.md)を継承。今回のheaderだけで任意悪意bitstreamを安全に処理できると認定したわけではなく、外部入力へ公開する前にtransport/worker隔離・資源制限を検討する。
