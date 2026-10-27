# 最新：固定格子での順序測距再計算r05（2026-10-26）

実行時サンプリングの移植差を修正した最終の再計算。
学校での操作、追加録画、モデル再学習は不要な範囲で進めた。
根拠とコード変更は[scene cadence監査](../scene_cadence_audit_r01/README.md)を参照。

## 結果

同じ3録画、全2,530 frameを順に処理した。中央範囲は明示的な `x=270..350, y=0..720`。
範囲外を監視する本番モードではなく、静止コーン測距の診断範囲である。

| 録画 | 全frame | 条件付き距離出力 | 有効scene画像 |
|---|---:|---:|---:|
| 同一姿勢・床→コーン系列 | 1,547 | **326** | 17 / 52 |
| 別の中央1.3 m | 651 | **0** | 2 / 22 |
| 中央コーンなし | 332 | **0** | 3 / 12 |

別の中央1.3 mは姿勢の初期化に必要な2枚学習＋2枚検証へ届かない。
中央コーンなしは対象候補なし。初期化不足や対象なしを0 mや過去値で補わない。

既存の区間ラベルを**完了後にのみ**付与した数値：

| 区間 | 出力 / 全frame | 出力中央値 | 基準との差の中央値 |
|---|---:|---:|---:|
| 中央1.3 m | 104 / 218 | **1.3259 m** | +0.0259 m |
| 中央2.0 m | 172 / 548 | **1.9743 m** | −0.0257 m |

ほかに配置移行中25件、移動移行中25件の条件付き出力があるが、これらには正解距離を補わない。
全326件を静止設置距離の検証成功数とはしない。
旧r03の279件との差は、標本選択に加えて測定したCPU所要時間の差も含む機能再計算の結果。
実カメラの改善率やGPU推論を含む実効FPSとして扱わない。

## 最新資料

- [距離と見送り理由の時系列](distance_and_withholding_timeline.png)
- [1.3 m：距離表示付き](visualizations/cone_130_recomputed_f000604.png)
- [2.0 m：距離表示付き](visualizations/cone_200_recomputed_f001142.png)
- 無加工原画像：[1.3 m](originals/cone_130_raw_f000604.png)／[2.0 m](originals/cone_200_raw_f001142.png)
- [全区間の集計CSV](phase_summary.csv)／[入力・出力・画像来歴](summary.json)

元の全画角1280×720は変更していない。注釈入りは別ファイルで、録画後の再計算と明記。
各区間で最初に出力できたframeを採用し、最小誤差の画像を選んでいない。

## 再計算の再現

元録画と保存済み検出結果があるPCで、GPUなしで実行できる。
現在こちらで完了済みのため、利用者が今実行する必要はない。
出力先は必ず新規の名前にし、旧結果を削除しない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
export THETA_DISTANCE_PYTHON=/home/robo25/theta-env/bin/python3
OPENBLAS_NUM_THREADS=1 ./start_cone_distance.sh replay \
  --session recordings/2026-10-15_floor_cone_same_pose_intake_r01/floor_cone_same_pose_r01_20261015_160621_378 \
  --saved-run Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/inference_r01 \
  --target-roi 270 0 350 720 \
  --output-dir Experimental_results/2026-10-26/cone_distance_replay_next_r01
```

最新の図の生成元：

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 src/summarize_cone_distance_replay.py \
  --replay-root Experimental_results/2026-10-26/cone_distance_replay_r05 \
  --scope-json Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/scope.json \
  --output-dir Experimental_results/2026-10-26/cone_distance_report_next_r01
```

## 適用範囲・検証

新規clock15＋engine30＋RTC26＋支持範囲24の計95テストがPASS。
固定格子の選択が元9録画・492標本と完全一致すること、busy中の仕事を増やさないこと、
時間飛び・接続reset・source時刻による期限・未来情報からの非干渉を確認した。
最終r05が消費したソース・入力の変更は0件。

保存済みYOLO枠を再利用しており、新規CUDA推論・カメラ/通信・走行・FFBは未実施。
校正K/Dや床変換、6平面、角度/SVD、初期化のしきい値は変更していない。
紙基準frameは測量済みbase_linkではなく、色下端は真の床接地点と未照合。
`physical_metric_verified` / `floor_contact_verified` / `usable_for_ffb` はfalseのまま。

次の実機確認ができるまでは、既存データでの診断とソフトウェア検証を続けられる。
ただし、根拠不足の姿勢を採用するためのROI/角度/必要本数の繰り返し調整は行わない。
Git commit / pushは依頼されていないため実施していない。
