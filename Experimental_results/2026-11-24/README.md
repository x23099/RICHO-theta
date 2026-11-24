# 2026-11-24 G923 M/B実機実験

G923の実機で、M（大きさのみ）とB（側ベース）を実施した。A（勾配方向）は未実施で、2026-11-25に再開する。
今日の中心的な発見は、**force pathは通ったが、Phase 4の`max_magnitude=0.05`では方向性のある定常トルクが知覚閾値以下**だったこと。

## 資料

- [実行手順・RUNBOOK](ffb_policy_comparison_r01/RUNBOOK.md)
- [実験手順・背景](ffb_policy_comparison_r01/README.md)
- [条件別config生成](ffb_policy_comparison_r01/make_condition_configs.py) / [preflight](ffb_policy_comparison_r01/preflight.py)
- [評定CSV](ffb_policy_comparison_r01/record_2026-11-24.csv)
- [代表資料](report_assets/README.md)
  - [M r012要約](report_assets/M_r012_summary.json)
  - [B r03要約](report_assets/B_r03_summary.json)
  - [force path確認](report_assets/ffb_chain_active_check.txt)

## 結果（要約）

| 条件 | run | 結果 |
|---|---|---|
| M | r010/r011/r012 | WARNING/CRITICALが十分。requested 0.25/0.4、direction 0。0.05の振動は体感3。 |
| B | r02/r03 | 箱左でdirection -1、requested 0.4。applied 0.05/pattern 1まで確認。方向の重さは感じず。 |
| B | r01 | 箱中央でdirection 0。Bとして無効。 |

- `ffb_status`：`output_active=true`、`requested=0.4`、`applied=0.05`、`pattern=1`、`direction=±1`、`fault=false`。
- Mの振動（pattern 3）は感じるが、方向の定常トルク（pattern 1）は感じない。
- Mの振動は「重さ」ではなくアラート。M/A/Bの重さ比較には、Mも同じ定常トルクにする設計変更が必要。

## 判断

- 0.05上限では方向性のある重さの体感比較は成立しない。上限は上げない。
- 新たに必要なのは、定常トルクを上げる安全段階（承認）か、振動に左右バイアスを付ける別パターン（目標とは別物）か、ログのみの方向比較。
- Aを1回確認して、方向不感知を確定する。

## 元archive（Git管理外）

`~/Downloads/`の`ffb_M_r010`〜`r012`、`ffb_B_r01`〜`r03`の`.tar.xz`。各345 MB程度で、`raw.avi`/`detection.avi`/`bev.avi`を含む。数値根拠は各`detections.csv`。
