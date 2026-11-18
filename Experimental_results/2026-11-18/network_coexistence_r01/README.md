# 実回線・通常映像併用確認 r01

現段階：**通常映像あり50 Mbpsを2回取得し、合成UDPの増量試験は終了**。[1回目](udp_video50_report_r01.md)は欠損114/52,079（0.2189%、6〜7秒）、[2回目](udp_video50_report_r02.md)は151/52,079（0.2899%、3〜4秒）。2回目は送信側が2〜3秒に44.6 Mbps、3〜4秒に55.4 Mbpsとpaceを乱し、その詰め戻しで受信側が落とした形。**「6〜7秒に周期的」という仮説は再現せず棄却**。操作者目視の停止/大きな乱れなし（2回目は「思います」の留保付き）。50 Mbpsは`probe.py`の上限であり、同一ツールでの増量は不可。**次は合成UDPではなく、実PNG/映像経路の試験へ移る**。実機のprobe/collectコードは不変で追加反映・再install不要。以下のinspectも再実行不要。新規撮影・画面録画・走行・コーン位置合わせ・GPU推論の再実行は不要。

**11/18訂正：** 以前の「通常映像あり5 Mbps」と「25 Mbps r01」は、映像送信・受信UIを起動しないまま実施されていた（操作者申告）。実際は映像なしであり、[5 Mbps訂正](udp_video5_audit_r01/condition_correction.json)・[25 Mbps訂正](udp_video25_audit_r01/condition_correction.json)に記録した。raw archiveと`audit.json`は書き換えていない。以降の手順には**映像ウィンドウが更新中であることの事前確認**を必須項目として追加した（[50 Mbps手順の0章](udp_video50_r01.md)）。

## 1. 最初に実行すること（通信負荷なし）

新しい変更を両PCへGit経由で反映する。反映方法の選択やpush/pullはユーザー側で行う。

**GPUPC**：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
python3 Experimental_results/2026-11-18/network_coexistence_r01/collect.py inspect \
  --role gpu --output-dir recordings/2026-11-18/network_gpu_r01
```

**matsunuc（カメラ側）**：普段 `src/start_theta_stream_rtc.sh` を起動しているリポジトリ直下で実行する。GPUPCの `/home/hsr/` は使わない。`pwd` と `git rev-parse --show-toplevel` で現在位置を確認できる。

```bash
python3 Experimental_results/2026-11-18/network_coexistence_r01/collect.py inspect \
  --role camera --output-dir recordings/2026-11-18/network_camera_r01
```

出力される **2つの `submission.tar.xz`** を提出する。区別用にコピー先で `network_gpu_r01.tar.xz` / `network_camera_r01.tar.xz` と改名してよい。各archiveは `report.json` 1点のみ。手動圧縮不要。既存outputは上書きしないので、再採取時だけ末尾をr02等へ変更する。

IPアドレス・interface・default route・iperf3 version/helpだけを読み取る。MAC/SSID・環境変数・プロセス一覧・画像・重みを採取しない。映像が起動中でも採取できる。新たな接続・port待機・ping・試験データ送信・sudo・インストール・時計同期は行わない。iperf3が無くても採取は完了し、未導入として記録する。

## 2. 結果確認後の受動観測

採取したIPと実際の接続先を照合し、使用interfaceを確定する。送信launcherの既存固定IP、VPN有無、NICの公称speedだけから実経路・空き容量を推定しない。既知の相手IPv4がある場合、inspectの `--peer 相手IPv4` はローカルのroute lookupだけを追加する（相手へは送信しない）。

使用interface確定後、同じPCで以下を映像なし／通常映像ありの各条件で採取する。`INTERFACE` は実際の名前に置換する。映像起動・停止は普段の手順を操作者が行い、採取器は操作しない。

```bash
python3 Experimental_results/2026-11-18/network_coexistence_r01/collect.py observe \
  --interface INTERFACE --seconds 30 --condition no-video \
  --output-dir recordings/2026-11-18/network_idle_r01
python3 Experimental_results/2026-11-18/network_coexistence_r01/collect.py observe \
  --interface INTERFACE --seconds 30 --condition normal-video \
  --output-dir recordings/2026-11-18/network_video_r01
```

これはinterface全体の送受信量・drop/error差分であり、映像専用bitrate・fps・空き帯域・一方向遅延の測定ではない。他の大容量通信は行わず、別の通信があれば条件メモに残す。両PCの時刻を対応させず、それぞれのmonotonic差分だけを使用する。

## 3. 能動試験の予定（実行は別手順）

両PCの住所・経路・iperf3 versionを確認してから、カメラPC→GPUPC方向の単一UDP streamを5→25→50 Mbps、各10秒で有限試験する。通常映像なし／ありを区別し、映像の乱れ・停止があれば増量しない。機体は停止したまま、G923出力は起動しない。5002番の映像offerと別portを使い、exact addressへのbind、one-off server、プロセスtimeoutを指定する。peerを推測したコマンド、無制限負荷、自動探索、daemon、firewall変更は用意しない。

11/18更新：5 Mbpsの映像なし結果、実際の映像なしだった「映像あり」5 Mbps、映像なし25 Mbps、実際の映像あり25 Mbps、実際の映像あり50 Mbps（2回）を受領済み。50 Mbpsはprobe.pyの上限であり、全rateのon/offを一括実行しない。欠損は25 Mbps映像あり14/26,040（6〜7秒）、50 Mbps r01 114/52,079（6〜7秒）、r02 151/52,079（3〜4秒）。6〜7秒の周期性は再現せず棄却。**合成UDPの増量は終了し、次は実PNG/映像経路の試験へ移る。**

この段階の結果でもPNGのlive採用は決まらない。UDPとSCTP/DTLSは異なり、PNG sender実装、NUC encode速度、送信待ち、受信処理、古い画像の破棄を含む実証は別。10 Hzの必要量約80.98 Mbpsに対して50 Mbpsまでの試験は不足し、5 Hz約40.49 Mbpsにも通常映像と実protocol overheadが別に必要。

計画・根拠は [implementation_plan.md](implementation_plan.md)。既存runtime/UI/操縦経路は未変更。

## ローカル検証

[verification_r01/audit.json](verification_r01/audit.json)、[テスト出力](verification_r01/tests.txt)：新15件＋旧308件、**323 passed / 0 failed / 0 skipped（15.68秒）**。前段のsource SHAを照合し、既存測距・packet・映像・操縦コードは不変。

両PC受領後の追加17件を含め [trial_verification_r01/audit.json](trial_verification_r01/audit.json) で **340 passed / 0 failed / 0 skipped（15.92秒）**。実iperf3/通信は未実施、試験手順と失敗時の保存をmock検証した。

実UDP結果受領後は新13件を加え [udp_idle5_verification_r01/audit.json](udp_idle5_verification_r01/audit.json) で **353 passed / 0 failed / 0 skipped（15.91秒）**。元archive/JSON/集計と旧source SHAを再照合した。こちらで追加の実通信は開始していない。

通常映像あり5 Mbpsの新入力についても既存検証器を無変更で使用し、[udp_video5_verification_r01/audit.json](udp_video5_verification_r01/audit.json) で **353 passed / 0 failed / 0 skipped（15.73秒）**。操作者目視申告は別の[観察記録](udp_video5_audit_r01/observation.json)として保存した。ただしこのrunは実際には映像なしだったため、[訂正記録](udp_video5_audit_r01/condition_correction.json)を追加した。

25 Mbpsの2runは、iperf 3.9が受信側per-stream `lost_percent`を0と出力する事象を含む。v1を変更せず[v2](audit_udp_v2.py)を追加し、[新テスト](../../../tests/test_network_udp_audit_v2.py)と合わせて [r02](udp_video25_verification_r02/audit.json) **359 passed / 0 failed / 0 skipped（16.13秒）**、[r01](udp_video25_verification_r01/audit.json) **359 passed（16.11秒）**。`end.sum`の整合性検査は緩めていない。詳細は[比較報告](udp_video25_report_r01.md)。50 Mbpsも同じv2で監査・検証し、[r01：359 passed（16.30秒）](udp_video50_verification_r01/audit.json)、[r02：359 passed（16.26秒）](udp_video50_verification_r02/audit.json)。結果は[1回目](udp_video50_report_r01.md)・[2回目](udp_video50_report_r02.md)。

**注意：** 11/18後段の[PNG transport probe](../png_link_probe_r01/README.md)で`src/webrtc_stream.py`と`src/webrtc_receive_ui.py`を既定offのまま変更した。このため`verify_udp.py`/`verify_udp_v2.py`のfrozen source検査は現在のtreeでは`previous frozen source differs`で停止する。保存済みのUDP監査・検証JSONは変更しておらず、再実行には11/18 pre-probeのcommitが必要。probe段階の検証は[png_link_probe_r01/verification_r01](../png_link_probe_r01/verification_r01/audit.json) **372 passed（16.48秒）**。

解析PCのread-only inspect試行では、sandboxがkernel netlink問い合わせを拒否し、iperf3も未導入だった。これをエラー情報として保存できたことのみ確認しており、IP/実回線計測の成功やGPUPC/matsunucの状態を示す結果ではない。その後の実機側inventory 2archiveは [監査結果](inventory_audit_r01/audit.json)へ保存し、さらにユーザー実施のUDP結果2archiveも [受領・監査](udp_idle5_report_r01.md)した。

オフライン再検証（成功済み同条件の反復は不要）：

```bash
python3 Experimental_results/2026-11-18/network_coexistence_r01/verify.py \
  --output-dir Experimental_results/2026-11-18/network_coexistence_r01/verification_r02
```
