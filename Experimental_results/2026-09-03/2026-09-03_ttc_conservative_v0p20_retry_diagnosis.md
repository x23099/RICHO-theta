# TTC conservative 0.20 m/s再試験診断

## 結論

`202609031610.tar.xz`の固定v4 profileによる自動判定は**FAIL（2/3 PASS）**だった。
ただし、TTC・WARNING・速度源融合に関する機能条件は3/3試行すべて成立した。

r01のODOM速度p90が許容下限0.160000 m/sに対して0.159923 m/sとなり、
0.000077 m/sだけ下回ったことが唯一のFAIL理由である。
これは公称0.20 m/sに対して0.039%の差であり、機能失敗として再録画する必要はない。

v4 profileは記録後に変更せず、正式結果をFAILのまま保存する。
工学的にはconservative候補の実機動作を3/3で確認できたと判断する。

## 入力

| 項目 | 値 |
|---|---|
| アーカイブ | `/home/robo25/Downloads/recoding/202609031610.tar.xz` |
| サイズ | 110,733,032 bytes |
| SHA-256 | `8d1b8e0bc59f4a07f47ccab715ac3c38aea573acd1a59b707664ce40c54310cf` |
| session | 3/3完全 |
| config | `src/bird_eye_config_ttc_conservative_candidate_20260903.json` |
| profile | `src/dynamic_ttc_evaluation_profile_v4_candidate.json` |

## 結果

| 試行 | fps | ODOM p90 | 速度源一致 | 速度MAE | 初回警告TTC | WARNING/HOLD | 固定判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| r01 | 30.007 | 0.159923 m/s | 100% | 0.0000003 m/s | 4.548秒 | 26/5 frame | FAIL |
| r02 | 30.008 | 0.164187 m/s | 100% | 0.0000002 m/s | 4.588秒 | 22/6 frame | PASS |
| r03 | 30.023 | 0.164187 m/s | 100% | 0.0000002 m/s | 4.439秒 | 26/7 frame | PASS |

3試行すべてで次を満たした。

- 検出率、motion中の追跡率、ODOM有効率が100%。
- `blue_ttc_velocity_source=conservative`とframe記録の速度源が100%一致。
- 接近中のTTC有効率が100%。
- TTC 4.6秒以下でWARNINGが成立。
- CRITICALは0 frame、警告後の前進PATH状態は0 frame、最終状態はCLEAR。
- 1〜1.5 cmの停止位置差に起因する不合格はない。

## r01の境界判定

profileの公称速度許容差は`max(0.025 m/s, 20%)`である。
公称0.20 m/sでは許容差0.04 m/s、下限は0.16 m/sとなる。

```text
r01 speed error = |0.200000 - 0.159923| = 0.040077 m/s
fixed limit     = 0.040000 m/s
excess          = 0.000077 m/s
```

同日の先行0.20 m/s録画ではODOM p90が0.162055 m/sで、今回のr02/r03は0.164187 m/sだった。
KobukiのODOM速度値は離散的で、境界0.160000 m/sの直近値を跨いで判定が変わる。

この記録を見てv4の許容値を変更するとholdout条件の事後変更になるため行わない。
今後は別versionのprofileで、ODOM分解能または試行群中央値を事前に定義してから評価する。

## v5診断候補

同日14時台と16時台の0.20 m/s録画から、ODOM速度の主要な刻みを
0.002132〜0.002133 m/sと確認した。v5候補ではprofileへ
`odom_speed_resolution_mps=0.002132`を明記し、速度許容差へ半刻みの
0.001066 m/sだけを加える。

v5で同じ録画を診断再生した結果は**3/3 PASS**となった。TTCや警告条件はv4から変更していない。
この再生は境界処理の妥当性確認であり、独立holdoutではない。v5を正式採用する場合は、
次回の未使用録画に対して事前固定した状態で評価する。

## 総合判断

前回の静止・後退試験と今回の接近試験を合わせると、conservative候補は次を確認できた。

- 静止時の誤TTC・誤警告なし。
- 後退時の誤TTC・誤警告なし。
- 0.20 m/s接近で3/3 WARNING成立。
- ODOM融合値と期待相対速度が一致。

したがって、速度源融合の実装確認を目的とした追加録画は不要である。
