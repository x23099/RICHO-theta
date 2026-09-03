# TTC速度源候補の設計判断

## 結論

映像から推定した相対速度だけを使う現行方式はproduction既定値として維持し、
実験候補として`conservative`方式を追加した。

`conservative`は次のうち、より接近側（負方向）の速度をTTC計算に使う。

1. 青箱追跡から得た平滑化相対速度
2. 静止障害物を仮定した`-odom_linear_mps`

ODOMが取得できない場合は映像速度へフォールバックする。選択結果は
`visual_smoothed_vz_mps`、`smoothed_vz_mps`、`ttc_velocity_source`として録画CSVへ残す。

## 根拠

- 2026-09-03独立holdoutは12/12 sessionが完全で、検出・追跡・ODOM有効率は全試行100%。
- 映像距離変化はODOM積算移動量に対し中央値0.845倍で、R²は0.9966以上だった。
- 距離と速度を同率補正してもTTCの比`z / -vz`はほぼ不変なので、距離scale補正だけでは警告欠落を直せない。
- v4 profileによる9月3日の動的9試行再生では、`visual`が6/9 PASS、`conservative`が9/9 PASS。
- 0.20 m/s接近は`visual`でWARNING 0/3、`conservative`で3/3。
- 8月18日・9月1日・9月3日の計28動的試行では、`visual`が16/28、`conservative`が21/28 PASS。
  残る7件は旧録画の警告進入遅延、追跡率、後退開始応答に分類され、9月3日の速度過小評価とは別である。

詳細は次を参照する。

- `2026-09-03_longitudinal_scale_diagnosis.md`
- `2026-09-03_ttc_v4_candidate_replay.md`
- `2026-09-03_ttc_v4_historical_replay.md`

## 評価条件の修正

通常接近試験では`minimum_warning_hold_frames=0`とする。
`WARNING_HOLD`は、警告成立後に走行中の観測が無効になったときの有限保持状態である。
遮蔽のない正常な接近でHOLDを必須にすると、観測が正常に続くほど不合格になるためである。

HOLD性能は「警告成立後に意図的な遮蔽または欠測を発生させる試験」として分離する。

## 実装と設定

- production設定: `blue_ttc_velocity_source: visual`
- 実験候補設定: `src/bird_eye_config_ttc_conservative_candidate_20260903.json`
- 実験候補profile: `src/dynamic_ttc_evaluation_profile_v4_candidate.json`
- 候補profileはconfigとの9項目一致をpreflightで検証する。
- 解析時はmetadataの設定値と各frameの`ttc_velocity_source`が95%以上一致することも必須とする。

## 次の最小実機確認

同じ12試行の再取得は不要。候補実装が実機経路でも再生結果と一致するか、次の5試行で確認する。

| 順番 | ラベル | 条件 | 時間 | 主な確認 |
|---:|---|---|---:|---|
| 1 | `static_center_ttc_r01` | 青箱中央1.0 m、静止 | 10秒 | 誤TTC・誤警告なし |
| 2 | `approach_center_v0p20_r01` | 1.3→0.8 m、約0.20 m/s | 約20秒 | WARNINGと速度源 |
| 3 | `approach_center_v0p20_r02` | 同上 | 約20秒 | 再現性 |
| 4 | `approach_center_v0p20_r03` | 同上 | 約20秒 | 再現性 |
| 5 | `retreat_center_v0p10_r01` | 0.8→1.3 m、約0.10 m/s | 約20秒 | TTC・警告なし |

0.20 m/s接近の停止位置は安全下限0.75 mを守り、1〜1.5 cmの停止誤差を許容する。
評価対象は停止位置の一致ではなく、接近中の速度源、TTC、WARNING成立である。

起動は次のワンコマンドを使う。GitをcleanにしてKobukiと`/odom`を起動してから実行する。

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_conservative_candidate_20260903.json \
  --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile_v4_candidate.json \
  --record-dir recordings/2026-09-03_ttc_conservative \
  --experiment-label static_center_ttc_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /odom
```

画面の速度表示に`src=conservative_odom`または`src=conservative_visual`が表示され、
CSVの`ttc_velocity_source`にも同じ値が記録されることを確認する。

録画を`tar.xz`へまとめた後は、5試行専用の固定要件で解析する。

```bash
python3 src/analyze_field_recording.py \
  --input /path/to/recording.tar.xz \
  --config src/bird_eye_config_ttc_conservative_candidate_20260903.json \
  --requirements Experimental_results/2026-09-03/2026-09-03_ttc_conservative_live_requirements.csv \
  --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile_v4_candidate.json \
  --output-dir Experimental_results/2026-09-03/ttc_conservative_live
```

## 採用前に残るリスク

対象物が自車と同方向へ遠ざかっている場合でも、静止物体仮定のODOM速度が選ばれて過警告になる可能性がある。
青箱を静止障害物として扱う現在の段階では安全側だが、YOLOで人や移動物体を扱う前に、
対象物運動を分離する方式またはクラス別の速度源方針が必要である。
