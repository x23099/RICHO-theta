# 2026-11-17 日報の代表資料2点

- [packetサイズ比較](packet_size.png)：保存native画像1枚で5回行ったVP8一体packetとPNG payloadの中央値。約101.9kB対1,021.9kB。実通信帯域・ライブFPSではない。VP8にはmetadataを含み、PNG比較は画像payloadだけである。
- [codec時間比較](codec_time.png)：同じローカル5試行の中央値と観測min/max。VP8 packet encode、packet検査/decode/copy、PNG encodeを分離。matunuc/GPUPC性能やFFB総遅延ではない。

根拠：[全5試行CSV](codec_samples.csv)、[集約CSV](comparison.csv)、[manifest](manifest.json)、[生成script](build_assets.py)。入力はframe_motion_packet_r01/results_r01。日付はユーザー指定の11/17作業枠を継承し、実行UTCを改変しない。

新規撮影をしていないため新たなカメラ画像は作らない。codec試験で用いた11/16 pin5186の元PNGはrecordings/内に不変で残り、元画像の代表資料は11/16分にある。非可逆decode画像を日報の元画像として再保存しない。

再現は解析PCで未使用の出力先を指定する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-17/report_assets/build_assets.py --output-dir Experimental_results/2026-11-17/report_assets/reproduction_r01
```
