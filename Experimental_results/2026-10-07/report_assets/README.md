# 2026-10-07 作成資料

9/29試験のchallenge間隔の再集計に加え、当日提出された完全遮蔽を意図したr01の録画も解析した。下記の生画像は提出された原本から抽出したもので、新たにこちらで収録した画像ではない。

| グラフ | 用途 |
|---|---|
| [challenge間隔・安定待ち](../challenge_jitter_review/challenge_interval_and_stability.png) | 発行元側と受信側のbag記録間隔、relayの1秒待ち直しを説明 |
| [v11実記録とv12オフライン許可](../challenge_jitter_review/relay_gate_recorded_vs_offline.png) | 鮮度とstream継続性の分離の効果。実記録対オフライン比較という制約を含む |

図は根拠CSV・スクリプトのある[診断フォルダ](../challenge_jitter_review/README.md)へ保存し、ここから参照する。同一PNGを重複保存しない。受信揺らぎのネットワーク／DDS／OS負荷の内訳は未確定。元カメラ画像には加工していない。

## 10/07 r01の追加資料

| 資料 | 用途 |
|---|---|
| [raw frame 1](full_occlusion_r01_raw_frame_0001.png) | 青箱の可視状態、全画角1280×720 |
| [raw frame 766](full_occlusion_r01_raw_frame_0766.png) | 板の上に青箱の上縁が残る部分遮蔽、全画角1280×720 |
| [全体タイムライン](../phase5_full_occlusion_dryrun_r01/trial_timeline.png) | 模擬速度、独立目視点、live状態、dry_run応答 |

録画sessionは`phase5_full_occlusion_dryrun_r01_20261007_162722_969`。frame 1は0.028944秒、frame 766は25.992993秒。[抽出manifest](full_occlusion_r01_export_manifest.csv)に対応元とピクセルハッシュを保存。PNG再読込のBGR値がrawデコードと一致し、注釈・切抜き・リサイズ・色補正は行っていない。

詳細と根拠CSV・生成スクリプトは[解析報告](../phase5_full_occlusion_dryrun_r01/README.md)。完全遮蔽の合格を示す画像ではない。復帰時CRITICALの追加診断図も同じ解析フォルダにある。

## 撮り直しr02

- [raw frame 420](full_occlusion_r02_raw_frame_0420.png)：13.985602秒、1回目の完全遮蔽。
- [raw frame 836](full_occlusion_r02_raw_frame_0836.png)：27.982785秒、2回目の完全遮蔽。
- [r02タイムライン](../phase5_full_occlusion_dryrun_r02/trial_timeline.png)：模擬前進中の2つの完全遮蔽、UNKNOWN単発、復帰後triple。

sessionは`phase5_full_occlusion_dryrun_r02_20261007_165130_432`。[抽出manifest](full_occlusion_r02_export_manifest.csv)と[rawピクセル照合](../phase5_full_occlusion_dryrun_r02/verification.json)を保存し、今回も全画角1280×720・無加工。成果報告には、部分遮蔽だったr01と混同せず、今回の2枚を完全遮蔽の例として優先する。

[r02解析報告](../phase5_full_occlusion_dryrun_r02/README.md)に、画像のサンプリング確認範囲と通信上の留保も記載した。日付内の複数試行の履歴として旧画像は削除していない。

## 反復r03

- [raw frame359](full_occlusion_r03_raw_frame_0359.png)：11.993116秒、1回目の完全遮蔽。
- [raw frame656](full_occlusion_r03_raw_frame_0656.png)：21.990126秒、2回目の完全遮蔽。
- [r03タイムライン](../phase5_full_occlusion_dryrun_r03/trial_timeline.png)：模擬前進中の完全遮蔽2回、UNKNOWN単発、復帰3連、dry_run応答。

sessionは`phase5_full_occlusion_dryrun_r03_20261007_171609_894`。[抽出manifest](full_occlusion_r03_export_manifest.csv)と[検証](../phase5_full_occlusion_dryrun_r03/verification.json)に原本対応・rawピクセル一致を保存。全画角1280×720の無加工PNG。詳細は[r03解析報告](../phase5_full_occlusion_dryrun_r03/README.md)。r023というK bag名はユーザー確認済みの誤記としてr03へ対応付けた。

## 静止距離参照

- [箱なしframe150](distance_reference_no_box_raw_frame_0150.png)：`record_reference_distance_reference_no_box_r01_20261007_174742_202`、4.986988秒。
- [1.10 m条件frame289](distance_reference_z1p10_raw_frame_0289.png)：`record_reference_distance_reference_center_z1p10_r01_20261007_174945_175`、9.995527秒。
- [距離タイムライン](../distance_reference_analysis/static_distance_timeline.png)、[距離の偏り](../distance_reference_analysis/static_distance_bias.png)：現行・同じrawでのbaseline再計算・凍結候補2方式の違い。測定起点と高さ・傾き変更なしのユーザー回答を反映済み。設置誤差・絶対姿勢の数値は未記録。

PNGは全画角1280×720、無加工。[箱なし抽出manifest](distance_reference_no_box_export_manifest.csv)と[1.10 m抽出manifest](distance_reference_z1p10_export_manifest.csv)、[raw一致検証](../distance_reference_analysis/verification.json)を保存。[解析報告](../distance_reference_analysis/README.md)から根拠CSV・生成スクリプトを追跡できる。安定して検出できたことと、絶対距離の正確さは区別する。

### 距離の追加診断

- [0.90 m条件frame300](distance_reference_z0p90_raw_frame_0300.png)、[1.30 m条件frame299](distance_reference_z1p30_raw_frame_0299.png)：上記1.10 m条件画像と合わせて箱の下端を比較するための追加資料。全画角1280×720、無加工。
- [接地点／床面投影の診断図](../distance_reference_analysis/distance_geometry_diagnosis.png)：目視した下端と凍結候補・申告距離の関係、固定pixelの幾何感度。目視幅は説明用仮定で、測定精度の信頼区間ではない。
- [共通誤差の両立範囲](../distance_reference_analysis/common_error_consistency.png)：説明用の目視±2 px条件では、3配置に共通する高さ単独またはoffset単独の値がないことを示す。逆算範囲は推奨設定や実測値ではない。

[追加PNGのmanifest](../distance_reference_analysis/geometry_raw_asset_manifest.csv)、[診断報告](../distance_reference_analysis/geometry_diagnosis.md)、[生成・検証スクリプト](../distance_reference_analysis/diagnose_distance_geometry.py)から元録画・frame・ピクセルhash・グラフのCSVを追跡できる。

### 下端幅方向の全frame診断

- [3距離の下端支持点グラフ](../distance_reference_analysis/bottom_support_diagnosis/bottom_support_profiles.png)：事前選択frameの幅方向分布。
- [右端1列の変化](../distance_reference_analysis/bottom_support_diagnosis/right_edge_support_comparison.png)：1.10 mの代表frame289と、診断基準で選択したframe65の支持点比較。カメラ画像の編集ではなく、CSVから生成した数値グラフ。
- [frame65の無加工raw PNG](distance_reference_z1p10_right_edge_raw_frame_0065.png)：2.207211秒。右端の支持点が大きいZになる最初の事例として出力確認後に選択したもので、blind評価用画像ではない。

[抽出manifest](distance_reference_z1p10_right_edge_export_manifest.csv)、[検証](../distance_reference_analysis/bottom_support_diagnosis/edge_assets_verification.json)、[報告・根拠CSV・再現手順](../distance_reference_analysis/bottom_support_diagnosis/README.md)。PNGは全画角1280×720・逐次rawデコードと画素一致、無加工。

### 過去4配置を用いた距離・横位置比較

- [左0.95 m・raw frame118](historical_holdout_xm0p22_z0p95_raw_frame_0118.png)：`holdout_xm0.22_z0.95`、当時CSVの公称3.933333秒。[manifest](historical_holdout_xm0p22_z0p95_export_manifest.csv)。
- [右1.20 m・raw frame145](historical_holdout_xp0p22_z1p20_raw_frame_0145.png)：`holdout_xp0.22_z1.20`、公称4.833333秒。[manifest](historical_holdout_xp0p22_z1p20_export_manifest.csv)。
- [距離・横位置の誤差比較](../distance_reference_analysis/historical_distance_comparison/historical_distance_bias.png)、[距離タイムライン](../distance_reference_analysis/historical_distance_comparison/historical_distance_timeline.png)。

原本は`coding_20260807_6.tar.xz`。代表画像は結果確認前に決めた各録画の中央frameを使用。今回も1280×720の全画角・無加工、逐次rawデコード／PNG再読込の画素一致を抽出時に確認した。グラフはカメラ画像の編集ではなく、位置CSVから生成。[解析報告・入力hash・根拠CSV・再現コード](../distance_reference_analysis/historical_distance_comparison/README.md)。当時の公称時刻は実測FPSではなく、この過去データは新規blind評価ではない。
