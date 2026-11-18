# 2026-11-18 代表資料

日報 [2026-11-18_daily_report.md](../../../Daily_reports/2026-11-18_daily_report.md) の図表。すべて保存済み監査JSONから再生成できる。

## 1. network_coexistence_rates.csv / .png

- 内容：UDP単一stream 10秒の6試行について、送信rate・受信区間rate・欠損数・欠損率・payload一致。
- 出典：`Experimental_results/2026-11-18/network_coexistence_r01/udp_{idle5,video5,video25,video50}_audit_*/audit.json`。
- 灰色barは「申告はnormal-videoだが、実際は映像パイプライン未起動」だった試行（[5 Mbps訂正](../../2026-11-18/network_coexistence_r01/udp_video5_audit_r01/condition_correction.json)、[25 Mbps r01訂正](../../2026-11-18/network_coexistence_r01/udp_video25_audit_r01/condition_correction.json)）。
- 図の数値は各監査JSONの`receiver_from_intervals`から再計算。**欠損率は欠損packets / 受信packets**であり、映像品質の指標ではない。

## 2. png_transport_probe_r01.csv / .png

- 内容：実SCTP/DTLS経路でのPNG frame到達（handed off / completed / published）と、実際に流れたpayload上限。
- 出典：`Experimental_results/2026-11-18/png_link_probe_r01/transport_audit_r01/audit.json`。
- 右図の「measured upper bound」は `fragments × message_cap ÷ 経過秒` の**上限**。実wire bytesは採取していないため、実際はこれ以下。
- 「40.49 Mbps」は前段の保存画像PNG（fragment込み約1,012,229 B）を5 Hzで送る場合の必要量で、**今回の実測値ではない**。

## 再生成

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/report_assets/make_assets.py
```

matplotlib 3.10.6で生成。カメラ画像は使用していない（当日のカメラ撮影なし）。
