# PNG送信待ち・混雑時の有界処理と連続負荷モデル

複数ファイルの時間制約・状態遷移に関わる作業として扱う。ユーザーの続行依頼に基づくoffline実装。実機・実通信・操縦/FFBには接続しない。

## 先行結果と設計

- lossless_frame_packet_r01で4枚×5反復の画素/元判定一致、初片200ms、payload2MiB/header8KiB/fragment16KiB、221テストを確認済み。
- 既存VP8 LatestPacketSenderの「進行中を毎回中断しない・最新pendingだけ保持・buffered量で停止・送信元ローカル年齢で破棄」をPNG専用に適用する。旧VP8/runtimeと前段PNG codec/fragmentは変更せず、protocol/layout定数とunpack検証を共用する別schedulerとする。既存VP8へのcodec偽装・私的prepared型の流用をしない。
- worker内で完成PNGを検証した後だけ1 active + 1 latest pendingを保持する。source順序・scope・sender側200ms、最大transport bufferを各handoffで検査。既にtransportへ渡したbytesの取消しはできないと明記する。
- 実RTC callbackへの接続は範囲外。同期offerのPNG検証時間をcallback上限内と主張しない。

## 評価

1. 新schedulerのsource order/PTS/時刻/期限/混雑/閉鎖/one-active-one-pending/最新置換/欠損後回復をテストする。
2. 保存4枚を順に循環する合成captureを5/10Hz、15/30/100Mbpsで4秒間モデル化する。各入力は元画素SHA一致のPNG payloadを再利用し、candidate/packet framingだけをフレームごとに生成する。新撮影のencode連続実測とは扱わない。
3. 仮想1ms tick、channel buffer 32KiB。送信CPU=前段のencode+初片前検査、受信CPU=初片後全仕事の画像別中央値を使う。single worker + latest pending（capture/decode待機）もモデル化し、段階ごとに置換/期限破棄を記録する。合成時計はsender/receiver別offsetで実装へ渡し、実装でPC間減算しない。
4. 停止/欠損/受信CPU低速/送信CPU低速/一方向500ms遅延を追加する。500ms遅延でローカル200msを満たすpacketも撮影から古くなり得ることをsimulation oracleで可視化し、source_freshnessを認定しない。
5. 正式結果・全trace・元画像/code SHA・前段221回帰を保存。既存成果の上書き、原画加工、期限・上限・HSV/ROI条件緩和なし。

未確認: 実回線容量、SCTP/DTLS/運転映像共存、実GPUPC/送信側CPUと5/10Hz、GPU推論/IPC/表示、元鮮度・露光/odom源時計・接地・FFB。モデルが通ってもlive採用しない。
