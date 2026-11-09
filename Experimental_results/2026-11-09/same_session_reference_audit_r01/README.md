# 同一セッションの別画像による床基準の監査（2026-11-09）

## 結論

**ローカルの提出物で追加確認できた床紙は、b559のframe2427の1枚だった。既存frame5755とほぼ同じ配置のため、フレーム間の読み取り再現性は確認できるが、別の物理基準による精度検証にはならない。**

半窓4pxの補正では2枚間の紙角差は最大約0.059px、条件付き床高さの差は約0.93mmだった。これは「同じ紙画像が繰り返し似た値になる」という結果で、サブmmの実距離精度や床姿勢の正しさを証明しない。

ユーザーから、学校PCに追加の元動画・画像が残っているとの回答を受けた後、候補5アーカイブが追加提出された。[追加提出物の照合](../archive_reference_intake_r01/README.md) では全70通常ファイルが既存ファイルと一致し、元動画・別位置の床画像は増えなかった。この監査はリモートの保存領域全体にはアクセスしておらず、他所に追加情報が存在しないとは結論していない。新たな撮影は実行していない。

## 1. 棚卸しの範囲と結果

対象session：`b559e4240e364166935f9ede9ac3e7ae`、`df33e833acdf4e7d8b00d1ec37b7bcae`。

- `recordings/2026-11-04/` のnative decoded PNGを全件調べ、同じsession/frameの別パスはSHA一致を確認して重複扱いにした。
- `/home/robo25/Downloads/` の対応する元PNGも照合。ファイル名が似た解析図・GUIスクリーンショットを新しい生フレームと数えていない。
- 提出済み `upper_support_capture_r01.tar.xz` は**再展開せず**メンバーとPNGのバイトSHAを照合した。
- ローカル対象ディレクトリと提出アーカイブに連続動画形式（AVI/MP4等）はなかった。学校PC・未提出フォルダ・全ての別アーカイブに存在しないと主張するものではない。
- 別sessionの9b7画像は、今回の幾何確認へ流用しない。

|session|重複除外後のframe数|床紙が見えるframe|紙が見えないframe|
|---|---:|---|---:|
|b559|10|2427、5755|8|
|df33|3|2292|2|
|合計|13|3枚|10|

`recordings/` には14パスあり、b559の5755は同一バイトのコピーが2か所にあった。アーカイブの対応PNG10枚も既存ローカル画像と全件一致し、追加観測ではない。

根拠：[unique_frame_inventory.csv](results_r02/unique_frame_inventory.csv)、[duplicate_paths.csv](results_r02/duplicate_paths.csv)、[archive_image_members.csv](results_r02/archive_image_members.csv)。紙の有無は元画像全体を見たassistantの観察で、人が新たに確定したラベルや物理測定ではない。未知の追加frameは自動的に「紙なし」と分類せず、再度の画像確認を要求する。

## 2. b559の2枚を独立に読み直した結果

各画像から既存の固定ROI `[280,395,90,50]`、gray閾値170、輪郭近似係数0.025で抽出し、補正なし/半窓2/3/4pxを適用した。片方の角座標を他方へコピーしていない。手動座標・距離ラベルから開始せず、各画像から床仮説8通りを求め、計64モデル応答を保存した。

比較表は以前からの先頭系列 `as_listed_s0_image_plane_plus_thickness` を固定表示し、方式や物理解を選んだことにはしない。

|処理|4角の最大フレーム間差|f2427の床高さ|f5755の床高さ|
|---|---:|---:|---:|
|旧輪郭のみ|0px|581.72mm|581.72mm|
|半窓2px|0.0873px|555.28mm|557.43mm|
|半窓3px|0.0242px|562.51mm|562.63mm|
|半窓4px|0.0591px|581.69mm|580.77mm|

根拠：[paper_frame_corner_differences.csv](results_r02/paper_frame_corner_differences.csv)、[paper_frame_geometry.csv](results_r02/paper_frame_geometry.csv)、[比較図](results_r02/same_paper_frame_repeatability.png)。旧輪郭の0px差は整数頂点の量子化による同じ返却値で、真の角が不動だった証明ではない。元画像のSHAは異なる。

持越しの高さ590mm、紙296×210mm、板厚約15mmは今回の再測定ではない。録画メタデータの `static_camera_only: true` は静止を前提とした運用条件で、外部測量による床姿勢不変の検証ではない。2枚の紙は画像上ほぼ同位置だが、厳密な物理移動ゼロは確認できていない。

## 3. 固定光線の応答と、実際のコーン距離を区別

床モデルの変化を比べるため、同sessionの後半frame35562で記録された点 `[308,417]` を**固定の試験光線**として両画像のモデルへ入力した。半窓4pxでは約0.974036→0.974617m、差は約0.58mmだった。

**これはf2427/f5755に写るコーンそのものの距離ではない。** 写っているコーンの実測位置が新たに分かったわけでも、0.58mmの測距精度を確認したわけでもない。CSVには `probe_is_actual_target_in_this_paper_frame: false` と `fixed_ray_response_only_NOT_current_frame_cone_distance` を明記した。将来フレームの試験画素で過去のlive出力を生成・承認したことにもしていない。

後半の8枚のb559コーン画像と2枚のdf33コーン画像では、床の紙は見えず、紙からその場の姿勢を再確認できなかった。床タイルや机脚は見えるが、今回画像に対する既知座標・寸法・対応点の裏付けなしに、独立の測量基準とは扱わない。

## 判断と次の入力

1. 別PNGは増やせたが、**同じ小さな紙の同配置を繰り返し観測しただけでは、前段で残った高さ・距離の偏りを解消できない**。
2. 手元の13frameについて、異なる位置の既知床基準が追加で得られたとは判定しない。旧校正・手動角・新補正を、そのままlive用モデルへ置換しない。
3. ユーザーが候補として追加提出した5アーカイブは検査済みで、新しい元動画・別位置画像はなかった。必要なのは、今回と同じカメラ取り付け・キャプチャ条件で、別位置の紙やより明瞭な床基準を観察できる情報である。別sessionしかなくても捨てずに条件を確認するが、現在sessionへ自動転用はしない。
4. このほかに元映像が残っていれば、その保存先を確認する。残っていなければ独立した床基準の新規記録が必要となるため、不足に限定した撮影条件を相談する。学校PCへ未承認の接続・機体の起動は行わない。

## 検証・再現

[verification_r01/verification.json](verification_r01/verification.json)：**関連90テスト成功、失敗/エラー/skip 0**。新規6試験でsession/frame識別、解析図の除外、バイトコピーの重複除外、同一IDの異なるPNG拒否、assistantの観察と人の物理測定の区別、未知frameの再確認要求を検証した。

元画像・人の確認JSON・元アーカイブのSHA不変、全8仮説の保持、固定試験光線と実際のターゲットの区別、既存runtime不変を確認。既存435試験はソースSHA不変で前回成功結果を再利用した。元PNGの注釈・加工・再保存はなく、比較グラフだけ別ファイルへ生成した。Git commit/pushなし。

```bash
cd /home/robo25/theta_ws/RICHO-theta
OPENBLAS_NUM_THREADS=1 MPLCONFIGDIR=/tmp/theta_reviewed_coordinate_mpl \
  /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-09/same_session_reference_audit_r01/analyze.py \
  --output-dir Experimental_results/2026-11-09/same_session_reference_audit_r01/results_reproduced_r01

OPENBLAS_NUM_THREADS=1 MPLCONFIGDIR=/tmp/theta_reviewed_coordinate_mpl \
  /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-09/same_session_reference_audit_r01/verify.py \
  --output-dir Experimental_results/2026-11-09/same_session_reference_audit_r01/verification_reproduced_r01
```

新規出力先が必要。Git外の `recordings/2026-11-04/`、このPCのDownloads内の対応PNG・提出アーカイブも再現入力に含む。`summary.json` の `source_sha256` はリポジトリ相対パスとDownloads絶対パスを区別して記録した。正式版は `results_r02/`、初回計算は削除せずGit対象外で保持した。
