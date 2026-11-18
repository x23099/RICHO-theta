# 通常映像との回線共存確認：準備計画

## 目的と範囲

保存画像のPNG/CUDA比較は完了した。fragment込み約1.01 MB/枚、5 Hzで40.49 Mbps、10 Hzで80.98 Mbpsという量が、通常映像と同じ実回線で扱えるかを次に確認する。これは必要データ量であり実回線の測定値ではない。

今回は独立した標準ライブラリの採取器と手順だけを追加する。WebRTC、PNG packet、ROS、操縦、G923、元画像、校正は変更しない。実通信・listener起動・インストールは実行しない。

## 順序

1. 両PCでIPv4・経路・interface・iperf3有無を読み取り採取する。既存launcherの固定IPを現在の接続先と見なさない。
2. 使用interfaceを確認した後、映像なし／通常映像ありの各30秒でNIC送受信カウンタを受動採取する。集計値は他プロセスを含み、映像bitrate・fps・空き容量とは呼ばない。
3. 両PCの対応・経路・操作者の実施意思を確認してから、別portの有限UDP試験を行う。単一stream、10秒、5→25→50 Mbpsの段階を候補とし、異常時は増量しない。最大帯域の探索や自動飽和を行わない。
4. 通常映像の停止・乱れの観察とUDP受信側結果を別々に記録する。UDPの結果をSCTP/PNGの実到着・露光鮮度・測距精度・FFB適格性へ読み替えない。

## 選択理由・出典

既存送受信器にはこの用途の回線計測がないため、計測のためだけのlive hook追加を避け、Linuxのinterfaceカウンタを外部から読む。能動試験候補は標準的なiperf3とし、新独自transportは作らない。iperf3はclient/server方式で、UDP試験にも制御接続を使用する。利用可能versionとhelpを先に採取し、未導入なら勝手に導入しない。

- [ESnet iperf3公式マニュアル](https://software.es.net/iperf/invoking.html)
- [iperf 3.9公式マニュアルソース](https://github.com/esnet/iperf/blob/3.9/docs/invoking.rst)（古い環境の互換確認用）
- repo: `src/start_theta_stream_rtc.sh`、`src/start_theta_receive_rtc.sh`、`src/webrtc_stream.py`、`src/driver_frame_packet_runtime.py`。

PC時計の同期は要求しない。受動採取はPC内monotonic差分のみ。時刻対応・capture-to-display遅延・物理距離・接地・制御・FFB・ROS送信の検証は本試験では行わない。

## 11/18 採取結果受領後の更新

両PCのarchiveを受領し、同subnetのup/default interfaceを各1件に絞れた。iperf3は双方未導入だったが、ユーザーから両PCへの追加承認を得た。そのため、受動採取を強制する順序にはせず、まず映像なし5 Mbps・10秒の小さい有限UDP試験へ進める。probe.pyはown IPとpeer routeを各実行直前に確認し、不一致なら送信/listenせず停止する。初回結果確認前に25/50 Mbps・映像あり・PNG liveへ一括展開しない。導入・実通信・firewall変更はこの解析環境から行わない。

## 検証

外部コマンド、sysfs、clockを模擬したunit testで、採取先の取り違え防止・個人情報最小化・既存出力の保全・カウンタreset・不正入力・archive内容を確認する。解析PCではread-only inspectのみ実行可能。能動ネットワーク試験や既存GPUベンチマークは再実行しない。
