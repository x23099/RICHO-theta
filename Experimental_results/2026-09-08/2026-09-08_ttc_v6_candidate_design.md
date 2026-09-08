# 2026-09-08 TTC v6候補設計

## 1. 目的

v5独立holdoutの失敗を、次の3種類へ分離できる評価と設定を作る。

1. 実際に危険TTCが継続したのに警告できない実装失敗
2. 減速によりTTCが安全側へ戻った正常解除
3. 警告を確認できる危険区間自体が成立しなかった試行条件不足

v5の固定profileと結果は変更せず、v6を別候補として追加する。

## 2. v6評価profile

対象: `src/dynamic_ttc_evaluation_profile_v6_candidate.json`

| 項目 | v5 | v6候補 | 理由 |
|---|---|---|---|
| schema | 4 | 5 | 新しい評価意味を旧結果から分離 |
| 検出率区間 | 録画全体 | 実走行区間 | 停止後の人の通過などを走行検出性能へ混入させない |
| 警告必須条件 | ラベル速度が0.15 m/s以上 | 加えて有効な生WARNINGが確認フレーム数以上継続 | 実測TTCに刺激がない試行を誤FAILにしない |
| 警告機会なし | FAIL相当 | INCONCLUSIVE | PASSとも実装失敗とも断定しない |
| 警告後PATH | 速度0.03 m/s超の全PATHをFAIL | 生リスクがWARNING/CRITICALのPATHだけFAIL | 減速による安全解除を許容 |
| 公称速度相対許容 | 20% | 25% | ペダル操作とODOM量子化を含む実機試験に合わせる |

新しいCSV指標は`motion_detection_rate`、`warning_intended`、`warning_opportunity`、
`unsafe_path_while_forward_after_warning_frames`、`inconclusive_reasons`である。

共通試行集計にも`motion_detection_rate`、`motion_measurement_acceptance_rate`、`motion_track_rate`を追加した。
v6用の固定要件`2026-09-08_ttc_v6_candidate_requirements.csv`で12試行を評価し、4規則すべてPASSした。
これにより、走行終了後の未検出を接近中の検出失敗として数えない。

## 3. 9月8日録画のv6再評価

出力: `ttc_v5_holdout/dynamic_ttc_results_v6_candidate.csv`

| 条件 | 結果 |
|---|---:|
| 0.10 m/s接近 | 3/3 PASS |
| 0.10 m/s後退 | 3/3 PASS |
| 0.20 m/s接近 r01 | PASS |
| 0.20 m/s接近 r02/r03 | 2 INCONCLUSIVE |
| 合計 | 7 PASS、0 FAIL、2 INCONCLUSIVE |

r01はWARNING後も5フレームだけ0.03 m/sを超えていたが、その時点の生判定はPATHでTTCも安全側だったためPASSとなった。
r02/r03には3フレーム連続の有効なWARNING機会がなく、警告性能を確認できないためINCONCLUSIVEとした。
`ttc_v5_holdout/virtual_ffb_replay_v6_candidate.csv`も生成し、schema 5でも速度源が
`conservative`のまま再生されることを確認した。

## 4. 観測面積ゲート候補

対象: `src/bird_eye_config_ttc_v6_candidate_20260908.json`

9月1日、3日、8日の計34試行と、8月26日の遮蔽2イベントを用いて正規化面積下限を比較した。
結果は`2026-09-08_observation_gate_threshold_sweep.csv`へ保存した。

| 下限 | 通常観測の最悪採用率 | 遮蔽外れ値拒否 | 追跡失効/再捕捉 | 判定 |
|---:|---:|---:|---:|---|
| 1400 | 99.14% | 100% | 2/2 | PASS |
| 1450 | 98.46% | 100% | 2/2 | PASS |
| 1500 | 97.09% | 100% | 2/2 | FAIL |
| 2000（現行v5） | 45.45% | 100% | 2/2 | FAIL |

通常観測98%以上を満たす最大値1450をv6候補とした。1200～1450では遮蔽外れ値拒否率はすべて100%だったが、
必要以上に閾値を下げず、検証済み範囲で最も強い除外を維持する。

## 5. 実装修正

- 警告履歴のないUNKNOWNから解除ヒステリシスだけでWARNINGへ昇格しないよう修正
- 安全PATHと危険PATHを分ける再生指標を追加
- dynamic TTC profile schema 5とINCONCLUSIVE判定を追加
- 共通試行要件へ走行区間限定の検出・観測採用・追跡指標を追加
- 遮蔽比較へ青箱なし試行が含まれても位置基準計算で停止しないよう除外処理を追加
- 上記に対する回帰テストを追加

## 6. 採否と次回検証

v6は**候補**であり、実機確認済み設定ではない。9月8日録画を原因診断と候補設計に使用したため、
同じ録画での成績を独立holdout結果として再利用してはならない。

次回はv6 configとprofileを事前固定し、新しい0.20 m/s接近を最低3試行取得する。
各試行では停止位置を厳密に合わせる必要はないが、TTC表示が4.6秒未満へ入ってから約0.2秒は急にペダルを戻さず、
警告確認3フレーム分の刺激を確保する。停止操作と安全距離を優先し、危険な接近を継続してはならない。

実装後の単体・回帰テストは152件すべてPASSした。v6 configとschema 5 profileのpreflight整合もPASSした。
