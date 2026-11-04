# upper-support 実機ログの同一フレーム比較（2026-11-04）

## 結論

今回の提出物で解析可能。正常終了、今回のセッションに対する床モデルの受入れ、旧・新ログの対応、保存PNGの再現性を確認した。追加提出・撮り直しを要求する欠落はない。

モデル読込後は **旧3,776/3,852＝98.027%、新3,779/3,852＝98.105%**。差は **+3フレーム、+0.078ポイント**。既存の数値を失ったフレームは0。改善は実測できたが小さく、保留が解消したとは言わない。これは処理したフレームの数値出力率であり、画面表示率・物理的接地点の正しさ・FFB接続の合格ではない。

## 入力と対応

- 入力: `/home/robo25/Downloads/upper_support_capture_r01.tar.xz`。
- 安全確認後の展開先: `recordings/2026-11-04/upper_support_capture_submission_r01/upper_support_capture_r01/`（Git対象外）。23メンバー、479,138,643展開バイト。通常ファイルとディレクトリのみ。重複名、絶対パス、親ディレクトリ参照、リンク・特殊ファイルを拒否。入力を実行していない。
- `distance_frames.jsonl` と `upper_support_comparison.jsonl` は **38,311行ずつ**。全行を既存の厳密な検証器で検査し、session・frame・受信時刻・完了時刻・frame age・選択bbox・モデル状態・推論由来が対で一致。新ログ内の旧候補、旧数値、旧理由も元ログと完全一致した。
- 最初のsession `9d0ab80cc3144a5aabdb9991e3368b77`、その後 `b559e4240e364166935f9ede9ac3e7ae`。モデル有効前34,459行は比較の分母から除外した。待機中の値0を検出失敗として集計しない。
- モデルSHA256: `414ea62787afdc829900c12d109202ae5a0f75999e16259e12dccf109a87e92e`。参照画像frame **5755**、有効化frame **32629**、generation **1**。受入れmanifest・画像SHA・session/config/camera・過去フレーム条件を再検査した。
- `live_summary.json`: `runtime_status=STOPPED`、worker/run errorなし、cleanup errorなし、worker停止、scene/model job停止、shutdown complete。Q終了後の保存状態として整合する。

## 同じモデル・同じフレームの比較

比較区間はモデル有効後 **133.245秒、3,852行**。

|項目|旧方式|upper候補|
|---|---:|---:|
|生の支持点あり|3,800|3,801|
|生の支持点なし|52|51|
|支持点の再確認待ち|24|22|
|条件付き距離数値あり|3,776|3,779|
|数値なし|76|73|

旧・新とも数値がある3,776行では、モデル別の距離・理由・可否も完全一致。upper追加数値は **35562、35563、35564** の3行だけ。

frame35562は旧方式で上端接触により保留。upperは上だけを16px、32pxへ広げた2つの領域で同一の閉じた成分・元の下側支持範囲を確認し、元bbox内の観測点 `[308,417]` を維持して受入れた。前後の観測支持範囲とも連続していたため、新方式は既に成立した連続性を保った。旧方式はこの欠測後に35563・35564を再確認待ちとし、35565で復帰した。500ms鮮度や3フレーム確認条件を緩めた結果ではない。

[回復イベント図](detail_r02/recovered_event.png) / [有効区間の推移](detail_r02/live_comparison.png) / [根拠CSV](detail_r02/active_plot_data.csv)

## 残る51件の生の保留

|原因|件数|扱い|
|---|---:|---|
|上端接触を閉じても点が元bboxの外|12|拒否を維持|
|上端＋下端接触|1|upper-only対象外|
|下端接触|22|upper-only対象外|
|左端接触|16|upper-only対象外。既存の横補完でも受入れに至らない条件|

例: frame32654の拡張領域で点 `[308,419]` は読めるが、元bbox下端は417.418px。約1.582px外のため拒否した。ここを丸め・許容幅で通す変更は行っていない。残り22行は欠測後の連続支持確認待ちで、51+22=73行が新方式の数値なしに対応する。

保存された **8枚の1280×720生PNGすべて**についてSHA一致、同一session/frame、upper候補の全記録の再現、処理前後の画像画素不変を確認した。うち1枚は実際に救えたframe35562。画像の注釈・切抜き・リサイズ・色補正は行っていない。全51保留フレームの画像があるわけではなく、8枚以外はログによる診断である。

[画像検証記録](results_r02/evidence_verification.json) / [拒否フレームCSV](detail_r02/refused_candidates.csv)

## 距離値と実測1m

ユーザーが今回の設置距離を **1.00m** と確認。基準は車体中心の床投影点からコーン台座手前辺の中央までの水平直線距離として記録した。値の近さを利用したモデル選択・再校正は行っていない。

|モデル名の識別部分（s0）|upper中央値|実測1mとの差|
|---|---:|---:|
|as_listed / image_plane_plus_thickness|0.956833m|−4.32cm|
|as_listed / external_height_image_normal|0.970444m|−2.96cm|
|swapped / image_plane_plus_thickness|0.787063m|−21.29cm|
|swapped / external_height_image_normal|2.151475m|+115.15cm|

8候補中4候補はこの区間で数値なし。全候補を残しており、都合のよいものを正解として選んでいない。図のモデルは一覧先頭を固定使用し、精度で選んでいない。床面画像の紙角の曖昧さ、辺の対応、床モデルの複数解、カメラ直下と車体中心の対応、色支持点と実測した台座手前辺中央の対応は別問題として残る。表は**観測量の対応未検証の参考差**であって、完成済み距離精度の保証ではない。

## 処理時間と検証

有効区間のreceiver-local frame ageは中央値 **45.72ms**、95%点 **62.11ms**、最大 **110.11ms**。500ms超は0。YOLO時間中央値6.94ms、従来cone service時間中央値29.54ms。処理済み行は約28.90行/秒、処理入力間隔最大129.21ms、200ms超の間隔0。

追加処理を含む区間が500msの制限内に収まったことは確認できた。ただしupper単独の時間計測もON/OFFの対応実験もないため、追加負荷ゼロ・カメラ30fps達成・撮影から画面まで45msとは言えない。起動時の最初の1行だけ全区間集計で947msの遅延があり、値は保留、モデル有効区間外だった。

- 支持品質ゲートをモデル受入れ時から因果順に再生: **旧・新7,704判定一致**。upperの詳細品質記録も3,852行一致。
- 保存画像8枚の候補を同じbboxから再計算し、全記録一致。
- 旧・新合計 **30,220個** のモデル距離値を独立再計算。最大差 `1.33e-15 m`。実測との正しさではなく計算・記録の再現性検査。
- 既存435テストの対象ファイルSHAがすべて一致したため成功記録を再利用。今回runtimeソースは変更せず、解析スクリプトと成果物だけ追加。

[完全な監査JSON](results_r02/audit.json) / [因果再生と実測差](detail_r02/detail.json) / [既存テスト再利用の根拠](detail_r02/software_verification.json)

## 次の判断

今回は提出・保存・同時比較として完了。追加撮影を直ちに求める状態ではない。upper候補は限定された上端接触に有効だが、残る下端・横端・bbox外点を通す理由にはならない。次は既存の保存画像と拒否ログを使い、支持範囲の揺れと床モデルの不確定性を分けて診断する。実行時の採用、移動時の精度、ROS/FFBへの接続は未承認・未検証のまま。

GUIは従来経路のままなので、新候補の3フレーム改善を画面表示の改善としては数えていない。

## 再現

リポジトリ直下で実行。出力先は新しい名前が必要。既存展開先を使う場合は `--reuse-extraction` によりアーカイブと全ファイルのバイトSHAを再照合する。

```bash
OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-04/upper_support_capture_analysis_r01/analyze.py \
  --archive /home/robo25/Downloads/upper_support_capture_r01.tar.xz \
  --extracted-dir recordings/2026-11-04/upper_support_capture_submission_r01 \
  --reuse-extraction \
  --output-dir Experimental_results/2026-11-04/upper_support_capture_analysis_r01/results_repeat

OPENBLAS_NUM_THREADS=1 MPLCONFIGDIR=/tmp/theta_upper_capture_mpl \
  /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-04/upper_support_capture_analysis_r01/detail.py \
  --analysis-dir Experimental_results/2026-11-04/upper_support_capture_analysis_r01/results_repeat \
  --output-dir Experimental_results/2026-11-04/upper_support_capture_analysis_r01/detail_repeat
```

`results_r01` は解析側スクリプトのconfig SHA取得間違いで中断した途中成果で、判定に使用しない。修正後の正式結果は `results_r02` と `detail_r02`。全行CSVは大きいためGit対象外として再計算可能なまま残し、図の根拠となる有効3,852行は小さいCSVで保存した。取得された実験自体にこの解析エラーは起きていない。
