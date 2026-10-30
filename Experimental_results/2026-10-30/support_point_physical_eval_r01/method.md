# 支持点の物理的意味の評価（実行前固定条件）

## 目的

HANDOFF 7.2 に従い、既存の比較モジュールを本判定へ昇格させず、保存済みbbox・原画素・保存済み投影だけを使って、支持点が「実際の台座/床接点」とどこまで対応するかを評価する。時系列の滑らかさや概算距離への近さを、正しい接地点の証明に使わない。

## 入力（すべて保存済み。新しい推論・撮影・画像読取りなし）

| 入力 | 用途 | 出所の区別 |
| --- | --- | --- |
| `Experimental_results/2026-10-19/cone_contact_reuse_r01/full_replay_r01/positions.csv` | 5,143 frame × 3 model の保存済みbbox/色支持点・Z | 保存済み検出の再利用。新しいYOLO推論ではない |
| 同 `pixels.csv` | V30の色支持点、bbox下端、候補数、保留理由 | 同上 |
| `Experimental_results/2026-10-19/cone_support_extent_r01/results_r01/observations.csv` と `lower_envelopes.csv` | 観測支持範囲、同一列の下包絡 | 原画素から保存済みの画像観測 |
| `Experimental_results/2026-10-19/cone_support_quality_r01/results_r02/observations.csv` | 時間品質ゲートの採否・理由 | 画像観測の時系列判定。物理接地の判定ではない |
| `Experimental_results/2026-10-19/cone_contact_reuse_r01/results_r01/paired_anchors.csv` | 同一録画の床V点・台座候補・色支持点の保存済み投影 | 目視候補は非盲検・物理GT未確認 |
| `Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/contact_candidates.csv` | 1.30/2.00 mの床V先端画素 | 同一録画・別時刻。assistantの非盲検候補 |
| `Experimental_results/2026-10-19/paper_cone_2m_validation_r01/analysis_r01/paper_projection.csv` | 紙の局所左下角（床レベル）の画素と投影 | 既知ROIの色読取り。物理GTではない |
| 同 `cone_same_column_projection.csv` | 紙と同一X列のコーン下辺画素と投影 | 同上 |
| `Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/*` | 10/30 2画像の支持点・固定床モデルの条件付き距離 | 隔離診断。物理承認ではない |
| `Experimental_results/2026-10-30/cone_completion_logging_r01/current_pair_r01/results.json` | 従来/左右補完shadowの支持点と保留理由 | 保存CPU検出・2静止画 |
| `Experimental_results/2026-10-30/cone_saved_frame_audit_r01/findings_r01/colour_controls.json` | 赤・黄・混合マスクの接触辺と輪郭 | 保存画像のCPU再推論。ライブ出力そのものではない |
| `Experimental_results/2026-10-30/cone_lateral_completion_r01/README.md` の保存結果 | 黄色コーンの保留、補完候補の件数 | 比較ログ専用 |

生動画の再デコード、画像の再読込み、YOLO推論、HSV再抽出、校正fit、画素補正は行わない。

## 物理基準の区別

1. **同一sessionの床マーカー**（10/15床V、10/19紙角）: 同一録画に実在する床レベル点。最も強い相対基準。ただし画素候補は非盲検で、紙角は台座基準点との対応が未測量。
2. **名目設置距離**（10/15静止6本）: 台座のどの点までの距離か、設置誤差が未数値化。±18.75 cm（中心）や±37.5 cm（辺）の基準点差を超える食い違いだけを強い証拠として扱う。
3. **概算タイル距離**（10/30約1.5 m）: 誤差幅なしの概算。モデル選択や誤差採点に使わない。

## 評価量

### 1. 支持点が参照距離の床接点だと仮定したときの実効レンズ高さ

床交点式では、レンズ高さ `h`、支持点の投影距離 `Z_proj`、参照距離 `Z_ref` の間で `Z_proj / Z_ref = h / h*` が成り立つ。したがって

```
h* = h_model * Z_ref / Z_proj
```

を計算する。`h*` は「支持点が参照距離の床接点なら、レンズ高さはいくつでなければならないか」を表す。ユーザー申告の590 mmと比較する。`h*` は recorded58/height_only59 で同一値になる（両者は高さだけが異なるため）。paper_centre2 は中心・角度も変えるため、この式の比較対象から除外する。

`h*` が590 mmから外れる原因は、支持点の対応誤差、参照点の定義差、録画間の姿勢・校正差のいずれかであり、**支持点だけの誤差と断定しない**。参照点の基準差が最大37.5 cm（台座一辺）でも説明できない場合だけ、「基準点の定義差では説明できない」と記す。

### 2. 同一session床基準との相対比較

床マーカーと支持点を同じ幾何で投影し、`Z_support / Z_floor` を求める。これは共通の高さ・スケール誤差の影響を受けにくい相対検査である。画像上の同じX列で比較できる場合は、その列の実観測下包絡だけを使う。異なる列の場合は、その制約を明記する。

同一画素が床点と一致することは「同じ光線上の床交点」を意味するが、対象点が床から浮いている可能性を排除しない。単一画素では「床からの高さ」と「奥行き」を分離できないため、これは接地の必要十分条件ではない。

### 3. 時系列の滑らかさ

隣接frameの `Z` 差の中央値（mm）を計算する。滑らかさと `h*` の偏りを並べ、滑らかでも物理的に正しいとは限らないことを示す。滑らかさを採用根拠にしない。

## カテゴリ

- baseline: 中央静止0.80/1.30/2.00 m
- lateral: 左右1.30 m
- same-session floor reference: 10/15連続1.30/2.00 m、10/19紙・コーン2.00 m
- completion: 10/30 frame1259（左右補完shadow）
- baseline still: 10/30 frame1655
- yellow + same-colour floor: 10/30保存画像の黄色コーン
- occluded: 10/15 sequence 1124–1139
- small/distant: 2.00 m
- multiple candidates: 10/15 right_130 frame54/56/57
- crop/ROI edge: V30 `colour_contour_reaches_roi_edge` 100 frame、10/30 frame1259
- top/bottom crop contact: 10/30保存画像の混合/黄色マスク

## 禁止・維持事項

- 未保存bboxを当時の値として推測しない。
- 新しいCPU/GPU推論を過去のライブ出力と扱わない。10/30保存画像のCPU再推論はその旨を明記する。
- 参照距離に近いモデル・点を選ばない。支持点を参照距離へ動かさない。
- 補完shadowを本判定の支持点へ昇格しない。黄色を赤い小部分で救済しない。
- `physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false` を全出力で維持する。
- ライブ経路、設定、校正、ROS/TF、FFBを変更しない。
