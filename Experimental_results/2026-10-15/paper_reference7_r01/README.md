# 白紙7点の録画確認・投影診断（2026-10-15）

## 結論

**7か所すべてに対応する配置と、角を読める区間が入っていた。今回の不足を理由とする再撮影は不要。**
紙の移動・置き直し・人の遮蔽を含むため、経過秒から保守的な内部区間を切り出した。
白紙の同じ角を用いることで、以前の遠方V字先端より位置を特定しやすくなった。
ユーザーから、7か所とも「車体に近い辺の左端の角」を指定座標へ合わせたと確認を得た。
座標の対応は直前の撮影手順・移動方向・確認回答に基づくもので、画像だけで実距離を計測したという意味ではない。

投影設定のずれも確認できた。既存設定では中央2.00mがZ=2.815mだったが、
5点だけで画像中心X/Yを調整したオフライン候補ではZ=2.026m。
調整に使わない1.00/1.60mも、Z誤差は-0.0425/+0.0064mだった。
**本番設定への採用、コーンの接地点精度、TTC/実機FFBの合格を意味しない。実機設定は変更していない。**

## 入力・完全性

- archive: `/home/robo25/Downloads/itiawase2_20261015_183552_599.tar.xz`
- 展開先: `recordings/2026-10-15_paper_reference7_intake_r01/itiawase2_20261015_183552_599/`
- raw/BEV/detection/CSV: 全て7,650frameで一致。frame連番・時刻単調増加・処理時間項目はPASS。
- 経過時間256.488秒、記録間隔から29.824fps、native1280×720、取得設定MJPG30fps。
- ODOMは全frameで取得され、記録された並進/回転速度は全て0。
  ODOMが0という事実だけで微小なカメラ姿勢不変を保証はしない。
- AI・FFB publisher・relayはmetadataで無効。今回も新しいモデル推論やROS通信は行っていない。
- 元archive/metadata/raw/CSVのhash不変、51枚の無加工PNGの寸法・pixel hash一致を確認した。

## 7か所の確認

以下は全静止期間の厳密な開始・終了ではなく、操作の前後を避けた**解析採用区間**。
10秒未満でも複数frameの読取りは可能であり、一律に欠測とは扱わない。
主閾値170は距離誤差を見る前に固定。frame数を独立した測量点数として扱わず、各配置の中央値を1点とした。

| 配置 | 指定角のX,Z [m] | 経過秒 | 区間frame数 | 主閾値で角候補を読めた数 | 角pixel中央値 (x,y) | 代表raw |
|---|---|---|---:|---:|---|---|
| C080 中央 | 0,0.80 | 1～15 | 420 | 420 | 315,440 | [frame247](raw_samples/paper7_f000247.png) |
| C130 中央 | 0,1.30 | 27～34 | 210 | 210 | 312,404 | [frame987](raw_samples/paper7_f000987.png) |
| C200 中央 | 0,2.00 | 46～51 | 146 | 43 | 309,378 | [frame1481](raw_samples/paper7_f001481.png) |
| L130 左 | -0.40,1.30 | 126～130 | 120 | 120 | 258,403 | [frame3758](interval_review/paper7_f003758.png) |
| R130 右 | +0.40,1.30 | 146～151 | 148 | 148 | 363,398 | [frame4442](raw_samples/paper7_f004442.png) |
| H100 確認用 | 0,1.00 | 205～209 | 120 | 120 | 313,425 | [frame6169](raw_samples/paper7_f006169.png) |
| H160 確認用 | 0,1.60 | 231～238 | 210 | 210 | 310,390 | [frame6909](raw_samples/paper7_f006909.png) |

合計1,374frame中1,271frameで主閾値の四角形条件を満たした。
C200の103frameは輪郭が四角形条件を満たさず拒否。**録画がないわけではない**。
閾値140/200ではこの区間146/146frameを読め、中央値は主閾値から各軸最大1pxの差。
都合のよい閾値に差し替えず、失敗も `threshold_summary.csv` に残した。

特記事項：

- 冒頭は既に紙がある。最初の紙なし約5秒はないが、末尾249～256秒に撤去後がある。
  今回の角読取りを無効にはしない。[末尾raw](raw_samples/paper7_f007650.png)
- 途中に中央へ戻す操作や、104～108秒の右側の途中配置がある。
  右側の途中配置は座標未割当の別IDに保持し、同じ点を重複fitしていない。
  L/Rを「4番目/5番目の静止らしい部分」だけで機械的に割り当てていない。
- ノートPCを一時的に前方へ出す区間は除外。H100は前方からPCが退いた後の205～209秒を使用。
- 閾値200ではR130が1/148frameしか四角形にならず、閾値140のH160は巻尺との連結で
  205/210frameがROI境界条件に掛かった。これは一般的な白紙検出器の完成を示さない。
  主閾値170の7点中央値は区間内の各軸変動0～1pxだが、測量誤差・反り等の絶対誤差は未測定。

## 投影比較

高さ実測59cmを固定し、C080/C130/C200/L130/R130の5点だけで中心X/Yを調整した。
H100/H160のpixel・座標はsolverへ渡していない。比較方法・範囲は[method.md](method.md)。

| 配置 | 参照Z [m] | 既存設定のZ [m] | 中心調整候補のZ [m] | 候補のZ誤差 [cm] |
|---|---:|---:|---:|---:|
| C080 | 0.80 | 0.929 | 0.795 | -0.46 |
| C130 | 1.30 | 1.578 | 1.279 | -2.11 |
| C200 | 2.00 | 2.815 | 2.026 | +2.63 |
| L130 | 1.30 | 1.582 | 1.289 | -1.05 |
| R130 | 1.30 | 1.672 | 1.319 | +1.93 |
| H100（fit対象外） | 1.00 | 1.136 | 0.958 | -4.25 |
| H160（fit対象外） | 1.60 | 2.080 | 1.606 | +0.64 |

| モデル | 調整5点の平面位置RMSE [cm] | 確認2点の平面位置RMSE [cm] | 確認2点の最大平面位置誤差 [cm] |
|---|---:|---:|---:|
| 記録設定（高さ58cm） | 46.52 | 37.04 | 50.12 |
| 高さのみ59cmへ変更 | 49.59 | 39.80 | 53.63 |
| 59cm固定＋中心X/Y調整候補 | 2.72 | 3.12 | 4.28 |

RMSEはX/Z両方の残差から算出。Zだけの誤差とは異なる。
今回の5点については、高さを1cm直すだけではずれは改善せず、中心X/Yの2自由度の修正で大きく縮小した。
ただしこれは「取り付けが動いた」「実際のレンズ中心がこの値」と原因を断定する根拠ではない。
同一録画の狭い床領域を説明できる候補が得られた段階で、完全な魚眼内部校正ではない。

候補は `analysis_r01/centre2_offline_candidate.json` に保存。
`camera_height=0.59, front_cx_offset=-91.3697403, front_cy_offset=-34.7149841`。
pitch/roll/yaw/radius、後方レンズは記録値のまま。探索境界には達していない。
**このJSONは本番設定ファイルではない。起動引数へ指定しない。**

## 残る確認と次の作業

追加撮影なしで、まず今回の候補を既存のコーン録画の保存bbox/接地点候補へ適用し、
中央・左右・距離ごとに改善/悪化を再計算する。床の角が読めても、コーンbbox下端が真の接地点とは限らない。
床用候補のfitへコーンの正解値を混ぜたり、コーン誤差で今回の閾値/区間を選び直したりしない。

今回のH100/H160はfit未使用だが同一撮影内の確認点であり、別録画・別環境への汎化試験ではない。
撮影間の転用確認とコーン接地点の切り分けが終わるまでは、本番校正/実機FFBへ採用しない。
元のV字による探索候補は置換・書換えず残した。今回の録画を受けてカメラの固定不良を再び前提にしていない。

## 成果物・検証

- [角pixel時系列](analysis_r01/paper_corner_timeline.png)：根拠は `corner_candidates.csv`。
- [投影比較グラフ](analysis_r01/projection_comparison.png)：根拠は `projection_comparison.csv`。
- 全7,650frameの扱い：`analysis_r01/frame_ledger.csv`。
- 閾値別集計：`analysis_r01/threshold_summary.csv`、主点：`reference_points_primary170.csv`。
- 無加工raw51枚、`raw_sample_manifest.csv` / `interval_review_manifest.csv` にframe/時刻/hash。
- `analysis_r01/provenance.json` に入力・使用実装・成果物のhashと非変更/非採用フラグ。
- 既存角読取りの12テスト、新規結果監査の7テスト：全19件PASS。
  監査は全frame台帳・主点中央値・fit再現・holdout混入拒否・順逆投影・PNG/hash・非変更を確認した。
- matplotlibのAxes3D警告が出たが、使用する2Dグラフ2枚は生成・表示確認済み。

再現コマンド（生成scriptは出力先既存時に上書き拒否。再解析は新しい版へ複製して実施）：

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-15/paper_reference7_r01/intake.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-15/paper_reference7_r01/export_review.py
/home/robo25/theta-env/bin/python3 Experimental_results/2026-10-15/paper_reference7_r01/analyze.py
/home/robo25/theta-env/bin/python3 -m unittest discover -s Experimental_results/2026-10-15/paper_reference7_r01 -p 'test_audit.py' -v
/home/robo25/theta-env/bin/python3 -m unittest discover -s Experimental_results/2026-10-15/white_paper_visibility_r01 -p 'test_paper_visibility.py' -v
```

既存の未コミット作業は保持。今回Git commit/pushや日報作成は依頼されていないため実施していない。
