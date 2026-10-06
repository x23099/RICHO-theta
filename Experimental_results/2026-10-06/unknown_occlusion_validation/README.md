# 過去UNKNOWN録画の目視遮蔽分類と固定候補比較

2026-10-06実施。追加録画・ROS送信・実機駆動なし。本番検出器、距離校正、FFB強度、安全ゲートは変更していない。

## 結論

9/29 v11録画の選定した2区間を全107 frame目視し、完全遮蔽と確認できる4 frameを見つけた。同じ動画の全2,412 frameを固定済み3方式で再計算したところ、完全遮蔽4 frameではすべて**検出0、測定採用0**だった。ただし1イベント・最初と最後のタイムスタンプ差が0.099875秒の短い例であり、完全遮蔽一般の安全性や長い遮蔽でのUNKNOWN発報・再捕捉遅延の合格証明にはならない。

4 frameで追跡位置が存在するのは新規検出ではなく、直前の位置からの**予測**だった。検出、測定採否、追跡予測、衝突状態を区別して集計した。

今回の結果は`OBSERVED_NOT_CERTIFIED`とし、実機候補の採用は引き続き保留する。[08/26の全182 frameレビュー](../occlusion_label_review/README.md)もそのまま保存した。

## 対象と先に固定した分類

session: `phase5_v11_reliability_dryrun_r01_20260929_153520_912`

原本: `/home/robo25/Downloads/rokuga_phase5_v11_reliability_dryrun_r01_20260929_153520_912.tar.xz`。
原本archive SHA-256: `240ac6566fb4fdd1172ce7ab8c2f020129cc2d50c869b1f48b04e970004ec668`。

対象箱は左側レンズの正面の箱。周辺の別の青い物体と区別して確認した。無加工1280×720の各frameを目視し、箱を遮る板との重なりに基づいて分類した。

1. 過去UNKNOWN試験の代表画像を確認した。[representative_screening.csv](representative_screening.csv)の6画像では、v11 frame 963以外は箱の縁などが残っていた。
2. v11のframe 950～985と1100～1170を選び、2区間の全frameを確認した。frame番号は1始まり、動画indexはframe−1。
3. 検出結果を見る前に[manual_review.csv](manual_review.csv)を保存し、SHA-256を[review_protocol.json](review_protocol.json)に固定した。検出できたかどうかで目視ラベルは変更していない。
4. 微小な縁を箱と断定できないframeは`uncertain`に分け、完全遮蔽の分母へ入れなかった。

| 目視分類 | frame数 | 意味 |
|---|---:|---|
| visible | 15 | 板による遮蔽が確認されない |
| partial_occlusion | 53 | 箱の面・上縁・下縁・側縁が残る |
| fully_occluded | 4 | 箱の面・縁が確認できない。963～966 |
| uncertain | 35 | 手や板の境界の細い部分を断定できない |

これは目視で選んだ区間の記述的評価であり、無作為抽出・独立holdoutではない。録画全体や他のarchiveに長い完全遮蔽が存在しないという結論でもない。v12の代表画像レビューを動画全区間のレビューと読み替えない。

## 比較条件と結果

候補条件・候補コードは[先行候補のprovenance](../box_contact_candidates/provenance.json)から変更していない。`--freeze-from`により一致を確認した。検出器条件は`src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`から取得し、幾何・追跡器・ODOM・測定ゲートには元sessionの条件を使用する。動画は冒頭から順に処理し、選定区間だけで追跡器をリセットしていない。

全2,412 frame × 3方式 = 7,236比較行。目視ラベルを結合したのは107 frame × 3方式 = 321行。

| 方式 | visible 検出／採用 | 部分遮蔽 検出／採用 | 完全遮蔽 検出／採用 | 判定不能 検出／採用 |
|---|---:|---:|---:|---:|
| baseline | 15 / 15 | 19 / 8 | 0 / 0 | 4 / 0 |
| seeded_s130_nearest | 15 / 15 | 12 / 9 | 0 / 0 | 0 / 0 |
| seeded_s130_bottom | 15 / 15 | 12 / 9 | 0 / 0 | 0 / 0 |

表の2数値はそれぞれframe数。各列の分母は上表の15、53、4、35。検出率だけで優劣を決めず、部分的に見える箱が面積・位置・追跡整合ゲートで不採用となることを区別する。採用された測定にも物理距離の正解は付いていない。

完全遮蔽では3方式とも`track_available=4`、`track_predicted=4`。予測で追跡が残ったことを「箱を誤検出した」とは数えない。また短い遮蔽からの予測維持を異常とは判定しない。

保存動画の圧縮後pixelとライブ処理pixelは同一とは限らない。今回再計算された仮想衝突状態や通知は、過去のROS通信・物理振動の再現を保証しない。元v11の通信診断やv12実機試験の判定を上書きしていない。YOLO経路の試験でもない。

## 保存物・検証

- `manual_review.csv`、`review_protocol.json`: 比較前に固定した107件の目視分類、対象範囲、判定不能の扱い。
- `video_comparison/frame_results.csv`: 全7,236行。検出・追跡・仮想衝突状態を含む。
- `reviewed_frames.csv`: 321行の目視結合。元動画SHA、frame index、decoded BGR画素SHAを記録。
- `phase_metrics.csv`、`review_summary.json`: 分類別集計、約0.10秒という制約、全入力・出力SHA。
- `raw_assets_manifest.csv`: 963（完全遮蔽）と1120（判定不能）の無加工PNGの対応・時刻・hash。
- `visual_review_coverage.png`: 107 frameの分類数。検出できたかを示す図ではない。
- `create_review_artifacts.py`: 集計・図・2枚の全画角PNGの再生成。目視分類を自動生成するものではない。

再生成時にラベル固定SHA、候補コード・候補条件、source動画／CSV／metadata SHA、全frameの3方式対応、source時刻一致、測定採用時の検出ありを検証した。目視に用いた**107枚すべて**を元動画の順次decode結果と全画素照合した。保存したPNGも1280×720で全画素一致。切り抜き・注釈・補正・リサイズは行っていない。

本番ソースは変更せず、直前に成功した全316 unittestの検証を再利用。今回の追加は目視CSV、オフライン再生成スクリプトと成果物であり、上記データ整合チェックを別途実施した。Matplotlibの未使用Axes3D警告は出るが、2Dグラフの保存は成功した。

## 再現方法

原本を安全に展開したsessionのパスを指定する。`--reviewed-png-dir`には、目視に使用した各frameの全画角PNG（`v11_raw_frame_0950.png`等）を置く。これは目視証拠の照合用で、未確認画像へ自動的にラベルを付けるものではない。

```bash
python3 src/compare_offline_box_contacts.py \
  --input /path/to/phase5_v11_reliability_dryrun_r01_20260929_153520_912 \
  --detector-config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --output-dir Experimental_results/2026-10-06/unknown_occlusion_validation/video_comparison \
  --variants baseline seeded_s130_nearest seeded_s130_bottom \
  --freeze-from Experimental_results/2026-10-06/box_contact_candidates/provenance.json

python3 Experimental_results/2026-10-06/unknown_occlusion_validation/create_review_artifacts.py \
  --session-dir /path/to/phase5_v11_reliability_dryrun_r01_20260929_153520_912 \
  --reviewed-png-dir /path/to/visually_reviewed_full_frame_pngs
```

## 次の判断材料

追加録画なしなら、v12の未レビュー区間を同じ基準で確認し、より長い完全遮蔽と見える状態への復帰を確定できるか調べる。十分長い区間が確認できた場合だけ、固定候補の追跡失効・UNKNOWN・再捕捉を時系列で比較する。見つからなければ、その項目は未評価として残す。部分遮蔽や判定不能を完全遮蔽へ読み替えて合格扱いにはしない。

次段の[v12追加探索・復帰比較](../v12_occlusion_screening/README.md)を実施した。疎な33点と連続42 frameを重複除外して72点確認したが、確定した完全遮蔽は速度0の短い2 frameのみだった。長い完全遮蔽での前進時UNKNOWN通知は未評価として残し、確認できた可視復帰での測定採否を別に保存した。
