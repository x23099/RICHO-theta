# 保存画像による併走負荷試験計画

複雑な性能評価。ライブ採用・実機性能の認定ではなく、既存videoと追加packetのCPU/生成bytes/最新破棄を局所測定する。

1. 11/16 pinと11/13保存native evidenceの原本SHAを既存監査へ照合。画角/解像度/画素を変更せずメモリで扱い、圧縮/復号カメラ画像を再保存しない。
2. installed aiortc 1.14.0のVp8Encoderを持続インスタンスとしてworkerで動かす。motion-nativeのBGR入力1280×720/30Hzを模し、target_bitrate=1.5Mbpsへ固定する（現接続の実bitrateやCLI15Mの達成を意味しない）。peer/camera/ROSは作らない。
3. 追加側は前段の実FramePacketChannelSender/専用encode workerを使い、fake sinkへ即時drainする。5/10/30Hzをbaseline0Hzと比較。時間/odom/sequenceは再生時の合成fixtureであり実画像の計測との結合ではない。
4. 静止画像repeatと保存4枚のdiscontinuous切替を分離。各条件warmup0.5秒＋計測3秒、2反復、2反復目は逆順で実行する。video pending1、追加pending1の最新優先、timer tick欠落、encode時間、capture代用の投入→send完了、初片数/完成組数、生成bytes、process CPU/window wallを保存する。
5. 固定しきい値で性能をPASSにせず、失敗/期限超過/欠落もそのまま記録。CPU比はprocessの使用core相当値でhost全体の使用率やFFB latencyではない。fake sinkにSCTP/DTLS/通信制限/受信decode/YOLO/操縦処理は含めない。
6. 数値の再集計を試験し、入力/実装/runtime SHA不変を確認。結果から次の比較候補rateを絞るが、実機を使わない段階でライブ採用と呼ばない。Git書込み/日報作成はしない。

根拠: installed aiortcのencoder/run_in_executorとnative trackを読んで比較層を限定。[上流vpx.py 1.14.0](https://github.com/aiortc/aiortc/blob/1.14.0/src/aiortc/codecs/vpx.py)、[PyAV VideoFrame](https://pyav.org/docs/stable/api/video.html)。private RTP/SCTP属性や既存runtimeは変更しない。
