# v12過去録画の遮蔽探索・固定候補の復帰確認

2026-10-06、追加録画なしのオフライン診断。実機駆動、ROS送信、本番設定・校正・FFB強度の変更は行っていない。

## 結論

9/29のv12 dry-run／hardware UNKNOWN録画を確認した。選定した**72件の目視点（うち42 frameは連続区間の全frame）**では、完全遮蔽と確認できたのはdry-runのframe 763～764だけだった。最初と最後のタイムスタンプ差は0.035808秒で、より長い完全遮蔽の評価材料は今回の確認範囲では確保できていない。

完全遮蔽2 frameでは固定3方式とも検出・測定採用0。対象が再び遮られずに見えるframe 773では3方式とも測定を採用した。ただし、その時点を基準にした待ち時間0は「物理系の復帰遅延0」を意味しない。実際には部分遮蔽中のbaseline frame 771、S130候補 frame 770から既に採用を再開している。

重要な制約として、完全遮蔽2 frameの記録ODOMは**速度0.0 m/s**、再計算衝突状態はCLEARである。したがって、この短い区間を接近中の完全遮蔽→UNKNOWN通知の試験として流用できない。既存の[hardware UNKNOWN出力PASS](../../2026-09-29/phase5_v12_hardware_unknown_r01_diagnosis.md)は、測定無効→単発通知→実機出力の試験であり、完全遮蔽の画像正解付き検出精度試験とは別である。その判定は上書きしていない。

## 入力・目視の範囲

| session略称 | 原本archive | 全動画frame |
|---|---|---:|
| dry | `rokuga_phase5_v12_reliability_dryrun_r01_20260929_162234_202.tar.xz` | 1,045 |
| hardware | `rokuga_phase5_v12_hardware_unknown_r01_20260929_184546_956.tar.xz` | 1,301 |

原本は`/home/robo25/Downloads/`。session名はarchive名の先頭`rokuga_`を除いたもの。archive SHAは`review_protocol.json`、動画／detections.csv／metadataと実装のSHAは`video_comparison/provenance.json`に記録した。

1. dryの16点、hardwareの17点を全画角の画像で疎に確認した。UNKNOWN近傍、遮蔽中、録画後半の復帰も対象にした。
2. dryのframe 410～430と760～780、各21 frameを全frame確認した。微小な縁の判断と、板を持ち上げる復帰を確かめた。
3. 重複3点を除いた72点の目視分類を`manual_review.csv`へ保存し、検出再計算の前にSHAを固定した。
4. 疎なサンプルの間は**未レビュー**であり、サンプルから区間全体のラベルを補間していない。hardwareの全遮蔽区間をレビュー済みとはしていない。

| session | 可視 | 部分遮蔽 | 完全遮蔽 | 判定不能 | 目視計 |
|---|---:|---:|---:|---:|---:|
| dry | 13 | 34 | 2 | 6 | 55 |
| hardware | 4 | 13 | 0 | 0 | 17 |
| 合計 | 17 | 47 | 2 | 6 | 72 |

部分遮蔽では板の上・右・下に箱の面や縁が残る。判定不能は手や板の境界の微小部分を断定できないframeで、完全遮蔽の分母に含めない。完全遮蔽の開始・終了時刻も、前後の判定不能frameを含めて断定していない。

## 比較条件・結果

`baseline`、`seeded_s130_nearest`、`seeded_s130_bottom`の3方式。候補コード・条件は[先行候補](../box_contact_candidates/provenance.json)から固定し、`--freeze-from`で一致を確認した。検出器条件はv12設定、幾何・校正・測定ゲート・追跡・ODOMは各録画の条件を使用した。全動画を冒頭から順に処理し、選定区間で追跡器を初期化していない。

全2,346 frame × 3方式 = 7,038比較行。目視結合は72点 × 3方式 = 216行。

以下の2数値は「検出frame数／測定採用frame数」。疎な目視点も含む記述的な件数で、区間の割合・継続時間や独立holdoutの精度ではない。

| session | 方式 | 可視 | 部分遮蔽 | 完全遮蔽 | 判定不能 |
|---|---|---:|---:|---:|---:|
| dry | baseline | 13 / 13 | 4 / 2 | 0 / 0 | 0 / 0 |
| dry | S130 nearest | 13 / 13 | 5 / 4 | 0 / 0 | 0 / 0 |
| dry | S130 bottom | 13 / 13 | 5 / 4 | 0 / 0 | 0 / 0 |
| hardware | baseline | 4 / 4 | 0 / 0 | 未評価 | 未評価 |
| hardware | S130 nearest | 4 / 4 | 2 / 1 | 未評価 | 未評価 |
| hardware | S130 bottom | 4 / 4 | 2 / 1 | 未評価 | 未評価 |

hardwareには目視で確定した完全遮蔽がないため、完全遮蔽性能の数値はnull／`NOT_EVALUATED`で保存した。0件の目視対象を「誤検出0でPASS」とはしていない。

復帰区間では、板の下から箱が現れるframe 765～772を部分遮蔽、773～780を可視と目視分類した。最初の測定再採用はbaseline 771、S130両候補770で、1 frameの差があった。これはこの映像の観測結果であり、普遍的な復帰速度の優位性ではない。部分遮蔽で採用した測定の物理距離の正解も付いていない。

完全遮蔽2 frameでは追跡位置も存在しなかったが、既に先行する部分遮蔽・判定不能で測定が失効している。この2 frameだけから追跡失効までの時間は計算しない。UNKNOWNには有効測定、前進条件、WARNING hold、再arm等も影響するため、「見えない」と「UNKNOWN通知」を同一ラベルにしない。

## 保存物・検証

- `manual_review.csv`、`review_protocol.json`: 比較前に固定した目視点、疎な確認と連続レビューの区別。
- `video_comparison/`: 全7,038行の再計算、条件と入力・実装SHA。
- `reviewed_frames.csv`: 216行。目視分類、source frame/index/time、元動画／全画素SHA、追跡・衝突状態。
- `phase_metrics.csv`: session・方式・確認範囲別の集計。未評価はnull。
- `visible_recovery_metrics.csv`: 可視復帰773と採用再開770／771の関係。完全遮蔽の復帰遅延評価とは別。
- `review_summary.json`: 件数、速度0の制約、入力／出力SHA、長い完全遮蔽の未評価。
- `review_coverage.png`: 目視点の分類数。区間時間を示すグラフではない。
- `continuous_window_recovery.png`: 全frame確認した2区間の見え方と固定3方式の検出・測定採否。
- `raw_assets_manifest.csv`: 無加工のdry frame 763とhardware frame 900の対応・時刻・hash。
- `export_review_frames.py`、`create_review_artifacts.py`: 全画角PNGの準備と集計・グラフ・代表画像再生成。目視判断は自動生成しない。

72点すべてについて目視PNGと元動画の順次decode結果を全画素照合した。代表PNGも元解像度1280×720のまま保存し、切り抜き・注釈・補正・リサイズなし。全frameの3方式対応・source時刻一致・source動画/CSV/metadata SHA・候補固定・採用時の検出ありをチェックした。構文チェック、成果物hash検証、`git diff --check`も実施した。本番ソースの追加変更はなく、直前に成功した全316 unittestの結果を再利用した。

## 再現

展開済みsessionパスを指定して`src/compare_offline_box_contacts.py`を実行する。`--input`を2つ、検出器設定を`src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`、`--variants baseline seeded_s130_nearest seeded_s130_bottom`、`--freeze-from Experimental_results/2026-10-06/box_contact_candidates/provenance.json`、出力を本フォルダの`video_comparison`へ指定する。

目視証拠PNGの相対パスとframeは`manual_review.csv`に記録した。`export_review_frames.py --session-dir /path/to/session --output-dir /path/to/export-root/screen_v12 --prefix dry --frames 350 367 ...`のように全画角PNGを準備する。連続レビュー42点は`review_v12_dense`へ出力する。必要な疎なframe一覧と連続区間は`review_protocol.json`に固定されている。

```bash
python3 Experimental_results/2026-10-06/v12_occlusion_screening/create_review_artifacts.py \
  --session-dir /path/to/phase5_v12_reliability_dryrun_r01_20260929_162234_202 \
  --session-dir /path/to/phase5_v12_hardware_unknown_r01_20260929_184546_956 \
  --export-root /path/to/export-root
```

## 残る評価条件

長い完全遮蔽での候補安全性は未評価のまま。本番採用・強度引き上げの根拠にはしない。残る画像正解付きの条件は、箱が有効に見えている状態から、前進ODOMが続く間に2～3秒完全に隠し、箱を再び見せる一連の区間である。板の上・左右・下に箱の縁が残らないことをraw動画で確認し、測定失効、UNKNOWN、復帰を別々に評価する必要がある。

現時点で録画全体の全frameを検査して不存在を証明したわけではない。ただし、既存UNKNOWN記録を完全遮蔽試験とみなすだけでは、この不足を埋められない。実験で補う場合もKobukiを停止した模擬ODOM＋dry-runからでよく、今回の解析から新たな実機駆動を実行するものではない。
