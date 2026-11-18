# 次の実行：映像なし、5 Mbps・10秒の有限UDP試験

11/18の両PC採取結果を使用する。iperf3の追加はユーザー承認済み。この資料・probe.pyを両PCへGit経由で反映してから実行する。**この試験では実際に通信する**。カメラ映像はまだ送らず、機体停止・G923出力停止のままでよい。測距推論・追加撮影・画面録画は不要。

今回の端点：matsunuc `150.89.169.207 / wlo1` → GPUPC `150.89.169.96 / wlp46s0f0`。同じ `/24` だがpeer疎通は未検証。probe.pyは各実行前に「local IPが指定interfaceに存在すること」と「peerへのローカル経路のdev/prefsrcが指定どおりであること」を検査する。不一致なら通信せず停止する。DHCP等でIPが変わった場合、古い値を無理に使わず再採取する。

## 1. 両PCで一度だけ導入

```bash
sudo apt install --no-install-recommends iperf3
iperf3 --version
```

「iperf3をdaemon/serviceとして自動起動するか」と聞かれたら **No／いいえ** を選ぶ。この試験に常駐サービスは不要。インストールやversionでエラーが出たら、その出力を送る。ドライバ・CUDA・Python環境・firewallの設定は変更しない。

## 2. 先にGPUPCで待機を開始

```bash
cd /home/hsr/yopi_ws/RICHO-theta
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py server \
  --local-ip 150.89.169.96 --peer 150.89.169.207 --interface wlp46s0f0 \
  --rate-mbps 5 --condition no-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_gpu_idle5_r01
```

`Waiting up to 45 seconds...` と出たら、**45秒以内に**次のmatsunucコマンドを実行する。指定IPのport5208だけで1接続を受けて終了し、待機・試験を含めプロセスは最長45秒で終了する。5002番の映像offerとは別。認証サーバーではないので、この短い試験以外は起動したままにしない。`--peer` はローカル経路の確認であり、serverのアクセス制御ではない。想定外peer接続はログ監査で不採用にする。

## 3. matsunucで10秒送信

```bash
cd /home/matunuc/theta_ws
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py client \
  --local-ip 150.89.169.207 --peer 150.89.169.96 --interface wlo1 \
  --rate-mbps 5 --condition no-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_camera_idle5_r01
```

こちらはUDP単一stream、目標5 Mbps、payload1200 bytes、送信10秒。制御TCP接続のtimeoutは3秒、clientプロセス全体は最長25秒。無制限TCP送信・逆方向・複数stream・自動増量・走行は行わない。serverはpeerが指定した試験設定を受けるため、wrapperの `--rate-mbps 5` がserver側で他clientの負荷を制限するわけではない。

通常は両PCに `State: process_completed_NEEDS_RESULT_REVIEW` と `Saved:` が出る。「プロセス完了」は受信量や遅延が合格した意味ではない。timeout/接続拒否等の失敗でも可能な限りログを残し、失敗を成功へ補完しない。接続できなければfirewallを勝手に開けず、ログを提出する。

## 4. 2ファイルを提出

- GPUPC：`recordings/2026-11-18/network_udp_gpu_idle5_r01/submission.tar.xz`
- matsunuc：`recordings/2026-11-18/network_udp_camera_idle5_r01/submission.tar.xz`

自動圧縮済み。コピー先で `udp_gpu_idle5_r01.tar.xz` / `udp_camera_idle5_r01.tar.xz` と改名すると区別できる。metadata・iperf生JSON・stderr・outcomeの4点のみで画像/重みなし。既存フォルダの上書きは拒否する。再試行が必要なら**両コマンド**のoutput末尾をr02へ変更し、serverから再開する。原ログを削除しない。

## その後

この結果で実peer/protocol/duration/受信量/loss/jitterを確認後、通常映像ありの同じ5 Mbps条件を比較する。その後25→50 Mbpsを段階的に検討し、映像に異常があれば増量しない。NICの受動採取は必要時に併用できる。

iperf3のjitterは一方向遅延や露光鮮度ではなく、UDPの受信量もSCTP/DTLS/PNG受理の保証ではない。5 HzのPNG必要量約40.49 Mbps、10 Hz約80.98 Mbpsに通常映像/overheadが加わるため、この5 Mbps試験だけでPNG live採用はしない。PC時計同期は要求せず、測距・制御・FFBの適格性は未承認のまま。

引数の根拠：[ESnet公式マニュアル](https://software.es.net/iperf/invoking.html)、[3.9公式マニュアル](https://github.com/esnet/iperf/blob/3.9/docs/invoking.rst)。手元のiperf3 helpで必要optionの存在も確認してから起動する。今回こちらでは導入・実通信・listener・機体操作は行っていない。
