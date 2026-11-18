# PNG frame/motion packet の実回線 transport 試験（案A）r01

## 目的

保存画像・offlineでのPNG/CUDA比較は完了している。ここでは**実際のSCTP/DTLS DataChannel**に、既存のPNG packet encode → fragment → 再構成 → 期限判定をそのまま通し、通常映像と同時に使ったときに**frame単位で何が届き、何が落ちるか**を測る。

これは「PNG live採用」の可否を直接決める試験ではない。測るのは転送の成立だけ。

| 測る | 測らない |
|---|---|
| 送信side: offered / handed off / fragments | 通常映像のfps・停止 |
| 受信side: completed / published / gaps | 片方向遅延（PC間時計を使わない） |
| receiver内の再構成・decode・期限落ち | 測距精度・接地・車体基準 |
| frame到達率（published / handed off） | ROS送信・FFB・G923 |

**推論は起動しない。ROSへも出さない。G923/FFBへは接続しない。** `usable_for_ffb=false` を維持する。

## 前提

- 両PCに今回の変更をGitで反映済みであること（反映はユーザー側）。
- 機体は停止。G923出力は起動しない。
- 通常映像（`webrtc_stream.py` → `webrtc_receive_ui.py`）は普段どおり動かす。今回は同一peer connectionにpacket channelを追加する。
- 追加撮影・画面録画・走行・コーン位置合わせは不要。

## 1. probe出力ディレクトリを作る（両PC）

```bash
# GPUPC
mkdir -p /home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-18/png_link_probe_gpu_r01
# matsunuc
mkdir -p /home/matunuc/theta_ws/recordings/2026-11-18/png_link_probe_camera_r01
```

既存ディレクトリは上書きしない。再試行は`r02`へ変える。

## 2. GPUPC：受信UIをprobe付きで起動

```bash
cd /home/hsr/yopi_ws/RICHO-theta
bash src/start_theta_receive_rtc.sh --frame-packet-probe \
  recordings/2026-11-18/png_link_probe_gpu_r01
```

起動ログに `Transport-only packet probe enabled` が出ること。映像ウィンドウが出るまで待つ。

## 3. matsunuc：送信をpacket付きで起動

```bash
cd /home/matunuc/theta_ws
bash src/start_theta_stream_rtc.sh --motion-native \
  --frame-motion-packets --frame-packet-hz 5 \
  --frame-packet-probe-dir recordings/2026-11-18/png_link_probe_camera_r01 \
  --receiver-ip 150.89.169.96 --device /dev/video0
```

- `--frame-packet-hz 5` は5 Hz。10 Hzは今回試さない。
- 受信側IPは**必ず明示**する（既定の`150.89.169.70`はGPUPCではない）。
- 起動ログで `Optional packet input withheld` が出ていないことを確認する。出た場合はpacket channelが成立していない。

## 4. 30秒流して止める

1. GPUPCの映像ウィンドウで、映像が更新されていることを確認する（カメラ前で手を動かす）。
2. そのまま**30秒**待つ。機体は動かさない。
3. matsunucで Ctrl+C → GPUPCで Ctrl+C（順序はどちらでもよいが、両方必ず止める）。

停止後、両PCに以下ができていること。

```bash
# GPUPC
cat /home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-18/png_link_probe_gpu_r01/receiver_probe.json
# matsunuc
cat /home/matunuc/theta_ws/recordings/2026-11-18/png_link_probe_camera_r01/sender_probe.json
```

## 5. 提出

- `sender_probe.json`（matsunuc）
- `receiver_probe.json`（GPUPC）
- 映像の停止・大きな乱れ：あり／なし
- 起動ログに `withheld` が出たかどうか

## 判定の見方

解析側で `audit_probe.py` に通し、次を出す。

| 指標 | 意味 |
|---|---|
| `frames_handed_off` | senderがchannelへ渡し切ったframe数（5 Hz×30秒で約150） |
| `receiver_frames_completed` | 全fragmentが揃い、整合検査を通ったframe数 |
| `receiver_frames_published` | 受信側の期限（初片から0.2秒）内にconsumerへ渡ったframe数 |
| `frame_completion_ratio` | completed / handed_off。fragment欠損・replacedの影響 |
| `frame_publication_ratio` | published / handed_off。期限落ちを含む実効到達率 |
| `receiver_sequence_gaps` | 受信したframe番号の飛び（欠損frame数） |

`receiver_sequence_gaps` と `frames_replaced`/`expired` が主な失敗要因になる。0.2秒の期限は**受信側の初片到着からの経過**であり、PC間時計同期や撮影時刻の鮮度ではない。

## ローカル検証（実通信なし）

[verification_r03/audit.json](verification_r03/audit.json)、[テスト出力](verification_r03/tests.txt)：**372 passed / 0 failed / 0 skipped（16.74秒）**。probe本体8件と監査5件を含む。実RTC接続・カメラ・ROS/G923は起動していない。probeは既定offで、ディレクトリ未指定なら従来経路と同一。r01/r02は監査スクリプト修正前の履歴として残し、**r03を正式採用**する。

## 実測結果（r01）

[transport_report_r01.md](transport_report_r01.md)：296 frameを渡して296 frame完成・296 frame到達（ratio 1.0）。ただしPNGは約128 KB/frame、payload上限4.54 Mbpsで、**40.49 Mbps級の共存は未検証**。代表シーンでの再試験が必要。

**注意：** この段階で`src/webrtc_stream.py`と`src/webrtc_receive_ui.py`を既定offのまま変更したため、`network_coexistence_r01/verify_udp*.py`のfrozen source検査は現在のtreeでは停止する。保存済みUDP監査・検証JSONは変更していない。

## 中止・切り分け

- `frames_handed_off=0`：packet channelが成立していない（`withheld`ログ、`activated=false`を確認）。
- `receiver_frames_completed=0`：fragmentが届いていない（`messages_sent`と`completed`を比較）。
- `completed`は多いが`published`が少ない：decoder/consumerが期限に間に合っていない（`inbox_peak_queued`、`delivery_latency_max_sec`を見る）。
- 映像が大きく乱れたら中止してよい。出力は消さず提出する。
- firewall・driver・CUDA・ROS/操縦設定は変更しない。
