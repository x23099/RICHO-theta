# TTC conservative候補 実機確認診断

## 結論

`202609031545.tar.xz`の自動判定は**FAIL**だった。
ただし、conservative実装、録画品質、静止時の誤警告、後退時の誤TTCには異常がない。
`v0p20`とした3試行の実測速度が約0.083〜0.085 m/sで、0.20 m/s試験の許容下限0.16 m/sへ
達していないことがFAILの原因である。

静止1試行と後退1試行は採用できる。再録画が必要なのは0.20 m/s接近3試行だけである。

## 入力

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/202609031545.tar.xz` |
| サイズ | 255,103,600 bytes |
| SHA-256 | `f6acc155ca993fa7c1c3efa40ce25b2593fd0e2a4216de85917041748bec68dd` |
| session | 5/5完全 |
| config | `src/bird_eye_config_ttc_conservative_candidate_20260903.json` |
| profile | `src/dynamic_ttc_evaluation_profile_v4_candidate.json` |

## 試行別結果

| 試行 | 実効fps | 検出/追跡/ODOM | ODOM速度p90 | 最小TTC | WARNING | 判定 |
|---|---:|---:|---:|---:|---:|---|
| static center | 30.017 | 100%/100%/100% | 停止 | なし | 0 | PASS |
| approach v0p20 r01 | 29.995 | 100%/100%/100% | 0.0832 m/s | 7.578秒 | 0 | 条件不成立 |
| approach v0p20 r02 | 30.041 | 100%/100%/100% | 0.0853 m/s | 7.738秒 | 0 | 条件不成立 |
| approach v0p20 r03 | 30.012 | 100%/100%/100% | 0.0832 m/s | 7.668秒 | 0 | 条件不成立 |
| retreat v0p10 r01 | 29.975 | 100%/100%/100% | 0.0853 m/s | なし | 0 | PASS |

3接近試行では、metadataの`blue_ttc_velocity_source=conservative`と各frameの速度源が100%一致した。
速度MAEは最大でも0.000015 m/s程度、TTCとODOM基準値のMAEは0.005秒未満であり、
ODOM融合処理は意図どおり動作している。

## WARNINGが出なかった理由

WARNINGしきい値はTTC 4.6秒である。一方、今回の接近は最接近時でも概ね
`0.67 m / 0.083 m/s = 8.1秒`であり、警告域へ入らない。

同日14時台の有効な0.20 m/s録画ではODOM速度p90が3試行とも約0.1621 m/sだった。
今回の値はその約半分である。停止位置の1〜1.5 cm差では説明できず、停止位置誤差は原因ではない。

CSVの`cmd_linear_mps`は全frameで0であり、走行指令がbird_eye外部から与えられたため、
録画だけから外部指令値は確認できない。採否には実測ODOMを使用する。

## 再録画

次の3試行だけを新しい録画フォルダへ取得する。

1. `approach_center_v0p20_r01`
2. `approach_center_v0p20_r02`
3. `approach_center_v0p20_r03`

各試行は物理距離1.3 mから0.8 mまで、約20秒、前後に停止区間を入れる。
走行中のODOM速度p90が**0.16 m/s以上**になる操作を使う。
安全下限0.75 mを守り、停止位置1〜1.5 cmの誤差は許容する。

再録画用の固定要件は
`Experimental_results/2026-09-03/2026-09-03_ttc_conservative_v0p20_retry_requirements.csv`
とする。
