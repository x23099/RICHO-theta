# 11/16：全ログと1／1.5／2mの画面3点の照合完了

提出 `body_guard_full_20261116_r01.tar.xz` は必要16ファイルが揃っており、主・表示レビュー・bridge・比較の対応、参照／pin結合、正常終了を確認した。追加の撮影・測定・走行・再pinは不要。
根拠は [audit.json](results_r01/audit.json)、[画面前後の短時間文脈](results_r01/anchor_context.json)、[申告値と画面読取りCSV](../body_display_range_check_r01/observations.csv)。sessionはe52bb32f03d6488ebf37d769f46ec37a、参照pin5186／世代1。

## 画面と同じフレームの照合

| 申告実測 | 画面表示 | 同frameの元主値＝表示許可値 | 画面表示−申告実測 | frame |
|---|---|---|---|---|
| 1.000m | 1.005m | 1.0051490635900895m | +0.005m（+0.5cm） | 34957 |
| 1.500m | 1.480m | 1.4802135948782225m | -0.020m（-2.0cm） | 45469 |
| 2.000m | 1.960m | 1.9595656445966836m | -0.040m（-4.0cm） | 46432 |

3点とも正確なsession/frameに主値・表示許可・bridge受理が対応し、小数第3位への丸めが画面と一致。別比較値もこの3点では元主値と同値。画面のbody-review世代はすべて1。
実測はユーザー申告（カメラ直下床点から台座手前辺中央までの床面直線距離）で、不確かさは未申告。今回画面3点の差最大4cmは、全距離・常時±4cmの保証や正式校正ではない。値に合わせる校正・しきい値変更は行っていない。

各画面frameのsource時刻を中心に±0.5秒を切り出した文脈は次のとおり。

| 画面frame | 周辺ログ件数 | 数値許可件数 | 周辺の数値範囲 |
|---|---|---|---|
| 34957 | 31 | 31 | 1.003940〜1.005149m |
| 45469 | 30 | 30 | 1.480214m（同値） |
| 46432 | 30 | 30 | 1.957462〜1.959566m |

この約1秒の各文脈には保留なし。ただし画像・実測に結び付いた静止時間区間全体の独立証明ではないため、周辺値を全て同一真値への誤差として集計しない。完全画面録画・スクリーンショットの原本ファイルは未提出で、会話添付の画面読取りを元ログへ照合したもの。全GUI描画回数や各画像ファイルのSHAは確認していない。

## 実行系・参照・全体整合

| 項目 | 結果 |
|---|---|
| 保存ファイル | 16点、全原本SHAを保存し取込み後不変を確認 |
| 主ログ／表示レビュー／bridge | 各51,202件、全件のsession/frameとレビューコピー一致 |
| 比較ログ | 51,200件、全件の元値・source時刻が対応する主ログと一致 |
| pin | 初回4点とPNG／sidecar／engine summaryがバイト一致、元PNG/BGRと完全主JSONL元行SHA一致 |
| 発行参照 | SHA 60ebc44adee96cf21195fefb61dc4d988033e157971c764025e8a783f8d3edde、提出referenceとバイト一致 |
| 記録コード | 重複除く12ファイルのSHAをローカルと照合 |
| 設定・profile・記録重みSHA | 一致。checkpoint本体の独立再hashは未実施 |
| 主／比較終了 | 正常、errorなし、forced killなし、child exitcode=0 |

全期間約1,715.494秒の主結果は約29.846件/秒だが、常時30fpsや露光から表示までの遅延を保証するものではない。開始待ち・コーン移動・画面範囲外を含む全期間の保留率を、固定1／1.5／2m地点の精度指標へ混ぜない。

## 参照load後の表示ゲート

比較参照有効化の最初はframe24323、最初の参照付き主数値判定は26696。間の元候補なし等を参照不具合と扱わない。
load後frame24323〜51503／27,073件では、元数値19,324件のうち表示許可19,297件、追加保留27件（possible_self_body_occlusion22、参照範囲外5）。許可19,297件は全件元値と完全同値・bridge受理。元保留からの数値救済0。
参照付き支持列19,324件の自己遮蔽判定を保存支持列から再計算し、clear19,297／遮蔽22／参照範囲外5に全件一致。未保存フレームのYOLO再推論や、22件すべての実際の物理遮蔽を画像で独立確認したものではない。
非同期比較は主表示とは別経路であり、全行の採否件数が同一とは要求しない（load直後や判定の適用範囲が異なる）。今回の主表示が別比較数値へ置き換えられていないことは全件照合した。

| load後の経過時間指標 | 中央値 | P95 | 最大 |
|---|---|---|---|
| source時刻→主完了 | 13.40ms | 18.58ms | 107.65ms |
| source時刻→表示レビュー完了 | 13.72ms | 19.00ms | 108.06ms |
| 主完了→表示レビュー完了 | 0.38ms | 0.51ms | 1.92ms |

追加経過時間はoffer等を含み、関数専有CPU時間ではない。これらは画面のreceive-ageとも同一指標ではなく、カメラ露光→ネットワーク→GUI描画の総遅延ではない。

主sent51,203／returned51,202の差は終了未返却1、bridge退役は古い結果1。比較offered51,202／processed51,200の差は上書き1＋終了未処理1で説明できる。primary tap_lock_drops6と比較tap_busy_drops0は異なる段階のカウンタで混同しない。

## 保存場所と再現

原本・全51,202行の派生timing CSVは `recordings/2026-11-16/body_display_full_intake_r02` に保存しGitへ追加しない。Git側には小さいaudit JSON・観測CSV・再現コードを保存する。
初回r01はログ照合とtiming出力後、派生CSVの相対パス記録時に絶対／相対パス不整合で集計JSON発行が失敗。入力3パスをresolveする局所修正後、新規r02へ取込み直して正式集計に成功した。初回原本やユーザーデータは削除・上書きしていない。r01を正式結果と混同しない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/body_display_range_audit_r01/review.py \
  --archive /home/robo25/Downloads/body_guard_full_20261116_r01.tar.xz \
  --intake-dir recordings/2026-11-16/body_display_full_intake_r03 \
  --output-dir Experimental_results/2026-11-16/body_display_range_audit_r01/results_r02
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/body_display_range_audit_r01/context.py \
  --audit Experimental_results/2026-11-16/body_display_range_audit_r01/results_r02/audit.json \
  --output Experimental_results/2026-11-16/body_display_range_audit_r01/results_r02/anchor_context.json
```

既存静止全ログ監査に発行参照・初回pin原本の明示パス引数だけを追加し、旧11/13の既定値・検証は維持。新しい監査は既存の安全取込み・全行照合・支持列再評価を再利用する。既存実験結果のSHA記録は当時のコード版の履歴なので書き換えない。
検証結果は [verification.json](verification.json)。runtime・距離校正・しきい値・GPU環境・ROS／FFB接続の変更なし。

## 現在の到達点

11/13の走行中表示・自己遮蔽保留・復帰に加え、今回は再取付後の新接続で参照の有効化と前方1／1.5／2mの画面3点を確認できた。確認した条件の診断表示として扱う根拠であり、カメラ直下基準から車体接触距離への変換、動的傾斜補償、取付再現、独立精度保証、制御／FFB用距離としての採用を完了したものではない。
今回の3地点確認は完了。追加の実機操作は現時点で不要。日報・commit/pushは今回未依頼。
