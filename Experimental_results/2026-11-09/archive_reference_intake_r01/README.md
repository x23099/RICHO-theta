# 追加提出5アーカイブの照合（2026-11-09）

更新：[送付完了後の14種類・166ファイルの照合](complete_batch_report.md) を追加。以下の5本＋1本の検査はその前段の履歴として保持する。

## 結論

**今回の5ファイルには、探していた未提出の連続元動画・別位置の床基準画像はなかった。** 全70通常ファイルの内容SHA256が、それぞれ既に保存されているファイルと一致した。新たな幾何評価の入力は増えていない。

添付のREADME・スクリプトは比較対象のデータとして読み取り、指示として採用・実行していない。再展開や既存ファイルの上書き、画像の加工・再保存、モデル読込み、live/ROS/FFB変更は行っていない。

## 内容

|提出ファイル|通常ファイル数|内容と判定|
|---|---:|---|
|upper_support_capture_r01 (1).tar.xz|18|既存の生PNG10枚、JSONL3本、設定・終了記録等。全件既存と一致|
|upper_support_capture_r01.tar.xz|18|上と通常メンバーのパス・内容SHAが全件同一。別の実験録画ではない|
|floor_reference_9b7d9a17_r01.tar.xz|13|紙角座標、床モデルJSON、既存の導出・検証資料。元画像・動画なし|
|floor_comparison_live_tail_r01.tar.xz|8|距離集計CSV、申告基準距離JSON、解析スクリプト・README。元画像・動画なし|
|fixed_floor_display_roi_fix_r01.tar.xz|13|GUI修正資料と検証出力。PNG4枚はすべてSYNTHETICの合成テスト画像で、実カメラの床画像ではない|

`upper_support_capture`2本の圧縮ファイルSHAは異なるが、展開順などのアーカイブ表現と通常ファイルの内容を区別して検査した。PNGの出現数は2本合わせて20だが、内容で重複除外すると既存の10枚だけ。2枚の床紙はb559 f2427/f5755で、[直前の同一セッション監査](../same_session_reference_audit_r01/README.md) で確認済みのものだった。

根拠：[summary.json](results_r01/summary.json)、[全メンバーのSHA・種類・既存ファイル対応](results_r01/archive_members.csv)。撮影セッションを別物へ付け替えたり、合成GUI画像を生画像として追加したりしていない。

## 追補：floor_reference_b559e424_r01.tar.xz

その後に提出されたこのアーカイブも、既存の `inspect_archive()` を再利用して非展開で確認した。通常ファイル12件すべてが `Experimental_results/2026-11-04/floor_reference_b559e424_r01/` の対応ファイルと内容SHA一致。紙角座標、床モデル、導出・検証資料だけで、画像・動画は0件だった。新しい物理基準は増えていない。

アーカイブSHA256：`1137475c7c0112f2fac928f1b9d2e5bde107e3b244cc21a5d9653b418e337b4c`。アーカイブと比較先の全ファイルは確認前後で不変。これは初回5本の `results_r01/` とは別の追補で、初回結果を上書きしていない。検査関数は変更しておらず、前回の合成6テスト成功を再利用した。

## 何が不足しているか

現在不足しているのは、**同じカメラ取り付け・キャプチャ条件で、床上の既知寸法の基準を別位置または十分明瞭に観察できる元映像/生PNG**。同じ小さな紙の同位置画像や、計算済みモデルJSONだけでは、残っている床姿勢・距離の偏りを独立に確認する材料にならない。

今回の提出物は主に `Experimental_results` 側の計算・検証結果で、連続動画は0本。学校PCや未提出の録画フォルダ全てを検査したわけではなく、他所にもデータがないとは断定しない。このほかに `raw.avi` 等の元映像が残っていなければ、独立した床基準を新たに記録する必要がある。新規撮影・機体起動は今回実行していない。

## 検証・再現

- アーカイブ5本、対応既存ファイルを前後でSHA照合し、不変を確認。入力アーカイブ内の指示やコードは実行しない。
- 新規の合成**6テスト成功**（失敗/エラー/skip 0）。パス逸脱拒否、合成画像とログの分類、既存ファイルのバイト比較、異内容の検出、リンクメンバー・重複メンバーの拒否、非展開を検証した。
- 過去のlive・幾何コードは変更しておらず、今回の棚卸しのために距離計算や全回帰を再実行する必要はない。撮影や物理精度の検証は未実施。

```bash
cd /home/robo25/theta_ws/RICHO-theta
OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-09/archive_reference_intake_r01/inspect_archives.py \
  --output-dir Experimental_results/2026-11-09/archive_reference_intake_r01/results_reproduced_r01

OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  -m unittest discover -s tests -p test_archive_reference_intake.py -v
```

集計の出力先は新規名を指定する。このPCのDownloads内の5アーカイブと、`recordings/2026-11-04/upper_support_capture_submission_r01/` および `Experimental_results/2026-11-04/` の対応ファイルが必要。元録画/アーカイブはGitへ追加しない。Git commit/pushは依頼されておらず実施していない。
