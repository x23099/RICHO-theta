# GPU PCでの非同期比較・保存データ再生を確認

2026-11-11。提出 `guarded_gpu_cached_r01.tar.xz` を監査し、**GPU PCでも保存画像8枚の比較OFF/ONで主判定が一致し、子プロセス・I/O・比較writerの終了記録が整合することを確認した。** 同じ再生を繰り返す必要はない。現在はこのPCとGPU PCのみ使用可能で、matunucは使用できないとの回答済み。

[正式監査JSON](results_r01/audit.json)、[監査スクリプト](audit.py)。archiveは15 regular filesと3 directoriesのみ。余分なmember、リンク、特殊ファイル、親パス参照を許可せず、上限内で読み取った。提出ファイルは実行していない。

|確認|結果|
|---|---:|
|主測距ログの独立照合|OFF/ON各8行、計16行|
|主測距の観測・model・判定・未承認flag|このPCの検証結果と全件一致|
|OFF/ON間の主判定|8／8一致（今回の元8枚は全て輪郭境界保留）|
|bridge eventの主結果・採用との対応|16／16行|
|入力の記録SHA|23／23一致、対応するローカル実ファイルも再hash一致|
|解析依存の記録SHA|重複除去13ファイル一致、現在のローカル実装とも一致|
|OFF/ON子プロセス・I/O停止|両方完了、worker errorなし、強制killなし|
|比較writerの終了記録|完了、8行処理、snapshot1枚、drop0、errorなし|
|比較の数値記録|1件、1.142471541888944 m、このPCのsummaryと一致|
|pin元の主ログ完全行SHA|ONのframe7と一致、元画像／画素SHAもこのPCの記録と一致|

受信／処理時刻・再生session UUID・PC固有パスは異なるためバイト一致とはしていない。主測距ログはそれらの変動項目を除いた全内容を、このPCの正式実pipe再生と比較した。metadataのリモート絶対パスは開かず、ログ／証拠／参照／設定のroleを明示して入力SHAを対応させた。

### エラーに見える項目の意味

summary内の `FileNotFoundError` は、検証スクリプト終盤でsessionを意図的に `ffffffff...` にした参照をloadする負例試験。対応するPNGが存在せず拒否され、旧数値も消えていることを確認するためのもの。最終`error=null`、`shutdown_complete=true`と矛盾しない。修理のための再実行や追加提出は不要。

OFFの`child_exitcode=-15`はSIGTERMによる停止で、ONは`0`。どちらも所有子とI/Oの停止確認済み。-15だけを推論クラッシュと扱わない。

## 確認範囲と次に残ること

- 実YOLOではなく、同じ元画素に紐付く保存済み検出枠を使う検証モード。**GPU PC上で実行できたことと、CUDA推論・実カメラ負荷を測ったことは別。** `actual_cuda_inference=false`、`actual_camera=false`。
- 今回は主ログ・bridgeログ・summary等が提出され、比較側の`comparison_frames.jsonl`やpin PNG自体はarchiveに含まれない。比較1件と参照loadの結果は、提出summaryと照合済み実装の試験内容との整合確認までで、比較JSONLを直接読んだとはしない。今回お願いしたsummaryを含む提出としては足りており、追加提出は要求しない。
- 物理距離誤差、床接地、姿勢補償、実映像／操縦遅延、実GPU追加負荷は未認定。主表示・制御／ROS／FFBへの比較値適用もない。
- matsunucが使えるまでは、送信・実カメラpinを要求しない。GPU PCでの基本再生確認は今回で完了。カメラなしでさらに行う場合は、保存画像を実YOLOへ通す推論・追加負荷確認を別試験として準備できる。実映像の確認はmatunuc／カメラが使える時に行う。

## 保管と再現

提出物15ファイルは無変更で `recordings/2026-11-11/guarded_gpu_cached_intake_r01/` に保存（Git対象外）。元archiveはDownloadsに保持。現在のコードはユーザー側でcommit `8e5172b`（1111）へ整理され、今回監査開始時のworktreeはcleanだった。過去の「今日の機能は未反映」という説明から、再度パッチ適用を求めない。

再監査する場合は未使用の出力先へ：

```bash
cd /home/robo25/theta_ws/RICHO-theta
python3 Experimental_results/2026-11-11/guarded_gpu_cached_audit_r01/audit.py \
  --archive /home/robo25/Downloads/guarded_gpu_cached_r01.tar.xz \
  --intake-dir recordings/2026-11-11/guarded_gpu_cached_intake_r02 \
  --output-dir Experimental_results/2026-11-11/guarded_gpu_cached_audit_r01/results_r02
```

監査PASS。runtimeコードを変更していないため成功済み198テストは再利用し、繰り返していない。本監査でカメラ・GPU推論・ROS・機体を起動せず、Git commit/pushもしていない。
