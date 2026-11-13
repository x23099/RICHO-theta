# 表示専用の自己遮蔽ゲート：実GPU・静止run全体監査

2026-11-13 JST。提出 `body_guard_static_r01_full.tar.xz` の必要16ファイルは完備。追加提出は不要。
**新ゲートONの静止時の連続処理・同一フレーム受渡し・数値復帰・正常終了を記録上確認できた。自己遮蔽による表示保留の実機確認は今回まだ成立していない。**

実行コード・閾値・校正・GPU環境は変更せず、保存データだけを解析した。カメラ／CUDA／ROS／機体はこのPCから起動していない。

## 提出物と照合

- 元データ：`recordings/2026-11-13/body_display_static_full_intake_r01/{primary,comparison}/`。Git対象外、画像を含め原本バイトは変更していない。
- 元primaryは `Experimental_results/2026-11-13/driver_body_guard_static_r01`、comparisonは `recordings/2026-11-13/body_guard_static_r01`。
- session `e011664e9b994ce1b070439efa875b6a`、pin361。元PNGの1280×720画素／PNG SHA／復号BGR SHA／sidecar／status／主JSONLの完全な元行SHAが一致。先行4点提出のPNG・sidecar・engine summaryとも同一。
- 発行参照：[reference.json](../body_display_reference_static_r01/reference.json) と提出参照がバイト一致。SHA `f93f4bd8e0c40fb4b6ee9e1fa3695520adc241d26c093ffca6e51334727a20d4`。
- 比較側9コード＋新表示側7コードの記録SHAを照合し、重複除外12コードがローカルと一致。profile／configの実ファイルSHAと記録重みSHAを照合。重み本体は提出されておらず再ハッシュしていない。
- 主測距・別表示レビュー・bridgeイベントは各28,369行。同session/frame/source時刻／元数値／レビューの完全コピーが全件一致。比較28,367行も元主行へ対応した。
- 参照が結ばれた表示3,711件について、**元ログの現在支持列**と発行した天板境界から自己遮蔽判定を再計算し、全件 `clear_of_reviewed_local_body_boundary_NOT_floor_contact` と一致。元画像の全フレームやYOLOを再計算したものではない。

原本・監査コードのSHA一覧と集計は [audit.json](results_r01/audit.json)、全主フレーム対応の根拠は [display_timing.csv](results_r01/display_timing.csv)。

## 区間と結果

`post_load` は比較側で初めて参照scopeが有効になったframe24754から最終frame28485までを固定した区間。ロード要求の発行時刻そのものではない。表示ゲートの初回参照有効はframe24756。終盤30秒も最終source時刻から機械的に選び、数値の出た部分だけを選別していない。

| 項目 | 参照有効化開始後 | 終盤固定30秒 |
|---|---:|---:|
| frame | 24754〜28485 | 27586〜28485 |
| 対応主結果 | 3,732 | 900 |
| source時間幅 | 124.405秒 | 29.966秒 |
| 処理結果間隔の平均 | 29.991件/秒 | 30.000件/秒 |
| 元測距が数値 | 3,713 | 881 |
| 表示ゲートが数値を許可 | 3,711 | 881 |
| 元測距自体の保留 | 19 | 19 |
| 元は数値・表示側のみ保留 | 2 | 0 |
| 元保留から表示数値への救済 | 0 | 0 |
| 表示数値と元値の完全一致 | 3,711 / 3,711 | 881 / 881 |
| 主完了age P95 / 最大 | 18.29 / 45.36ms | 18.20 / 25.23ms |
| 表示レビュー完了age P95 / 最大 | 18.73 / 45.98ms | 18.61 / 26.11ms |
| 主完了→レビュー完了 P50 / P95 / 最大 | 0.40 / 0.55 / 1.22ms | 0.41 / 0.52 / 1.04ms |
| 別比較service P95 | 5.15ms | 5.05ms |
| レビュー完了ageが33.33ms超 | 3件 | 0件 |

許可された3,711件は全件bridgeでも受理された。値の範囲は約1.4375〜1.4442m。**これは元値保持と静止変動幅であり、独立実測に対する誤差ではない。**

`主完了→レビュー完了` は比較offer・参照取得・レビュー等を含む経過時間で、ゲート関数の専有CPU時間ではない。主ログのageにはこの部分が入らないため別集計した。いずれも受信source基準であり、露光→送信→GUI描画の総遅延ではない。処理件数も全画面の描画回数を保証しない。

### 保留を分離する

- 読み込み前：主24,637件／約825秒。主数値24,456件にも表示数値へのフォールバックはなく、参照未取得の保留を維持。初回の古い入力1件も表示保留＋bridge退役。長い待機を含む全体表示率を、読み込み後の失敗率に混ぜない。
- 有効化境界：frame24754は `display_body_reference_unavailable`、24755は `display_body_reference_not_current`、24756から数値許可。別比較も最初の2件は `comparison_waiting_for_post_activation_frame`。最初の2件の待機後、同種の保留は再発していない。非同期処理の内部ロックのどの瞬間だったかまではログから断定しない。
- 終盤のframe28276〜28294（連続19件）は **元測距側の `ambiguous_upper_body_colour`**。主・表示・別比較とも保留。新ゲートが別の数値に救済せず、その後再び数値へ復帰。各瞬間の元画素は未保存のため、曖昧判定の物理原因は断定しない。
- `possible_self_body_occlusion` は今回0件。遮蔽のない静止状態で数値を不必要に棄却しなかったことは確認できたが、**近接遮蔽時の新しい主表示が実機でWITHHELDへ切り替わる証拠はまだない**。以前の走行ログの後解析や合成テストとは区別する。

## 終了・欠落の会計

主sent／returnedは各28,369、bridge受理28,368＋初回退役1。主入力tap_lock_drops=3は比較側のdropとは別。
比較offered28,369／processed28,367、latest_slot_overwrites=1／tap_busy_drops=0。差2件はslot上書き1＋終了時未処理1と整合する（未処理を成功件数には含めない）。

主／I/Oはshutdown_complete=true、child_stopped=true、worker_error／shutdown_error=null、強制killなし。child_exitcode=-15はSIGTERMで、これだけを異常終了と解釈しない。終了待ち約63.53ms。
比較はstate=closed、writer_done=true、shutdown_complete=true、error=null。JSONLの未完行・混在session・重複対応は検出しなかった。

## 限界と次段階

今回の静止確認は完了。同じデータの再提出・旧パッチ適用・もう一度の静止待機は不要。
ユーザー提示の画面下部 `body-review gen 1` は新ラベルの表示と整合するが、別frameのstatusと完全な同時刻対応にはせず、全GUI描画の証拠にも拡張しない。

次は **元数値保持→台座が天板で隠れたときの表示保留→見える位置での復帰** を新ゲートONで確認する段階。
まず車体を停止したまま現地でコーンを移動して表示切替を確かめる方法がある。実施手順は別途提示し、この解析だけで走行・接近を開始しない。
今回の受信は終了済みなので、再開するなら新しい保存先／新接続のpinと参照が必要。旧pin361参照をsessionだけ書き換えて使わない。

物理距離精度・床接地・カメラ取付再現・床姿勢は未認定。数値はカメラ直下基準の水平距離の診断値で、base_link距離・車体接触距離ではない。固定取付＋平面床の仮定と、傾斜補償なしを維持し、ROS／操縦／FFB／自動停止への使用はしていない。

## 再現とテスト

新しい空の保存先を使う（既存データを上書きしない）：

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/body_display_static_live_audit_r01/review.py \
  --archive /home/robo25/Downloads/body_guard_static_r01_full.tar.xz \
  --intake-dir recordings/2026-11-13/body_display_static_full_intake_r02 \
  --output-dir Experimental_results/2026-11-13/body_display_static_live_audit_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_body_display_static_live_audit.py \
  tests/test_driver_body_display_guard.py \
  tests/test_report_driver_motion_logs.py
```

新監査7件＋既存関連を含め37テスト成功。境界付き16ファイル抽出、重複／パストラバーサル／リンク／不足／既存保存先拒否、元値変更／数値救済／権限変更／別参照／bridgeレビュー不一致／古い数値を拒否する検証。既存ゲートの合成・ローカルpipe試験は実GPUの負荷測定とは分ける。日報・commit・pushは今回依頼されておらず実施していない。
