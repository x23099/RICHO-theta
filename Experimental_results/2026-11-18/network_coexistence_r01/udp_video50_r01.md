# 次の実行：通常映像を維持し50 Mbps・10秒

> **11/18実施済み（r01・r02の2回）。** r01は欠損114/52,079（0.2189%、6〜7秒）、r02は151/52,079（0.2899%、3〜4秒）。6〜7秒の周期性は再現せず棄却。結果は[1回目](udp_video50_report_r01.md)・[2回目](udp_video50_report_r02.md)。**50 Mbpsはprobe.pyの上限であり、この系列の増量は終了。** 再試行する場合のみoutputを`r03`へ変え、serverから開始する。

通常映像あり25 Mbps（実測 受信24.880 Mbps、欠損14/26,040＝0.0538%、目視の停止/大きな乱れなし）を確認済み（[比較報告](udp_video25_report_r01.md)）。**映像をそのまま流し、今回だけ50 Mbpsへ増量する。** 50 Mbpsは`probe.py`の上限であり、これ以上のrateは指定できない。新Git反映・再インストールは不要。追加撮影・画面録画・コーン位置合わせ・走行は不要。

## 0. 映像が流れていることの確認（必須）

**この確認をしないと「映像あり」条件が成立しない。** 過去に、映像ウィンドウを出さないまま「映像あり」として実施した例がある。

1. GPUPCで受信UIを起動する。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
bash src/start_theta_receive_rtc.sh
```

2. matsunucで送信を起動する。**受信側IPは必ず明示する**（既定値`150.89.169.70`はGPUPCではない）。

```bash
cd /home/matunuc/theta_ws
bash src/start_theta_stream_rtc.sh 150.89.169.96 /dev/video0
```

3. GPUPCの「THETA S Driver View with Classic Analog Cluster」ウィンドウで映像が更新されていることを確認する。カメラ前で手を振ると判別しやすい。

機体を停止し、新たなG923出力は起動しない。映像プロファイル/設定は前回と同じにする。別の大容量転送やGit操作は試験中に行わない。

## 1. GPUPCで先に待機

```bash
cd /home/hsr/yopi_ws/RICHO-theta
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py server \
  --local-ip 150.89.169.96 --peer 150.89.169.207 --interface wlp46s0f0 \
  --rate-mbps 50 --condition normal-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_gpu_video50_r01
```

## 2. 待機表示から45秒以内にmatsunucで送信

```bash
cd /home/matunuc/theta_ws
python3 Experimental_results/2026-11-18/network_coexistence_r01/probe.py client \
  --local-ip 150.89.169.207 --peer 150.89.169.96 --interface wlo1 \
  --rate-mbps 50 --condition normal-video --confirm-owned-peers \
  --output-dir recordings/2026-11-18/network_udp_camera_video50_r01
```

UDP単一stream/1200-byte payload/送信10秒、目標50 Mbps（約62.5 MBのpayload、実protocol overhead別）。server全体45秒、client全体25秒の上限は変わらない。own IP/peer routeを実行前に確認し、不一致なら通信前停止する。

試験中はGPUPCの映像を見る。停止・大きな乱れがあればCtrl+Cで中止してよい。異常が出ても出力フォルダを消さず、その結果を提出する。firewall・driver・CUDA・ROS/操縦設定は変更しない。

## 3. 提出

- GPUPC：`recordings/2026-11-18/network_udp_gpu_video50_r01/submission.tar.xz`
- matsunuc：`recordings/2026-11-18/network_udp_camera_video50_r01/submission.tar.xz`
- 「映像の停止/大きな乱れ：あり／なし」の観察メモ
- 映像ウィンドウが実際に更新されていたことの確認

圧縮は自動。コピー先で `udp_gpu_video50_r01.tar.xz` / `udp_camera_video50_r01.tar.xz` と改名してよい。再試行が必要なら両outputをr02へ変えてserverから開始する。過去の結果は上書きしない。

50 MbpsではPNG 5 Hzの必要量約40.49 Mbpsを単独では超えるが、通常映像と実protocol overheadが別に必要であり、10 Hzの約80.98 Mbpsには届かない。この結果でもPNG live採用は決まらない。異常時は増量せず、必要なら同rateの映像なしで切り分ける。定量fps/遅延・元鮮度・制御/FFBの適格性は未承認のまま。

なお、5 Mbpsの実際の映像あり条件は未取得。25 Mbpsで中心的な比較は済んでいるため、必要になった時点で追加する。
