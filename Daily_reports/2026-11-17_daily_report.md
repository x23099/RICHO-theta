# 2026-11-17 日報：時計同期に依存しない画像・運動一体packetの試作

## 1. 到達点

**画像と運動情報を別々の到着順で推測せず、一つのpacketとして受け渡す独立部品を実装・ローカル検証した。** 先頭/途中フレーム欠落後も、独立VP8 keyframeと当該metadataを取り違えずに復元できることを確認した。

PC間時計同期や時刻換算は使わず、既存challenge方式をFFBの期限判定に活用する方針を維持。今回の試作はまだ実行中の映像・GPU測距・ROS・操縦・G923へ接続していない。既存RTP映像の受信フレームにmetadataを貼れたという成果でもない。

本日扱いの作業は、前回ユーザーが11/16終了後に「11/17の日付の作業として続ける」と指定した枠を含む。正式auditの実行UTCは2026-11-16T11:24:28+00:00であり、11/17へ偽装しない。今回はこの成果を確認して日報へまとめた。11/18分の後続成果とは分離する。

## 2. 実施条件・Git状態

- 解析PC robo25で、保存画像・合成運動fixture・メモリ内codec・単体/回帰試験を使用。新規撮影・実機走行・GPUPC反映・ROS/WebRTC実通信・G923出力なし。
- 入力画像は11/16のpin5186、session e52bb32f03d6488ebf37d769f46ec37a、1280×720 dual-fisheye。元PNGのSHAは`7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89`で正式監査に一致。
- **運動metadataは合成fixtureであり、この実画像に対応する実測odomではない。** 元画像file/入力画素は不変、encode/decodeしたカメラ画像は再保存していない。
- PyAV16.1.0/NumPy1.24.4、既存libvpxを使用。追加package導入やaiortc本体の改変なし。
- 開始時HEADはc05ff48（11/16日報等）、本日commitはなし。今回までの変更はHANDOFF.mdと新packet module/tests/11/17成果物。既存の未コミット成果を引き継ぎ、無関係な変更はない。
- ユーザーがGit pushを行うため、**今回こちらではcommit・push・pullを実行しない。** 11/16のpush完了実績と、本日の未commit状態を分離する。

## 3. 設計・実装

[計画](../Experimental_results/2026-11-17/frame_motion_packet_r01/implementation_plan.md)、[実装](../src/driver_frame_packet.py)、[正式監査](../Experimental_results/2026-11-17/frame_motion_packet_r01/results_r01/audit.json)。

### 3.1 方式の比較

| 方式 | 判断 |
|---|---|
| 既存RTP映像＋連番/先頭PTSによる別metadata照合 | 先頭欠落時にoriginが変わるため不採用 |
| aiortc内部の識別hook | 保守/version/再送/decoder境界に課題。runtime monkey patchはしない |
| PNG＋metadata | lossless照合は可能だがサイズ/圧縮負荷が大きい可能性 |
| 独立VP8 keyframe＋metadata一体packet | オフライン試作として採用。ライブ採用は保留 |

### 3.2 部品の境界

- 長さと全体SHA256付きの有界envelopeへ、独立VP8 bitstreamとsender frame motion candidateを一緒に格納。header最大8KiB/payload最大2MiB、media PTSはuint32の範囲に限定。
- 厳密JSON、重複key/NaN/未知schema/不正型/認定flag昇格を拒否。既存source candidateを元選択観測から再検査する。
- 可視keyframe・1280×720をdecode前に検査。他frame参照を使わず、先頭/途中欠落後のpacketも独立decode。
- 受信器でsender/stream ID・順序・重複/逆順を検査。失敗時は旧画像/運動pairを消し、close/時計逆行後に復活させない。受信後の経過だけをreceiver時計で検査し、PC間の時計差を引かない。
- SHAは誤結合/破損検査であって認証ではない。送信callerが最初から誤った画像とmetadataを組にしたケースや、元計測/露光の鮮度を保証しない。全physical/FFB/ROS認定flagはfalseを維持。

## 4. 定量結果

同じ保存画像1枚を5回処理した結果。[全試行CSV](../Experimental_results/2026-11-17/frame_motion_packet_r01/results_r01/codec_samples.csv)。

| 項目 | 中央値 | 観測min〜max |
|---|---:|---:|
| VP8画像＋metadata packet | 101,927bytes | 101,924〜101,960 |
| VP8画像payload | 99,903bytes | 全試行同じ |
| PNG比較payload | 1,021,907bytes | 全試行同じ |
| VP8 packet encode | 26.415ms | 24.687〜27.389 |
| packet検査/decode/copy | 14.535ms | 14.221〜15.437 |
| PNG encode | 37.323ms | 36.257〜40.950 |
| VP8 decoded画像の画素値平均絶対差 | 1.816/255 | 全試行同じ |

raw BGRは2,764,800bytes。30fpsを単純仮定したpayload量はVP8 packet約24.46Mbps、PNG約245.26Mbps、raw約663.55Mbps。ただしこれは**ネットワーク実測・ライブFPS・matunuc/GPUPCの性能ではない**。既存映像のencodeやSCTP/DTLS overheadとの同時負荷も含まない。約100KBpacketを単一DataChannelで送れるとは仮定しない。

VP8は非可逆で元画像とpixel hashは一致しない。画素差は測距誤差でもYOLO結果の一致保証でもない。PNGはpixel一致を確認したが、負荷面からライブ採用を決める根拠としては不足する。

## 5. 検証・不変性

| 試験 | 結果 |
|---|---:|
| packet新規試験 | 23成功、skip0 |
| sender-frame・odom・操縦・FFB・記録・codec等の関連suite | 197成功、0失敗、3.39秒 |
| 正式checkのpacket試験 | 23成功、skip0 |
| 保存画像codec比較 | 5/5往復metadata一致、元file/画素不変 |
| 旧距離/表示source | 12ファイルSHA一致 |

23件は197件に含まれ、独立実験数へ加算しない。先頭/途中欠落、別stream、入替え、破損、重複・逆順、保留値、停止0・符号、cache失効、close/受信時計逆行等を確認。初回1失敗はPyAV C拡張のimmutable属性をmockしたテスト側の誤りで、module属性へのmockへ修正しproductionの検査を緩めず再実行した。

既存webrtc_stream/webrtc_receive_ui/capture/odom observer/FFB relay・publisher、前日のsender-frame部品は無変更。既存距離表示や操縦の回帰試験を維持。構文とgit diff --checkは確認済み。今回日報作成時は同じ入力/コードの成功結果を再利用し、codec比較を新たな試行として繰り返していない。

## 6. 成果物と残課題

[代表資料2点](../Experimental_results/2026-11-17/report_assets/README.md)はpacketサイズ図とcodec時間図。元CSV/集約CSV/生成script/入力出力SHAで追跡可能。新規カメラ画像がないため、無関係な画像や加工したcamera frameは追加していない。

ライブ採用・capture/odom取得点・GPU測距入力の接続は未実装。元計測鮮度、現取付の車体TF/車幅/障害物点の意味も未解決。既存challengeの成功だけでそれらを認定しない。

日報作成後はユーザー指定の**11/18扱い**で、packetの有界分割/再構成、欠落・期限・再接続・新旧混在、backpressure下の最新優先破棄をローカル実装/検証する。圧縮/decodeをRTC callbackへ置かず、実ネットワークや操縦への影響は別段階で確認する。現時点で追加撮影/走行・GPU反映・G923試験を要求しない。
