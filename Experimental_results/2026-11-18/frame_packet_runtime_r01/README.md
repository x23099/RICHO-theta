# 11/18：既定offの一体packet測距入力をruntimeへ接続

**送信元のcapture/odom観測から、同じpacketの画像をGPU認識用pipeへ渡し、返った結果へ元candidateを結び付ける経路を実装した。** 通常は無効。既存の運転映像/telemetry/controlを残し、実験modeで選んだ場合だけ測距入力をpacketへ切り替える。

[計画](implementation_plan.md)、[接続部](../../../src/driver_frame_packet_runtime.py)、[新規22ケース](../../../tests/test_driver_frame_packet_runtime.py)、[正式監査](results_r02/audit.json)、[397試験の出力](results_r02/tests.txt)、[代表的な結合結果](results_r02/representative_bridge_event.json)、[対応する認識process出力](results_r02/representative_measurement.json)。

今回の確認は**fake peer/channel＋実VP8 codec＋実local pipe＋既存MotionRangeEngine**。predictor/支持点/画像/odomは合成fixture。実network、カメラ、ROS、CUDA推論、G923を起動せず、距離精度やライブ採用・FFB利用を認定していない。

## 既定と実験mode

| 項目 | 既定 | 明示した実験mode |
|---|---|---|
| sender | 独立packet channel/追加odom購読/workerなし | `--motion-native --frame-motion-packets --frame-packet-hz 10`（5/10のみ） |
| receiver | `--motion-input rtp`：従来のRTP native tap | `--motion-distance --motion-input packet`＋従来のweights/profile/output等 |
| 運転映像 | 従来RTP | 従来RTPを維持。packet画像と同じframeとは主張しない |
| 認識model/pipe | 従来1本 | 同じ1本を再利用。二重YOLO起動なし |
| 片側だけ有効 | 従来動作 | 明示ackがなければpacket送信を開始しない／packet受信modeは保留。RTPへ自動fallbackしない |
| ROS/FFB出力 | 既存操縦のみ | 距離・candidateは操縦/FFBへ送信しない。全権限flags false |

10Hzは前段load比較からの**次の実験上限候補**であり、FFB更新rateの承認ではない。追加30Hzは選べない。現在取付のTF・車幅・障害物点の意味や物理認定を新たに定めてはいない。

## sourceと接続の束ね方

1. 既存`CaptureFrames` readerを共有し、追加カメラを開かない。既存native track/readerの実装自体は不変。専用producerが`after(sequence)`で得た元sequence/read-return時刻/画像を扱う。encodeと画像copyをRTC callbackへ追加しない。
2. 明示modeだけ追加の**観測専用**odom subscriptionを作る。新`OdometryObserver`の全callback snapshotをsender-local有界履歴へ渡す。telemetry購読やROS publish処理を改造しない。subscriberは運動指令を出さない。
3. source専用sender ID、新stream ID、5/10Hz、上限/期限/false flagsを厳密profileとしてHTTP offerへ添付。両端のapplied SDPから1つのapplication MIDと共通message上限を確認し、同じprofile/capのackが返るまで送信workerを開始しない。unknown/重複/不正型/整数0でfalseを偽装するprofile等は拒否。
4. 独立`theta-frame-motion-v1` channel objectを1本だけbind（unordered、maxRetransmits0）。labelは一意性や認証の根拠ではない。既存telemetry/control handlerは変更せず、独立listenerを追加する。private RTP/SCTP属性なし。HTTP/DTLSでの相手認証全般を新たに保証する仕組みではない。
5. receiverではpacketの元stream/capture sequenceを`NativeFrame.session/sequence`として既存pipeへ保持し、receiver内連番へ振り直さない。sourceのsender media PTSはpacket内でのみ使用し、表示RTPのPTSや到着順で結合しない。
6. bridgeは最新1＋inflight1のpacketを保持。旧IPCの厳密frame/result schemaで戻った同identityの結果だけへ、そのinflightのcandidateとpacket SHAをログで束ねる。candidateを画像と別の最新telemetryで置換しない。childは画像を認識し、parentが元metadataを保持する設計であり、candidateをGPU側へ無条件な制御入力として渡すものではない。

receiverの`motion_bridge_events.jsonl`へ`source_candidate`・`packet_sha256`・`input_source=independent_frame_motion_packet_NOT_RTP`を保存。`motion_distance_frames.jsonl`にもpacket由来の入力markerを保存する。`motion_engine_summary.json`はpacket mode、200ms、関係code SHAを記録する。

送信側camera read-returnは露光時刻でなく、odom callbackは元計測時刻とは限らない。`local_pair_available=true`でもsource freshness/物理精度/接地/車体座標の認定ではない。candidateのreceiver_frame_identity_verified等もfalseのまま。

## 無効化・期限・終了

- 欠けたnative/profile、能力不一致、ackなしでは測距を保留し、運転映像/既存操縦通信をrejectしない。packet mode中にRTPが届いても、その画像からpacket candidate付き測距を捏造しない。
- profileのstreamは再利用しない。新offerで旧packet入力を退役、古いpeerの遅延disconnect/resultで新scopeを失効・汚染しない。各HTTP handlerは自身のpeer参照でSDPを処理し、途中で置換された`self.pc`のSDPを誤使用しない。
- 初片受信からの**同じ200ms**を再構成/decode/pipe待ち/inference前後/結果受理/表示に含める。raw engineの標準設定が500msでもpacket modeで延長しない。sender側にも別の200ms read-return ageがあるが、両者の間の実transport遅延を測定・上限認定したことにはならない。
- 通常RTP modeの既存条件/表示/ログは維持する。packet modeのpanelには「独立packetの画像・元capture番号。表示中のRTPフレームとの一致は未認定」と追記し、運転映像そのものへ注釈・変換を施さない。
- source/codec/ingress失敗や重複channelはpacket入力だけ退役する。通常のROS publish/control関数、keyboard、challenge/FFB経路を変更していない。
- sender終了は既存daemon workerのdone状態を有限時間pollし、新しいexecutor queueを作らない。receiverは退役flag＋有限join、GPU pipeは従来のgrace/force終了を再利用する。停止できないworkerを停止済みと偽らない。受信raw画像/packetサイズ・queueの上限は前段を継承するが、全接続数/全heap/最悪CPUをハード保証したものではない。

## 検証と変更範囲

**22新規を含む関連397成功、失敗/skip0、12.52秒。** default camera/pipe/display/body guard/shutdown/rangeと、前段codec/fragment/worker/odom/telemetry/操縦/FFB回帰を含む。先行84成功・139成功・396成功は同じ試験を含むので加算しない。results_r01はCLIで1本のbridgeだけを作る追加試験・代表受理assert強化前の履歴、正式はresults_r02。

代表caseは元capture **723**。sourceの後退v=-0.2m/s・ω=+0.1rad/sを同じpacketに保存し、実codec→receiver actual offer handler→既存local pipe→既存range engineの723番の結果へ結合。正常caseのlocal期限内受理trueを確認。距離の1.23599…mは合成支持点からの値で、実画像/実測精度の結果ではない。

新試験では、既定off、片側だけ/無profile/型違い/上限/MID不一致、未受信nullと実測0の区別、未来/反復callbackを旧値で救済しないこと、rate上限、元sequence保持、stale/重複入力、old inflight metadataと新scope不混同、RTP fallback禁止、旧peer disconnect、重複channel、panelの入力区別等を確認した。

今回、以下5既存sourceへ意図したopt-in差分を追加した（byte不変とは報告しない）。旧SHAは書き換えず、before/afterを新監査へ保存した。

- `webrtc_stream.py`：明示modeの観測購読・channel・offer/ack・終了だけ。
- `driver_motion_camera.py`：共有readerの受渡し、早期validationとbinding cleanup。
- `webrtc_receive_ui.py`：明示modeの独立listener/ack、RTP測距tapからの分離、peer所有権/終了。
- `driver_motion_bridge.py`：入力選択、既存受理/event hookの既定挙動を保つ分離、packet panelの入力marker。
- `driver_motion_process.py`：packet入力markerと200ms gate/code metadata。

旧操縦関数/ROS node/keyboard/legacy cameraの固定AST一致試験が成功。旧距離監査12 componentのうち、bridge/processの2つは上記意図した変更、残る幾何/支持点/body guard/IPCなど10 componentはSHA一致。前段packet channel/fragmentとodom/clock/telemetry/FFB部品も変更なし。source frame/packetの厳密validatorを緩めていない。

初回のsource試験3件はfixtureが`base_link`のままで、明示した`base_footprint`条件を満たさず失敗。fixtureを修正しproduction条件は保持。初期のasync試験ではexecutor終了待ちで停止したため、自分が開始した試験を中断し、binding終了を既存done flagの有限pollへ変更した。制御経路やFFB停止機構を変更した対応ではない。正式結果は上記修正後に全回帰を再実行したもの。

今回カメラ画像の撮影/加工/再保存、実機操作、依存導入、Git書込み、日報作成はなし。先行の未commit成果も保全している。

## 次に行うこと（まだliveを起動しない）

次はGPUPC側の依存環境で保存native画像をpacketへ通し、再圧縮がYOLO/色支持点/測距の採否へ与える影響と認識負荷を比較する。今回の模擬通信試験だけでライブ採用や測距精度を決めない。双方の反映と必要な保存入力・weightsを確認してから、PC別の手順を提示する。**追加撮影/走行はまだ不要。**

将来の試験起動では、senderの既存native起動に`--frame-motion-packets --frame-packet-hz 10`を追加し、receiverの既存測距起動に`--motion-input packet`を追加する。weights/profile/output/comparison等は実施日と新規保存先を明示して選ぶ。ここは起動引数の対応説明で、現時点で機体や送受信を開始する指示ではない。片側だけ反映してRTPへfallbackさせない。

以前のcodec/load用checkは「runtime source不変」の当時のbaselineを検査するため、今回の意図した変更後はそのまま再実行して通る前提にしない。過去manifestのSHAを更新して通さず、今回のruntime監査を使う。

### 再現（解析PC、実機不要）

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/frame_packet_runtime_r01/check.py --output-dir Experimental_results/2026-11-18/frame_packet_runtime_r01/results_r03
```

未使用のoutputが必要。fake peer、合成画像/odom、fake predictor/support、local子processだけを起動し、結果と代表JSONを保存する。[aiortc公開API](https://aiortc.readthedocs.io/en/latest/api.html)とinstalled1.14.0のSDP parserを確認したが、別versionの互換性や実通信は未確認。
