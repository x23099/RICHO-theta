# 2026-10-21 報告用画像

本日の作業は既存録画による既知寸法測距の検証。新しい撮影・実機出力ではない。[検証報告](../cone_known_size_pinhole_r01/README.md)

| ファイル | 内容・説明時の注意 |
|---|---|
| [known_width_vs_floor.png](known_width_vs_floor.png) | 設置距離に対する可視幅方式と同じ視線の床交点の比較。実測内部校正済み・本番使用可という意味ではない。 |
| [known_width_occlusion_and_yaw.png](known_width_occlusion_and_yaw.png) | 左は既存録画の遮蔽付近の推定、右は理想正方形の合成yaw感度。右を実験中の姿勢測定結果として使わない。 |
| [raw_paper_cone_2m_f001019.png](raw_paper_cone_2m_f001019.png) | 10/19の名目2.00 m条件のネイティブ1280×720カメラ画像。枠・文字・切抜き・拡大縮小・色変更なし。10/21の新規撮影ではない。 |
| [known_height_comparison.png](known_height_comparison.png) | ユーザー実測の全高73 cmによる測距比較。台座手前辺と先端軸の対応は未確認で、本番承認ではない。[高さ検証報告](../cone_known_height_pinhole_r01/README.md) |

カメラ画像の元セッションは `paper_cone_center_z2p00_r01_20261019_180411_245`、元フレーム番号1019。元の[フレーム来歴](../../2026-10-19/paper_cone_2m_validation_r01/raw_sample_manifest.csv)を参照。

3点は元ファイルからバイト同一でコピーし、SHA-256を確認した。[マニフェスト](known_width_manifest.json)。グラフは数値から新規生成したもので、カメラ画像の編集ではない。

追加の高さ比較グラフも元生成物からバイト同一で保存。[高さグラフの来歴](known_height_manifest.json)。元の3点・マニフェスト・カメラ画像は変更していない。

続く点対応検証のグラフも同日フォルダに保存：[投影方向と観測下辺の比較](../cone_plumb_support_r01/results_r02/plumb_support_comparison.png)、[遮蔽・列移動](../cone_plumb_support_r01/results_r02/plumb_support_occlusion_and_shifts.png)。これらは追加の解析図であり、上の代表4点や未編集カメラ画像は置き換えていない。数値の来歴と制限は[検証報告](../cone_plumb_support_r01/README.md)を参照。

後続の視線監査：[絶対角と角度サイズ](../cone_absolute_bearing_audit_r01/results_r01/absolute_vs_relative_bearing.png)、[床基準の角度と録画間の画素差](../cone_absolute_bearing_audit_r01/results_r01/floor_references_and_repeatability.png)。どちらも数値グラフでありカメラ画像の編集ではない。約7°は物理的取付変更の測定ではなく、未校正モデルの方向残差。[根拠・制限・テスト](../cone_absolute_bearing_audit_r01/README.md)
