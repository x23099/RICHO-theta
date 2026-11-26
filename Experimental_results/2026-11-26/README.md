# 2026-11-26 G923 A/Bベンチ・連続cadence・autocenter

2026-11-24のM/B実機の続き。今日はA（勾配方向）、B（側ベース）のベンチ、continuous cadence、autocenter 15を確認した。
中心的な結果は、**autocenterでベースラインは軽くなったが、0.15の方向定常トルクはまだ感じられない**こと。次は0.20→0.25→0.30の段階試験。

## 資料

- [代表資料](report_assets/README.md)
  - [A r01](report_assets/A_r01_summary.json)
  - [bench 0.15（triple cadence）](report_assets/bench_r03_summary.json)
  - [B continuous 0.15（経路）](report_assets/B_continuous_path_r01_summary.json)
  - [B continuous 0.15（autocenter 15）](report_assets/B_continuous_autocenter_r01_summary.json)
- [評定CSV（11/26）](record_2026-11-26.csv)
- [2026-11-24のM/B実機・手順](../2026-11-24/README.md)
- [RUNBOOK](../2026-11-24/ffb_policy_comparison_r01/RUNBOOK.md)
- [評定CSV（11/24）](../2026-11-24/ffb_policy_comparison_r01/record_2026-11-24.csv)

## 結果（要約）

| 条件 | 結果 |
|---|---|
| A r01 | 箱左でdirection +1（Aの勾配反転）。0.4の定常36 frameは方向として感じず。0.25/direction 0の振動を1回。 |
| ベンチ0.075/0.10/0.15（triple） | pattern steadyだがactive 3〜4 frame ON/OFF（`cadence_gap:triple`）。0.10/0.15で「ドッドッド」。 |
| B continuous 0.1/0.15 | 箱が真横/経路外でrisk/hold/UNKNOWNが切れ、「ドドド」。青い経路に箱を入れる必要。 |
| B continuous 0.15（19:13） | 最初のCRITICALは箱が経路内（1.21 m、direction -1、steady）。最後は真横/経路外でUNKNOWN pulse。CRITICALで停止。 |
| B continuous 0.15 + autocenter 15（20:27） | ベースライン軽量化。箱左、direction -1が61 frame、active 72、corridor 63/72。0.15の方向定常は左でも感じず。右が軽いのは逆側で正しい。 |

## 判断

- force pathは正常。autocenter 15でベースラインは軽くなった。
- 0.15の方向定常トルクはまだ知覚閾値以下。0.20/0.25/0.30を短いパルス、車輪浮かせ、e-stop、安全確認者で段階試験する。
- 0.5は最後の手段。0.30でも感じない場合だけ、明示承認＋50〜120ms＋車輪浮かせ＋e-stop＋安全確認者。
- 0.15で感じない原因として、`FF_GAIN`、spring（`ffb_follow` idle 13500）、autocenterの組み合わせも確認する。
- フィールドの`max_magnitude=0.05`は変えない。0.20/0.30/0.5はベンチ専用。
- Aは箱左で+1、Bは箱左で-1。Aの勾配反転とBの側の違いがログで確認できた。

## 次

1. `BENCH_HARDWARE_MAX_MAGNITUDE`を0.20にした状態で、0.20のBを1回。
2. 感じなければ0.25、0.30。短いパルス、CRITICALで停止。
3. 0.30でも感じない場合は、`ffset`のgain、spring 13500、autocenterの組み合わせを確認。0.5は最後。
4. 箱左で左が重い、箱右で右が重い。逆なら`constant_direction_sign=-1.0`。
5. 評定を`record`へ。A/Bの方向方針のログ比較をまとめる。

## 元archive（Git管理外）

`~/Downloads/`の`ffb_A_r01_20261126_153717_062`、`bench_r01/r02/r03_20261126_*`、`ffb_B_continuous_*`、`ffb_B_continuous_0.15_test_20261126_{191349,202728}`。各archiveは`detections.csv`と動画を含む。
