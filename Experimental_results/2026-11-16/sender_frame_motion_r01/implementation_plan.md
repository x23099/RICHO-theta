# 時計同期を前提にしない送信元フレーム・運動対応

2026-11-16。複雑・互換性に注意が必要な変更。ユーザーが既存challenge方式を踏まえた方針変更後の続行を依頼。

## 判断と範囲

- PC間時計対応の新規実装を中止する。9/17の時計差による拒否と9/24のchallenge方式hardware確認を再利用し、時計同期をFFB出力の必須条件に戻さない。時計観測の過去原本は削除・再解釈しない。
- 認識GPUと送信PCの時計を引き算する代わりに、送信元で画像のread-return時刻と、それ以前のodom callbackを同じmonotonic時計で対応させる部品を実装する。カメラ露光時刻やodomの計測時刻への同期を保証するものではない。
- 今回は独立部品とローカル試験まで。実行中のROS/映像/telemetry/距離表示/操縦/challenge/FFBへは接続せず、実機起動・ネットワーク送信・時計設定変更もしない。

## 実装

1. 既存driver_odometry_observation_v1の厳密検証を再利用。明示sender/stream ID・件数上限・callback/progress/画像処理待ちの許容値を持つ有界履歴を作る。許容値は呼出し側指定で、実機採用値やFFB安全期限を新規に既定化しない。
2. 新しいcallbackが画像取得より未来なら、履歴内の過去callbackだけを選ぶ。直近の過去callbackが無効・反復・古い場合は、それより古い有効値に戻らず保留。停止の実測0は保持し、未受信を0にしない。
3. 順序逆転・sender混在・時計異常は履歴を失効させ、新しいstream instanceでのみ再開。lock競合は待機せず保留、対応処理でIOや画像加工をしない。
4. 出力へcapture sequence/read-return時刻・sender media PTS・採用した元観測・callbackとstamp進行の経過・判定理由を入れる。全認定/制御flagsはfalse、元ROS stamp→PC時計の換算やclock bindingを生成しない。
5. 受信側はreceiver frame numberや先頭PTS=0からsender番号を推測しない。aiortc 1.14.0の実TimestampMapperとVP8 codecをローカル試験し、先頭欠落時のrebasingとcodec経路で保持できる情報を記録する。private実装へruntime hookを入れない。

## 次の境界

送信側の撮影/trackへこの部品を接続するには、画像取得とodom観測の取得点、stream IDの寿命、受信画像との厳密な識別を先に定める。今回のsource bundleを受信decoded画像へ結合済みと報告しない。画像とmetadataの到着順・連番・先頭PTSだけで代用しない。FFB challengeは指令期限の検査であり、古い観測を新鮮にする仕組みではない。
