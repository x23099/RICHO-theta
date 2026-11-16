# 2026-11-16 日報の代表資料

1. [未加工の現在取付参照画像](decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png)：1280×720 dual-fisheye。session e52bb32f03d6488ebf37d769f46ec37a、frame5186。提出body_guard_full_20261116_r01.tar.xzの比較側pin画像で、全ログ正式監査SHAへ一致する。**実測3地点の画像ではない。** 元PNGをbyte単位で複写し、切抜き/注釈/リサイズ/色補正なし。
2. [実測申告と表示の3地点差](three_distance_difference.png)：[根拠CSV](three_distance_points.csv)はbody_display_range_check_r01/observations.csvの同一コピー。1/1.5/2mの画面表示との差+0.5/−2/−4cm。実測不確かさ不明、連続区間全体の誤差上限ではない。UIスクリーンショットの未提供ローカル原本を復元したものでもない。
3. [sender時計読出し区間の統計](clock_read_bracket.png)：[根拠CSV](clock_read_bracket.csv)はsender_ros_clock_live_audit_r01/results_r02/audit.jsonのbracket_width_us。1,177観測の最小47.061/中央値102.126/P95 165.5674/最大287.649μs。PC間時計精度・計測鮮度・FFB遅延ではない。時計同期を新たな前提にする意図もない。

入力/出力SHAと由来は[manifest](manifest.json)。生ログはGit管理しないrecordings/配下に保存し、ここへ埋め込まない。[生成script](build_assets.py)の既定出力はこのfolderだが、既存成果物への上書きを拒否する。再現時は新規outputを指定する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/report_assets/build_assets.py --output-dir Experimental_results/2026-11-16/report_assets/reproduction_r01
```
