# 2026-10-15 報告用資料

日報に対応する代表4点。rawは全画角・元解像度1280×720・無加工PNG。
既存解析からバイト同一で複製し、hashを `manifest.json` に記録した。

| 資料 | 内容・出典 | 注意 |
|---|---|---|
| [中央1.30mの赤コーン原画像](raw_cone_center1p30_f000217.png) | `10151400.tar.xz`、session `cone_static_center_z1p30_r01_20261015_135329_732`、frame217、7.221865秒 | 枠や注釈を付けていない。原点から台座の車体側辺までの設置条件 |
| [白紙・中央2.00mの原画像](raw_paper_center2p00_f001481.png) | `itiawase2_20261015_183552_599.tar.xz`、同名session、frame1481、正確な経過秒はmanifest | 紙の車体側辺の左角が参照点。画像に目印を追加していない |
| [遮蔽時の距離品質ゲート](cone_occlusion_quality_gate.png) | [元CSV/グラフ](../cone_observation_quality_r01/results_r01/)・[生成script](../cone_observation_quality_r01/replay.py) | 不自然な距離を確認待ちにする例。校正済み・実機FFB成功の図ではない |
| [白紙7点の補正前後比較](paper_reference_projection_comparison.png) | [projection_comparison.csv](../paper_reference7_r01/analysis_r01/projection_comparison.csv)・[生成script](../paper_reference7_r01/analyze.py) | H100/H160はfit対象外。同一録画内の仮候補で、本番採用ではない |

原画像の出典と画素hashは、元の `raw_sample_manifest.csv` と本フォルダの `manifest.json` から追跡できる。
`collect.py` は元画像を加工せずコピーするだけで、既存出力の上書きを拒否する。
グラフ2枚は元CSVから生成済みの数値図であり、カメラ画像の加工ではない。
