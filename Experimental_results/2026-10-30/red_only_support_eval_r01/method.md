# 赤のみshadow候補の保存データ評価（実行前固定条件）

## 目的

r02実機ログ（2026-10-30 18:53）の`colour_support_shadow`候補を、HANDOFF 7.2の評価対象として保存データだけで監査する。unionマスクが床と連結して基準支持点を棄却した場面で、赤のみ候補がどのような画像点・下包絡を持つかを確認する。

**この評価は制御支持点への昇格判定ではない。** 候補の安定性・bboxとの関係・失敗カテゴリを整理し、次に比較評価へ進めるかの材料にする。

## 入力（すべて保存済み）

| 入力 | 用途 |
| --- | --- |
| `recordings/2026-10-30/live_frame_evidence_r02_20261030_185348/distance_frames.jsonl` | 1,689フレームの基準支持点・赤のみshadow・補完shadow・bbox・姿勢理由 |
| 同 `live_summary.json` | 実行条件、GPU、checkpoint、終了状態 |
| `Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/` | r02の接触辺・床マスク分析（参照のみ） |

新しいYOLO推論、画像デコード、HSV再抽出、校正・姿勢fitは行わない。SキーPNGの再解析は別成果物（`analysis_r02/inspect_saved_mask.py`）で実施済み。

## 評価量

1. **候補の有無と理由**: `unverified_visible_colour_support`、`colour_contour_reaches_roi_edge`、`ambiguous_upper_body_colour`の件数。
2. **bboxとの関係**: 点がbboxのx範囲内か、bbox下端から何px上か、bbox中心からのx offset。
3. **下包絡**: support列数、x span、点がsupportに含まれるか（既存検証と同じ）。
4. **時間安定性**: 隣接フレームの点のx/y移動量（px）。frame番号が連続する場合のみ。
5. **補完shadowとの一致**: 同時刻のcompletion候補点と同一か、距離何pxか。
6. **物理基準**: このsessionには同一フレームの床マーカーが無い。したがって絶対距離・接地は評価しない。

## 判定の扱い

- 点がbbox内・support上・時間的に安定していても、**床接点の証明にはならない**。
- 赤のみ候補が利用可能でも、unionマスクの棄却を遡って無効化しない。
- 距離・姿勢・FFBのflagsはすべてfalseのまま。
- 近似1.5 mや名目距離に近い点を選ばない。

## 出力

- `candidate_frames.csv`: フレーム単位の候補点・bbox・support・移動量
- `summary.json`: 件数、分位値、カテゴリ、flags
- `provenance.json`: 入力・スクリプトのSHA-256
