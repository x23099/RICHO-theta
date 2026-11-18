# PNG原画素・運動情報のatomic packet試作

複数ファイルの形式・期限・破損時動作に関わる作業として扱う。ユーザーの続行承認に基づくoffline実装で、実通信・カメラ・GPU・操縦・G923へ接続しない。

## 根拠と選定

- 前段frame_packet_preservation_r01/results_r03ではPNG既定が元GPU入力の全画素と元判定を4枚とも維持した。約1MB/枚で帯域は課題のまま。
- driver_frame_packet.py / flow.pyのVP8形式と既存runtimeは凍結。codecだけを偽装して既存経路に通さず、別magic/schemaのPNG packetと別fragmentを追加する。既存候補検証checked_candidateのみ共用する。
- PNGのchunk/CRC/順序は[W3C仕様](https://www.w3.org/TR/png-3/#5DataRep)に基づく。ただし一般PNG readerではなく、OpenCV既定encoderが出すIHDR・IDAT・IENDだけのnative RGB8/非interlace profileに限定する。余剰chunk・末尾・過大寸法・解凍後超過は拒否する。
- payload 2MiB、header 8KiB、fragment最大16KiB、初片から200msを維持。上限超過は失敗し、期限延長や画素削減で通さない。

## 実装と検証

1. 画像pixel SHA・source candidate・media PTSを同じSHA付きpacketに格納し、寸法・exact fields・false権限を検証。SHAは事故検出であり認証・正しい撮影対応の証明ではない。
2. 1packet有界再構成、source scope/sequence、断片重複・欠損・入替え・改変・期限・時計逆行を検証。最初の到着時刻は重複で延長しない。新sequenceで旧packetを破棄する。
3. 復号前後とtake時に同じ受信側ローカル期限を検査し、失敗時に旧値を返さない。送信側時計との減算や露光時刻の認定はしない。
4. 保存4原画をメモリ内でPNG化・packet往復し全画素/候補一致、サイズと処理時間を計測。15/30/100Mbpsの理想直列化モデルで期限を評価する。実回線・SCTP/DTLS・運転映像共存とは区別する。
5. 新規テストと前段194の回帰、既存runtime SHA不変、原本SHA不変を保存する。

今回の範囲外: 実channel/送信queue接続、backpressure・5/10Hzの実負荷、実帯域、GPU再推論、元鮮度・接地・車体TF・FFB認定。これらを完了済みにしない。
