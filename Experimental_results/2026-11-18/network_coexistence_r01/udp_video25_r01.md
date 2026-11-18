# 次の実行：通常映像を維持し25 Mbps・10秒

> **11/18訂正：この手順のr01は映像送信・受信UIを起動せずに実施され、実際は映像なしだった。** 実際の映像あり25 Mbpsはr02として取得済み（[比較報告](udp_video25_report_r01.md)）。次は[50 Mbps](udp_video50_r01.md)。

通常映像あり5 Mbpsではpayload全量一致・欠損0、目視の停止/大きな乱れなしを確認済み。**映像をそのまま流し、今回だけ25 Mbpsへ増量する。** 50 Mbpsまで自動連続実行しない。新Git反映・再インストールは不要。追加撮影・画面録画・コーン位置合わせ・走行は不要。

機体を停止し、新たなG923出力は起動しない。通常映像が更新されていることを確認し、映像プロファイル/設定は前回と同じにする。別の大容量転送やGit操作は試験中に行わない。

## 1. GPUPCで先に待機

```bash
cd /home/hsr/yopi_ws/RICHO-theta
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py server \
  --local-ip 150.89.169.96 --peer 150.89.169.207 --interface wlp46s0f0 \
  --rate-mbps 25 --condition normal-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_gpu_video25_r01
```

## 2. 待機表示から45秒以内にmatsunucで送信

```bash
cd /home/matunuc/theta_ws
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py client \
  --local-ip 150.89.169.207 --peer 150.89.169.96 --interface wlo1 \
  --rate-mbps 25 --condition normal-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_camera_video25_r01
```

UDP単一stream/1200-byte payload/送信10秒、目標25 Mbps（約31.25 MBのpayload、実protocol overhead別）。server全体45秒、client全体25秒の上限は変わらない。own IP/peer routeを実行前に確認し、不一致なら通信前停止する。serverのpeer認証や他client負荷制限を追加したものではない。

試験中はGPUPCの映像を見る。停止・大きな乱れがあればCtrl+Cで中止してよい。異常が出ても出力フォルダを消さず、その結果を提出する。firewall・driver・CUDA・ROS/操縦設定は変更しない。

## 3. 提出

- GPUPC：`recordings/2026-11-18/network_udp_gpu_video25_r01/submission.tar.xz`
- matsunuc：`recordings/2026-11-18/network_udp_camera_video25_r01/submission.tar.xz`
- 「映像の停止/大きな乱れ：あり／なし」の観察メモ。設定や映像プロファイルを変えた場合はその内容。

圧縮は自動。コピー先で `udp_gpu_video25_r01.tar.xz` / `udp_camera_video25_r01.tar.xz` と改名してよい。再試行が必要なら両outputをr02へ変えてserverから開始する。過去の5 Mbps結果は上書きしない。

結果確認後に50 Mbpsへ進めるか判断する。25 Mbps成功でもPNG5 Hzの必要量約40.49 Mbps＋映像/overheadを満たしたとは言わない。異常時は増量せず、必要なら同rateの映像なしで切り分ける。定量fps/遅延・元鮮度・制御/FFBの適格性は未承認のまま。
