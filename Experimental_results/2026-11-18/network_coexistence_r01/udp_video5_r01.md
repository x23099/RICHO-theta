# 次の実行：通常映像あり、5 Mbps・10秒

映像なしの実測は受領済み。送信6,249,600 bytes/10.000106秒、受信区間集計6,249,600 bytes/10.042234秒、欠損0。今度は**通常映像を流したまま同じ5 Mbps**で比較する。既存probe.py/collect.pyは変更していないため、この試験のための新コード反映・再インストールは不要。

## 1. 普段の映像送受信を開始

普段の方法でmatsunucから映像を送り、GPUPCで映像が更新されていることを確認する。既存の距離表示が有効ならそのままでよい。新しいPNG packet設定や操縦/FFB設定は追加しない。**機体は動かさず、G923への新たな出力は起動しない**。追加撮影・画面録画・コーン位置合わせは不要。

普段使用している映像プロファイルを変えない。開始時にすでに映像が停止/乱れている場合は、試験を始めずその状態を伝える。別の大容量転送やGit操作は試験中に行わない。

## 2. GPUPCで先に待機

```bash
cd /home/hsr/yopi_ws/RICHO-theta
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py server \
  --local-ip 150.89.169.96 --peer 150.89.169.207 --interface wlp46s0f0 \
  --rate-mbps 5 --condition normal-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_gpu_video5_r01
```

## 3. 待機表示から45秒以内にmatsunucで送信

```bash
cd /home/matunuc/theta_ws
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py client \
  --local-ip 150.89.169.207 --peer 150.89.169.96 --interface wlo1 \
  --rate-mbps 5 --condition normal-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_camera_video5_r01
```

試験中に、GPUPCの通常映像が停止したり、大きく乱れたりしないかを見る。異常があれば試験をCtrl+Cで中止してよく、負荷を増やさない。これは目視申告であり、fpsやcapture-to-display遅延を定量計測したとは扱わない。

## 4. 提出するもの

- GPUPC：`recordings/2026-11-18/network_udp_gpu_video5_r01/submission.tar.xz`
- matsunuc：`recordings/2026-11-18/network_udp_camera_video5_r01/submission.tar.xz`
- 一言の観察メモ：「映像の停止/大きな乱れ：なし」または「あり（状況）」、普段と異なる映像設定があればその内容。

手動圧縮不要。コピー先で `udp_gpu_video5_r01.tar.xz` / `udp_camera_video5_r01.tar.xz` と改名してよい。過去のidle5結果を上書きしない。新outputが既に存在する場合は両側をr02へ変え、serverから再開する。IP/経路不一致・timeout等ならfirewallを変更せずログを送る。

この比較後に25/50 Mbpsへ進めるか判断する。5 Mbpsで異常がなくても、必要量約40.49/80.98 MbpsのPNGを5/10 Hzで運べることや、SCTP/DTLS・元鮮度・測距・制御・FFBの適格性を認定しない。
