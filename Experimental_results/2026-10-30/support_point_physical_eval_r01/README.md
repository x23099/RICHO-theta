# 支持点の物理的意味の評価 r01（保存データのみ）

HANDOFF 7.2 の範囲で、コーンの支持点が「実際の台座／床接点」とどこまで対応するかを、保存済みの CSV/JSON と保存済み投影だけを使って評価した。新しい推論、画像の再デコード、HSV 再抽出、校正・姿勢 fit、ライブ経路への接続は行っていない。

## 結論

1. **同一 session 内の相対的な床対応は支持できる。** 10/15 の床 V 先端と同じ X 列で比べると、支持点は 1.30 m で +1 px、2.00 m で 0 px。10/19 の紙角とコーン下辺は同一列で完全に同一画素 `(313,371)`。
2. **絶対的な距離・レンズ高さは未検証。** 同じ 2.00 m 名目でも、10/15 連続 session は 592.7 mm、10/15 静止 session は 446.1 mm、10/19 紙＋コーンは 330.6 mm を示す。支持点の相対対応が良いことは、絶対メートル精度の証明ではない。
3. **時系列の滑らかさは正しさではない。** 10/15 静止 2.00 m は隣接 frame 中央値 2.56 mm で滑らかだが、含意レンズ高さは 446.1 mm。連続 2.00 m の 0.60 mm も、それ自体では接地の証拠にならない。
4. **基準点の定義差だけでは 10/15 静止 2.00 m を説明できない。** 590 mm に合わせるには +0.645 m の奥行き offset が必要で、台座一辺 0.375 m を超える。ただしこれは「支持点だけの誤差」を意味せず、録画間の姿勢・校正差も分離できていない。
5. **10/30 の補完 shadow は画像被覆の修正であり、接地証明ではない。** 固定床モデルの条件付き範囲の和集合 1.403–1.528 m には概算 1.5 m が入るが、590 mm 入力時の 1 px 制御はどの単一モデルも 1.5 m を含まない（primary は 1.428–1.476 m）。これはモデル間の一致ではない。
6. **黄色コーンは保留のまま。** 黄色マスクは同一色の床と連結しており、赤い小部分 `[450,348,463,359]`（79.5 px²、下端 y=359）は黄色全体の下端 y=401 より 42 px 上にある。これを支持点に救済しない。

`physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false` を全出力で維持する。

## 物理基準の扱い

| 基準 | 強さ | 制約 |
| --- | --- | --- |
| 同一 session の床マーカー（10/15 床 V、10/19 紙角） | 最も強い相対基準 | 画素候補は assistant の非盲検候補。紙角は台座基準点との対応が未測量 |
| 名目設置距離（10/15 静止 6 本） | 弱い | 台座のどの点までの距離か、設置誤差が未数値化 |
| 概算タイル距離（10/30 約 1.5 m） | 参考のみ | 誤差幅なし。モデル選択・採点に使わない |

ユーザー申告のレンズ高さ 590 mm は入力条件であり、独立測定値ではない。以下の「含意レンズ高さ」は、支持点が名目参照距離の床接点だと仮定したときに整合するレンズ高さ `h* = h_model * Z_ref / Z_proj` である。連続 session で `h* ≈ 590 mm` になることは、名目距離と投影が同じモデル内で整合するという再表現であり、590 mm の独立確認ではない。

## 含意レンズ高さ（`height_only59`, V30）

| dataset | condition | 中央値 [mm] | p05–p95 [mm] | 隣接 frame Δ 中央値 [mm] | 590 mm に必要な offset [m] |
| --- | --- | ---: | ---: | ---: | ---: |
| sequence | cone_130 | 589.9 | 589.8–590.1 | 0.08 | +0.000 |
| sequence | cone_200 | 592.7 | 592.5–593.2 | 0.60 | -0.009 |
| static | center_080 | 531.7 | 531.4–532.5 | 0.44 | +0.088 |
| static | center_130 | 502.0 | 495.6–504.9 | 0.83 | +0.228 |
| static | center_200 | 446.1 | 445.7–447.5 | 2.56 | **+0.645** |
| static | left_130 | 538.3 | 529.0–549.4 | 14.99 | +0.125 |
| static | right_130 | 490.4 | 481.4–500.0 | 23.12 | +0.264 |

`+0.645 m` は台座一辺 0.375 m を超えるため、基準点の定義差だけでは説明できない。一方、0.80/1.30 m の offset は辺長以内で、支持点誤差と基準点差を分離できない。

## 同一 session 床基準との比較

| session | case | 床基準画素 | コーン支持画素 | 行差 [px] | 距離差 [m] | 含意高さ（床／コーン）[mm] |
| --- | --- | --- | --- | ---: | ---: | --- |
| 10/15 same-pose | C130 | `(310,416)` floor | `(310,417)` at x=310 | +1 | -0.0191 | 581.4 / 589.9 |
| 10/15 same-pose | C200 | `(311,393)` floor | `(311,393)` at x=311 | 0 | +0.0078 | 595.0 / 592.7 |
| 10/19 paper+cone | paper corner | `(313,371)` | `(313,371)` at x=313 | 0 | 0.0000 | 330.6 / 330.6 |

C130 の参照画素は床候補 `(310,416)` であり、コーン候補 `(310,417)` ではない。両者を混同すると行差が 0 に見えるため、`within_session_floor_check.csv` は `reference_candidate_kind` と `cone_candidate_pixel` を別列で保持する。

10/19 は相対対応が完全（同一画素）でありながら、名目 2.00 m に対して両方とも 3.5692 m へ投影され、含意高さは 330.6 mm になる。したがってこの session の絶対誤差の原因は支持点ではなく、姿勢・校正・参照距離の側にある。

## カテゴリ監査

| category | 採否 | 要点 |
| --- | --- | --- |
| baseline（中央静止 0.80/1.30/2.00 m） | 採用 | 名目ラベルのみ。2.00 m は +0.645 m で辺長超 |
| lateral（左右 1.30 m） | 採用 | 含意 538.3/490.4 mm。基準点定義と分離不可 |
| same-session floor reference（10/15 連続、10/19 紙） | 採用 | 相対対応は支持、絶対幾何は未検証 |
| completion（10/30 frame1259） | 条件付きのみ | 補完 shadow `(299,385)`。被覆修正であり接点証明ではない |
| baseline still（10/30 frame1655） | 条件付きのみ | 支持点 `(300,385)`。2 静止画の一致は接地証明ではない |
| yellow + same-colour floor（10/30 f004903） | 保留 | 黄色 bounds `[409,298,468,401]` が左・右・下の床と連結 |
| occluded（10/15 1124–1139） | 保留 | 16 中 15 frame を品質ゲートが棄却。可視境界 ≠ 床接点 |
| small/distant（2.00 m） | 採用 | 支持幅 27/31 px。同一名目距離で含意高さが 446.1/592.7 mm |
| multiple candidates（right_130 54/56/57） | 保留 | 最大スコアを選ばず非選択 |
| crop/ROI edge | 保留 | 100 frame。端接触 ≠ 床接触 |
| top/bottom crop contact | 保留 | 混合・黄マスクの下端接触。画素だけでは床と分離不可 |

## 10/30 固定床モデルとの両立

| frame / source | 条件付き範囲の和集合 [m] | primary の 1 px 制御 [m] | 590 mm 入力時 [m] | 580 mm 入力時 [m] |
| --- | ---: | ---: | ---: | ---: |
| 1259 / lateral_completion_shadow | 1.404–1.528 | 1.428–1.476 | 1.5270 | 1.5011 |
| 1655 / baseline_colour_shadow | 1.403–1.526 | 1.428–1.475 | 1.5263 | 1.5005 |

概算 1.5 m は和集合の内側にあるが、590 mm 入力時の 1 px 制御には入らない。`approximate_reference_agreement` は全行 `False` であり、`approximate_reference_used_for_selection=false` のまま。補完 shadow は制御距離へ昇格していない。

## 基本原理上の限界

単一の支持画素は「床からの高さ」と「光線方向の奥行き」を分離できない。同一光線上の床マーカーとの一致は接地の**必要条件**だが、十分条件ではない。支持点の物理的意味を確定するには、同一光線上の床基準に加えて、台座基準点の測量または既知寸法の対象が必要になる。

## 成果物

- `method.md`: 実行前固定条件
- `analyze.py`: 保存データのみの評価（出力先は新規ディレクトリ必須）
- `results_r01/implied_height_by_condition.csv`
- `results_r01/within_session_floor_check.csv`
- `results_r01/category_audit.csv`
- `results_r01/fixed_floor_1030.csv`
- `results_r01/support_point_physical_meaning.png`
- `results_r01/summary.json`, `results_r01/provenance.json`
- `verify.py`, `verification_r01/{verification.json,tests.log}`
- `../../tests/test_support_point_eval.py`

## 再現

```bash
cd RICHO-theta
python3 Experimental_results/2026-10-30/support_point_physical_eval_r01/analyze.py \
  --output-dir /tmp/support_point_eval_repro
python3 Experimental_results/2026-10-30/support_point_physical_eval_r01/verify.py \
  --evaluation-dir Experimental_results/2026-10-30/support_point_physical_eval_r01 \
  --output-dir /tmp/support_point_eval_verify
```

`analyze.py` は既存ディレクトリを上書きしない。`verify.py` は数値転記、入出力ハッシュ、推論・画像デコード非使用、ライブ経路の非変更、focused tests を検査する。`verification_r01` は `PASS_SAVED_DATA_ONLY`（27 tests）。

## 明示しないこと

- 支持点が実際の床接点であることの証明
- 592.7 mm や 589.9 mm を独立したレンズ高さ測定値とすること
- 概算 1.5 m への近さをモデル・点の選択根拠とすること
- 補完 shadow を制御距離へ昇格すること
- 黄色コーンの赤部分を支持点として救済すること
- ライブ経路、設定、校正、ROS/TF、FFB への反映
