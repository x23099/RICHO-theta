# GPU PCの録画後比較結果を照合

2026-11-10。提出 `guarded_comparison_171250_r01.tar.xz` を、[このPCの検証済み結果](../guarded_comparison_log_r01/recorded_run_r01/comparison_summary.json)と照合し、**一致を確認した**。GPU PCで同じ録画後比較を実行する手順は完了。同じ操作の繰返しや追加撮影は不要。

## 結果

[機械可読の監査結果](results_r01/audit.json)。提出archiveにはsummaryと比較JSONLの2ファイルだけがあり、リンク・余分なmemberなし。パスを指定しての自動展開はせず、許可したmemberを読み取った。

|確認|結果|
|---|---:|
|job終了|`state=complete`|
|比較JSONL|このPCとバイト単位で一致、記載SHAとも一致|
|元判定の再現|8／8件|
|入力ファイルの記録SHA|23／23一致、対応するこのPCの実ファイルも再hash一致|
|解析コードの記録SHA|8／8一致、対応するこのPCの実ファイルも再hash一致|
|保存画像・元ログの照合記録|8／8、このPCの記録と一致|
|比較候補の数値|frame14922、1.142471541888944 m、支持点[312,407]|
|その他7画像|比較でも保留|

sessionは `4c34c8c3d6d44949afb2e921e819e563`、参照はframe14604。参照より前の6画像の `reference_used_posthoc=true` も一致。summaryはPC固有パス以外すべて同じ。入力はログ／証拠／実装／参照の明示roleに分けて対応し、同名ファイルの曖昧な突合せをしていない。

GPU PCそのものやmetadataに書かれたリモートパスへアクセスしたわけではない。**提出成果物の一致と、同じ解析依存コードの実行記録を確認した**のであり、GPU PC全体のGit状態、Python環境全体、別の終了待ち修正の反映まで証明するものではない。

## 意味と次段階

- これは保存済み8画像の**録画後再計算の再現確認**。改良候補のリアルタイム表示への組込み・性能確認ではない。
- 数値1件は条件付き候補で、独立した実測精度・床接地の認定ではない。主表示、操縦、ROS、FFBには適用していない。
- 次は既存運転画面の主測距を維持し、比較候補を別出力としてリアルタイムに扱う設計・接続検証。その際の同session参照の取扱いと失効条件を先に定める。今回の参照を新sessionへ自動転用しない。新しい撮影を開始条件にせず、既存データ・模擬入力から進める。

## 保管・再現

提出2ファイルはraw扱いで、Git対象外の `recordings/2026-11-10/guarded_gpu_result_intake_r01/` にそのまま保管。元archiveはDownloadsに保持。画像は生成・加工していない。

[監査スクリプト](audit.py)は標準ライブラリのみで、リモートパスを開かず、入力を変更しない。出力先は新規必須。再確認時は末尾を未使用の名前に変更する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
python3 Experimental_results/2026-11-10/guarded_gpu_result_audit_r01/audit.py \
  --archive /home/robo25/Downloads/guarded_comparison_171250_r01.tar.xz \
  --intake-dir recordings/2026-11-10/guarded_gpu_result_intake_r02 \
  --output-dir Experimental_results/2026-11-10/guarded_gpu_result_audit_r01/results_r02
```

実提出物による監査を実行しPASS。測距runtimeは変更していないため、同一hashで成功済みの解析24テストは再利用し、再実行していない。別作業の `src/collision_risk.py` 変更は保持・対象外。Git commit/push、実機操作は本確認では行っていない。
