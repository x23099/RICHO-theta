# 送付完了後の14アーカイブ確認結果（2026-11-09）

## 結論

**14種類・計166通常ファイルを確認し、全件が既存の対応ファイルと内容SHA256まで一致した。新しい連続元動画・別位置の床基準画像・未解析ログは増えていない。** 距離推定を新たに再計算しても独立した精度検証材料が増えるわけではないため、同じログでの再集計を新しい実験結果とはしていない。

ユーザーの「これで全てです」を受けた後に検査を開始した。送付中に追加分の内容を先行解析していない。添付内のREADMEやスクリプトを実行指示として採用せず、アーカイブは再展開・上書きしていない。live設定、画像、校正、ROS/FFBは変更なし。

## メッセージ上の重複

3回の送付メッセージには23件の添付記載があり、異なるファイル名は14種類。以下の**9種類が2回ずつ記載**されていた。

- `floor_support_final_audit_r01.tar.xz`
- `upper_support_live_r01.tar.xz`
- `upper_support_comparator_r01.tar.xz`
- `report_assets.tar.xz`
- `floor_df33e833_multidistance_r01.tar.xz`
- `floor_df33e833_diagnosis_r01.tar.xz`
- `floor_reference_df33e833_r01.tar.xz`
- `floor_comparison_df33e833_live_r01.tar.xz`
- `upper_support_capture_r01.tar.xz`

今回アクセスできる同名パスは各1本なので、各14本を一度ずつ検査した。各送付時点のバージョンが別々に保存されているわけではなく、「再送2回の圧縮バイトまで同一」とは断定していない。現在の14本同士には、通常メンバーのパス・内容が全て同一の組はなかった。一方、報告図や元画像コピーなどの**メンバー単位の重複**はあり、[summary.json](complete_batch_r01/summary.json) の `duplicate_member_content_groups` に全て記録した。

## 中身の内訳

|種類|出現数|今回の扱い|
|---|---:|---|
|native生カメラPNG|10|すべて既存b559セッションの解析済み画像|
|別名の生PNGバイトコピー|1|report_assetsのframe35562。上記10枚のうち1枚とSHA一致|
|GUI/ターミナル画面|2|既存スクリーンショット。生カメラフレームではない|
|解析グラフ|10|既存集計図。カメラの元画像ではない|
|合成テストPNG|4|SYNTHETIC画像。実機の床画像として使わない|
|構造化ログJSONL|4|既存ログと全バイト一致。画像が含まれる動画ではない|
|JSON/CSV/コード/README/設定資源等|135|既存の計算・検証・保存資料|
|**合計**|**166**|**新規・変更ファイル0件**|

生画像11出現を内容SHAで重複除外すると10枚。床紙が写るものは、既に比較したb559のf2427/f5755の2枚で、別位置の独立基準が新たに増えたわけではない。AVI/MP4/MKV/MOV/WebM/MJPEG等の動画メンバーは0件。

`floor_reference_df33e833_r01` や `floor_df33e833_multidistance_r01` という名前でも、提出内容はモデル・参照先JSON・集計結果で、参照先の元画像/録画が同梱されているわけではなかった。元データの**パスが記載されていること**と、**元データ本体が入っていること**を区別した。

|アーカイブ（拡張子tar.xz省略）|通常ファイル|既存内容と一致|
|---|---:|---:|
|floor_reference_9b7d9a17_r01|13|13|
|fixed_floor_display_roi_fix_r01|13|13|
|floor_comparison_live_tail_r01|8|8|
|floor_reference_b559e424_r01|12|12|
|upper_support_capture_analysis_r01|14|14|
|floor_support_final_audit_r01|15|15|
|upper_support_live_r01|10|10|
|upper_support_comparator_r01|7|7|
|report_assets|7|7|
|floor_df33e833_multidistance_r01|8|8|
|floor_df33e833_diagnosis_r01|11|11|
|floor_reference_df33e833_r01|22|22|
|floor_comparison_df33e833_live_r01|8|8|
|upper_support_capture_r01|18|18|

## 次に必要なものの判断

今回の14アーカイブで、手元の保存情報の棚卸しは完了した。この提出分からは、同じ紙の4隅を再調整する以外の新しい物理情報は得られなかった。既存推定の約2cmの一致を精度保証へ引き上げたり、校正を自動採用したりする根拠は増えていない。

学校PCの別の `recordings` 保存先まで直接検査したわけではないため、他所の元動画の不存在を断定しない。ただし**今回が残存データの全てなら、次は不足に限定した床基準の追加撮影が必要**。目的は同条件の録画量を増やすことではなく、小さな紙の角・床姿勢の曖昧さを減らし、校正用と独立確認用の情報を分けて取得すること。新規撮影・機体起動は今回行っていない。

## 根拠と検証

- [archive_summary.csv](complete_batch_r01/archive_summary.csv)：14本のSHA、添付記載回数、通常ファイル数、一致数。
- [archive_members.csv](complete_batch_r01/archive_members.csv)：全166メンバーのSHA、サイズ、既存対応パス、画像用途。
- [summary.json](complete_batch_r01/summary.json)：入力・比較先の前後不変、重複、全件一致、画像役割を記録。
- 生コピーの出典は既存 `Experimental_results/2026-11-04/report_assets/README.md`、frame35562の元PNGとのSHAで照合。解析図の一部は元の生成スクリプトの `savefig` 出力先も確認した。
- 関連の合成8テストで検査関数の非展開、安全パス、バイト差分、重複メンバー拒否、画像分類、再送件数、別名の生コピーのSHA照合を検証。liveコードは変更せず、無関係な回帰・実機試験は再実行しない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-09/archive_reference_intake_r01/inspect_complete_batch.py \
  --output-dir Experimental_results/2026-11-09/archive_reference_intake_r01/complete_batch_repeat_r01

OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  -m unittest discover -s tests -p test_archive_reference_intake.py -v
```

出力は新規フォルダを指定。Downloadsの14アーカイブと、Git外 `recordings` の既存比較先が必要。元アーカイブをGitへ追加せず、Git commit/pushも実施していない。
