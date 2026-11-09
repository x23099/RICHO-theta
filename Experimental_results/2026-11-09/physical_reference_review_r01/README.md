# 既存6画像の物理対応レビュー（2026-11-09）

## 今回進めたこと

前回の幾何・距離・支持点監査は完了しているが、紙の物理四隅と台座手前辺の可視範囲を自動閾値の結果だけで正解とはできない。今回はそれを人が元画像で確認し、座標だけを別JSONへ記録する道具と、既存6枚の確認キューを準備した。

**更新：ユーザーの確認が完了し、6枚すべてreviewed、pending/unclearは0件。** `prepared_r01/decisions/` の明示的な人のクリックを検査し、[reviewed_report_r01/summary.json](reviewed_report_r01/summary.json) に集計した。紙の辺対応は2枚ともunknownのまま保持している。

紙角・台座辺を分けた再計算は [reviewed_coordinate_audit_r01](../reviewed_coordinate_audit_r01/README.md) に保存。床モデルのlive採用、支持点の実装、GUI、ROS/FFB、実行時設定は変更なし。Git commit/pushは今回依頼されておらず実施していない。

準備直後は6枚ともpendingだった。その履歴を `pending_report_r01/` に保存しているが、現在の未確認件数ではない。以下のGUI手順は再レビュー用の参考で、今回は再実行不要。

## 対象

|順|対象|session / frame|確認するもの|
|---|---|---|---|
|1|最新の紙|b559e424 / 5755|白い紙の外周4隅。床の反射、黒い板、印刷格子との区別|
|2|前の紙|df33e833 / 2292|同じ物体でも別frameとして4隅を独立に確認|
|3|コーンの保留例|b559e424 / 32654|台座の車体側の辺の左右端|
|4|コーンの回復例|b559e424 / 35562|同じ辺の左右端を、アルゴリズムの点を見ずに確認|
|5|前の近距離コーン|df33e833 / 61948|台座手前辺の左右端|
|6|前の遠距離コーン|df33e833 / 64232|縮んだ辺の両端を判別できるか。不明ならunclear|

`spec.json` と `prepared_r01/queue.json` に元ファイルへの相対パス・SHA256・session/frameを固定。6枚とも既存の1280×720生PNGで、ファイルのコピーや再保存を増やしていない。

画像の目視では、最新紙は反射と接する左上境界、台座は下辺と床・反射の境界が特に曖昧。前回の自動抽出と同じ座標を人の正解として転記しないため、レビュー画面には自動候補・推定距離を出さない。

## このPCで行うこと（録画・GPU・カメラ不要）

robo25 PCの通常のデスクトップ端末から実行する。学校のmatunuc/GPU PCへ移る必要はない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
MPLCONFIGDIR=/tmp/theta_physical_review_mpl \
  /home/robo25/theta-env/bin/python3 src/review_physical_reference.py review \
  --queue Experimental_results/2026-11-09/physical_reference_review_r01/prepared_r01/queue.json \
  --decisions-dir Experimental_results/2026-11-09/physical_reference_review_r01/prepared_r01/decisions \
  --reviewer human_local
```

画面が1枚ずつ開く。ホイールを対象物の上で回すと表示だけを拡大できる。拡大しても元解像度にない情報は増えない。

1. 紙2枚では、**白い紙の外周の左上→右上→右下→左下**を左クリックする。黒い支持板の角や格子の角ではない。
2. 紙の最初の2点を結ぶ辺が296mmと確実に分かれば `W`、210mmと確実に分かれば `D`。分からなければ初期値unknownのままでよい（`A`でunknownへ戻せる）。見かけの横長だけで決めつけない。
3. コーン4枚では、**同じ台座手前辺の左端→右端**を2点クリックする。台座全体のbbox、床の反射、コーン胴体の端を選ばない。実空間の中央点を画面の平均位置から作らない。
4. 選択が見える箇所だと判断できれば `Y` で確定・次へ。**判別できなければ `U`** でunclearを保存して次へ。unclearには推測座標を残さない。

|操作|意味|
|---|---|
|ホイール|表示だけを拡大/縮小。保存座標は常に元1280×720の座標|
|H|全体表示へ戻す|
|Backspace / Delete|最後の選択を取消し|
|R|現在画像の選択を全取消し|
|Y|必要点数を検査してreviewedを別JSONへ保存|
|U|判別不能として保存。途中の推測点は破棄|
|N|今回は飛ばす。pendingのまま|
|Q|途中終了。既に保存した結果は保持|

画面上の水色の選択印は一時表示だけ。画像ファイルを保存する機能・保存ボタンは用意していない。元PNGは読取り専用として扱い、前後でSHAを照合する。

保存先は `prepared_r01/decisions/<item_id>.json`。途中終了後に同じコマンドを起動すると保存済み画像を飛ばす。既存決定を変更する場合は別の `--decisions-dir` を指定し、以前の記録を消したり上書きしたりしない。

このPCで確認した場合は、終了後に「確認しました」と伝えれば保存JSONをこちらで読める。追加のスクリーンショットや録画提出は不要。

## レビュー後の集計

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 src/review_physical_reference.py report \
  --queue Experimental_results/2026-11-09/physical_reference_review_r01/prepared_r01/queue.json \
  --decisions-dir Experimental_results/2026-11-09/physical_reference_review_r01/prepared_r01/decisions \
  --output-dir Experimental_results/2026-11-09/physical_reference_review_r01/reviewed_report_r01
```

出力先は新規名が必要。今回の未確認集計は `pending_report_r01/summary.json` に保存したが、それを上書きしない。

- reviewedの紙だけ既存のnative KB4→IPPEで再計算する。辺の対応がunknownなら2対応、各対応の平面解も両方残す。厚さ15mm・外部高さ590mmは従来申告の持越しであり今回の再測定ではない。
- コーンは観測した左右端だけを記録。魚眼像上の線分の中央を物理的中央として距離計算へ流用しない。
- pending/unclearの画像に数値を補完しない。人の目視も独立測量による真値や床接触の証明ではない。
- prepared_floor.jsonは生成せず、既存モデルの置換やlive採用は行わない。

人の確認後、紙角と旧自動座標の差、台座の可視辺と旧支持点の位置関係を比較する。画像で分からない物理対応だけが残った場合に、その不足だけを相談する。自動的な追加撮影依頼や安全条件緩和へは進まない。

## 実装・検証

- 新規 `src/review_physical_reference.py`。既存のPNG/session/frame検査 `derive_fixed_floor_live_bundle.source` と平面解算器を再利用。
- 点はnative左レンズ範囲、有限値、必要点数、凸な紙4隅の順序、左→右の辺を検査。画像SHA/queue SHA違い、非表示の権限フラグ、変更済み記録への上書き、未知の決定ファイルを拒否。
- [verification_r02/verification.json](verification_r02/verification.json): **準備時点の45テスト成功**（新規16＋関連既存29）、失敗/エラー/skip0。既存435試験は対象SHA不変を照合し再利用。当時、元画像6枚とキューSHAが不変で、人の確認記録がまだないことを検査した履歴である。人の確認完了後の検証は [新しい66テストの記録](../reviewed_coordinate_audit_r01/verification_r01/verification.json) を参照。
- [gui_smoke_r01.json](gui_smoke_r01.json): 合成画像2枚の隔離仮想画面で、拡大後のnative座標、点不足の拒否、紙の辺対応、unclear時の推測点破棄、画像出力なしを確認。**この合成試験自体は実画像の人の確認を行っていない。** その後ユーザーが行った6件の確認とは区別する。
- 仮想画面の初回は実行環境の表示接続制限で開始できず、隔離Xvfbで再実行。合成結果保存時のNumPy bool変換も修正し、成功記録だけを正式結果とした。実画像やlive処理の障害ではない。
- この環境ではMatplotlib既定がAggのため、レビュー時のみTkAgg（または `--backend QtAgg`）を明示する。グラフ/集計とGUIの起動を分離した。通常のGUI端末で起動し、SSHの画面転送なし端末では起動しない。

このフォルダの `verify.py` は「実画像の人の確認前」という準備時点専用であり、確認完了後には再実行しない。現在の再検証は `../reviewed_coordinate_audit_r01/verify.py --output-dir <新規出力先>`。GUI合成試験は `xvfb-run -a .../gui_smoke.py --output <新規JSON>` で、実際の人の確認キューには書き込まない。
