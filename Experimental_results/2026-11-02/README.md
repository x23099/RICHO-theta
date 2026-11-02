# 2026-11-02 成果物索引・Git保存方針

今日は学校で撮影できないため、解析PCで既存データを使用した。実機/GPU/ROS/FFBは起動していない。

| 作業 | 正式な結果 | 検証 |
| --- | --- | --- |
| 同録画の過去姿勢による固定床比較 | [連続再生](fixed_floor_contiguous_replay_r01/README.md)、`results_r02/` | `verification_r01/`、当時283テストPASS |
| 同接続内の明示L読込み | [ローカル読込み](fixed_floor_live_load_r01/README.md) | `verification_r04/`、当時309テストPASS |
| 床画像→候補モデル→読込み用ファイル | [モデル導出](fixed_floor_derivation_r01/README.md)、`results_r02/` | `verification_r03/`、当時360テストPASS |
| 読込み前後の観測再生 | [実負例と合成入力](fixed_floor_lifecycle_replay_r01/README.md)、`results_r04/` | `verification_r02/`、新規16PASS。正の実モデル連続評価は未完了 |
| 比較専用GUI | [表示仕様](fixed_floor_display_r01/README.md) | `verification_r02/`、最終393テストPASS |

日報：[2026-11-02](../../Daily_reports/2026-11-02_daily_report.md)。代表資料：[report_assets](report_assets/README.md)。

## Gitへ含めるもの

コード、テスト、手順・README、正式な小さい集計CSV/JSON、モデル候補JSON、検証manifest/テスト記録、グラフ、明示した合成GUI例、変更前source snapshotを含める。原画像は既存の場所を維持し、代表資料の複製はバイト同一。

## ローカルに残すもの

以下は`.gitignore`で除外した。**削除していない。**

- `fixed_floor_contiguous_replay_r01/results_*/**/distance_frames.jsonl`。
- `fixed_floor_lifecycle_replay_r01/results_*/**/distance_frames.jsonl`（実観測の派生行・合成行とも再生成可能）。
- 各READMEが途中版と記載している探索/失敗/中断のrevision。正式版の一覧は上表。
- 生録画、実機元JSONL、checkpoint、dataset、venvは従来どおりGit外。

検証器が入力JSONLを必要とする場合、別PCへGitをpullしただけでは揃わない。元の録画/観測・保存予測も用意し、対応する`run.py`で未使用フォルダへ再生成してから検証する。手順は各READMEを参照する。GUI検証は観測再生のJSONLも参照するため、こちらが先に必要。

公開しているhashは元の取得/検証時点の証拠。GUI追加など意図した変更は後続manifestと変更前snapshotで照合し、古いmanifestのhashを新しい値で書き換えていない。過去の検証器を現在の変更済みコードで再実行すると保護対象の不一致を検出することがあるため、最新のGUI検証と監査記録を優先する。

別作業中の`Experimental_results/2026-10-30/red_only_support_eval_r01/`と`tests/test_red_only_support_eval.py`は、ユーザーの指定どおり今回のcommit/push対象外。保持したままとする。
