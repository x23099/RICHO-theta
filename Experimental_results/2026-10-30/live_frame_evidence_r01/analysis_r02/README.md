# 実機同一フレーム証拠ログ r02 の解析（接触辺の特定）

2026-10-30、GPU PC（RTX 4070 Laptop、torch 2.7.1+cu118）で取得した60秒静止ログ。r01で未確定だった「cropのどの辺に色輪郭が接しているか」を、`mask_diagnostics`で特定した。

## 結論

- 接触辺は**左 100%、右 89%、下 93%、上 0%**。左だけでなく、右と下にも同時に接している。
- 接触は0 px（crop端そのもの）で、cropは中央値55×97 px。輪郭はcropの左端から右端・下端まで広がっている。
- 保存PNGの同一マスクを再計算すると、下端の接触19 pxはすべて黄系（Hue≈18、S≈81–83、V≈160）で、**床のベージュがHSV下限S=80をわずかに超えて連結**している。左は黄40 px＋赤4 px、右は黄6 px＋赤4 px。
- つまり主輪郭は「赤コーン」ではなく「赤コーン＋同色の床・背景」であり、cropで切られた形になっている。`colour_contour_reaches_roi_edge`による棄却は、現在の規則どおりの保守的判断として正しい。
- 基準支持点0/1,689、姿勢0/1,689、距離0/1,689はr01と同じ。**支持点が無いのはコーンに下端が無いからではなく、unionマスクが床と分離できていないため**。
- 赤のみのshadowは1,636/1,689で画像点を持つ（例: frame635 `[286,387]`）。ただしshadowは制御支持点ではない。今回の結果だけを理由に本判定へ昇格しない。
- 姿勢は`fewer_than_six_distinct_planes`のまま独立に不成立。支持点が取れても距離は出ない。

## 入力

| 項目 | 値 |
| --- | --- |
| archive | `/home/robo25/Downloads/live_frame_evidence_r02_20261030_185348.tar.xz` |
| archive SHA-256 | `4043dbe652abe194f47dcc788cd3b560f2c2eae1f8ae8c7b231f35dce9839664` |
| 展開先（Git外） | `recordings/2026-10-30/live_frame_evidence_r02_20261030_185348/` |
| `distance_frames.jsonl` SHA-256 | `5f0396a6f40e2fbef1c29613b8850523075324e0574b8ee44ec31748abc009e7` |
| `live_summary.json` SHA-256 | `ad32090cf0ecbce57c4df06325fa21104099da48fbaf539714b1ab60d8956ef1` |
| session | `f860e50d1c4e485a98cbc1a2f6138cdf` |
| 実行時間 | 60.02 s、`STOPPED`、cleanup errorなし |
| GPU / weights | RTX 4070 Laptop / `3a6e124a...`（設定と一致） |
| target ROI | `[270, 0, 350, 720]` |
| 有効フラグ | `frame_evidence=true`、colour/completion shadow=true |

SキーPNGは3枚（frame 311/635/1218）。うち2枚を無加工で`evidence/`へ複製した。

| 画像 | SHA-256 |
| --- | --- |
| `decoded_..._f000635.png` | `5a78fc8410999bfda7863ee9af28adbd6fe01026c0e72686ddb08398d2a38c54` |
| `decoded_..._f001218.png` | `5f8c36fcd23ce880dd7941882d893facdfce7755cba986c2e5de71d0c6ee8a99` |

いずれも1280×720。切り抜き・縮小・注釈・色補正は行っていない。

## 定量結果

| 項目 | 結果 |
| --- | ---: |
| 処理フレーム | 1,689 |
| 選択bbox 1個 | 1,689 / 1,689 |
| 基準支持点あり | 0 |
| 姿勢利用可能 | 0 |
| 距離出力 | 0 |
| mask診断あり | 1,689 / 1,689 |
| 鮮度500 ms以内 | 1,688（初回のみ1,000.5 ms） |
| frame age 中央値 / p95 / 最大 | 13.63 / 17.21 / 1,000.52 ms |
| bbox幅 / 高さ 中央値 | 46.87 / 88.40 px |
| bbox confidence 中央値 | 0.949 |
| crop幅 / 高さ 中央値 | 55 / 97 px |

### 接触辺の組み合わせ

| 接触辺 | フレーム数 |
| --- | ---: |
| 左・右・下 | 1,401 |
| 左・下 | 169 |
| 左・右 | 102 |
| 左のみ | 17 |
| 上を含む | 0 |

辺ごとの接触率は左1,689（100%）、右1,503（89.0%）、下1,570（92.9%）、上0（0%）。

### 境界の余裕

| 辺 | 最小 | 中央値 | 最大 |
| --- | ---: | ---: | ---: |
| 左（contour_x1 − crop_x1） | 0 | 0 | 0 px |
| 右（crop_x2−1 − contour_x2） | 0 | 0 | 7 px |
| 下（crop_y2−1 − contour_y2） | 0 | 0 | 1 px |

輪郭数は1個374、2個1,207、3個105、4個3フレーム。第2輪郭が25%未満のため曖昧扱いにはならないが、主輪郭自体がcropいっぱいに広がっている。

### 保存PNGによるマスク境界の確認（frame 635）

`decoded_..._f000635.png`に、実装と同じV30 union HSVを適用した。cropは`[265,296,320,393]`、マスク画素2,682。

| 辺 | マスク画素数 | 内訳 | 例（Hue, S, V） |
| --- | ---: | --- | --- |
| 左 | 44 | 黄40、赤4 | (24, 98, 130)、(10, 216, 130) |
| 右 | 10 | 黄6、赤4 | (21, 84, 127)、(8, 80, 204) |
| 下 | 19 | 黄19、赤0 | (18, 81–83, 157–161) |
| 上 | 0 | — | — |

下端はすべて黄系で、彩度Sが下限80を1–3だけ超えている。ベージュ床がマスクに入り、赤コーンと連結していることを示す。左・右はコーンの赤と背景の黄の両方がcrop端に達している。

この確認は保存済みPNGへのマスク再適用であり、新しいYOLO推論・HSVしきい値変更・距離再計算ではない。生成は`inspect_saved_mask.py`、結果は`mask_edge_sample.json`。

```bash
python3 Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/inspect_saved_mask.py \
  --png Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/evidence/decoded_f860e50d1c4e485a98cbc1a2f6138cdf_f000635.png \
  --crop 265 296 320 393 \
  --output-json Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/mask_edge_sample.json
```

## 解釈

現行の`observe_support`は、bboxを4 px広げたcrop内で赤・黄・混合のunionマスクを作り、最大輪郭がcrop端に接したら棄却する。今回の場面では:

1. ベージュ床のSが80前後で、黄色範囲`(15,80,30)-(40,255,255)`に入る。
2. 赤コーンと床が1つの輪郭として連結する。
3. その輪郭が55×97 pxのcropを埋め、左・右・下で接触する。
4. 棄却は規則どおり。支持点0は「コーンに下端が無い」ことを意味しない。

赤のみのshadowが1,636フレームで点を持つことは、分離色なら輪郭が取れることを示す。しかしshadowは7.2の評価を通っていない比較ログであり、基準支持点の代替にはしない。

## 次の判断

1. **赤のみ候補を7.2の評価対象として扱う**。同一session床基準との相対対応、カテゴリ別の誤対応、黄色コーンとの整合を保存データで確認してから、制御支持点へ昇格するか決める。今回の1,636点をそのまま採用しない。
2. **unionマスクの背景除去**を設計するなら、距離に近い値でしきい値を選ばず、保存フレームで赤/黄/床の分離性能を先に評価する。S=80を下げる/上げるだけの調整は、黄色コーンと床の両方に影響するため行わない。
3. **姿勢は別問題**。`fewer_than_six_distinct_planes`は支持点を直しても残る。6平面条件の緩和や別録画姿勢の流用はしない。

## 成果物

- `flatten/frame_evidence.csv`: 1,689行。crop・輪郭bounds・接触辺を含む
- `flatten/counts.json`: 接触辺別件数、support/pose/freshness件数
- `report/report.md`, `report/summary.json`, `report/processed_frames.csv`, `report/processing_diagnostics.png`
- `inspect_saved_mask.py`: 保存PNGへのマスク再適用スクリプト
- `mask_edge_sample.json`: frame635の境界マスク内訳
- `evidence/`: 無加工PNG 2枚

```bash
cd RICHO-theta
IN=/home/robo25/theta_ws/recordings/2026-10-30/live_frame_evidence_r02_20261030_185348
python3 Experimental_results/2026-10-30/live_frame_evidence_r01/flatten_evidence.py \
  --input-dir "$IN" --output-dir Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/flatten_r02
python3 src/summarize_cone_distance_live.py --input-dir "$IN" \
  --output-dir Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/report_r02
```

出力先は新規ディレクトリ必須。`analysis_r02`は今回の固定結果。

## 明示しないこと

- 赤のみshadow点が床接点であること
- 支持点0を「コーンが検出されていない」と解釈すること
- ベージュ床を除くためだけのHSVしきい値変更
- 距離0の原因を支持点だけと断定すること（姿勢も独立に不成立）
- 条件付きログを距離精度・接地・FFBの合格とすること
