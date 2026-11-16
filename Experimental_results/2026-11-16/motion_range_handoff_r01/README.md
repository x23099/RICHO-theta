# 更新した研究目標に向けた保存ログの距離受け渡し

## 結論

[研究目標](../../../RESEARCH_GOAL.md)を、ユーザー指定の「操舵入力に対するリスク勾配をG923へ抵抗型提示する」計画へ更新した。現在の距離計算は接近情報・リスク評価の入力を準備する中間成果として継続利用する。
その前段として、**保存済み51,202件の距離／保留／時刻／session・frameをJSONで受け渡し、受信側で値と無効状態を維持できることを確認した。** ROS送信・G923実出力・機体操作は行っていない。

正式結果は [results_r02/audit.json](results_r02/audit.json)、画面3点は [point_handoff.csv](results_r02/point_handoff.csv)。r01は初版の成功記録として保持し、現在の受信処理（不正時計でも保持値を消す、受信結果へframe／元時刻を保持）の検証はr02を参照する。

## 実ログ全件の結果

| 項目 | 件数・結果 |
|---|---|
| 変換・JSON往復・受信検証 | 51,202件 |
| 入力検証済み | 51,201件。初回の古い退役結果1件は無効 |
| 数値あり | 19,297件、すべて元表示レビューと完全同値 |
| 距離なし | 31,905件、すべてdistance=null。ゼロ埋め・前値保持なし |
| 自己遮蔽の保留 | 22件、理由と無効状態を維持 |
| 参照範囲外の保留 | 5件、理由と無効状態を維持 |
| 既知画面3点 | frame34957／45469／46432の値・元時刻・frameを維持 |
| 受信停止後の期限切れ | 最後の数値を消し、距離なしにする |

元レビューとの照合条件は `bridge受理 && display_available`。別比較の数値で救済せず、未参照時の元主数値も有効へ昇格しない。初回退役結果の受信側理由はhandoff_sample_staleで、その他の保留は元理由を維持している。

| 画面地点 | 受け渡し前 | 受け渡し後 |
|---|---|---|
| 1m | 1.0051490635900895m | 同値 |
| 1.5m | 1.4802135948782225m | 同値 |
| 2m | 1.9595656445966836m | 同値 |

物理誤差は[先行の3地点監査](../body_display_range_audit_r01/README.md)の扱いを維持し、受け渡し成功を精度認定と混同しない。

## 遅延注入

同じsampleの元時刻は書き換えず、受信評価時刻だけを遅らせた。

| 追加の配送遅延 | 数値あり | 距離なし |
|---|---|---|
| 100ms | 19,297 | 31,905 |
| 400ms | 19,296 | 31,906 |
| 501ms | 0 | 51,202 |

これは現行測距に合わせた**受信元時刻基準の0.5秒期限**のテスト。FFB指令の100ms期限・challenge・watchdogとは別である。100ms追加後に保持できたことを、FFB側の100ms期限に適合した証明とはしない。
実ネットワーク遅延やROS clock同期を測ったものではなく、保存レビュー完了時刻を基準にしたオフライン再生である。

## データ契約と実装

`src/driver_motion_handoff.py` はオフライン専用で、既存実行系からはimportしない。

| フィールド | 意味 |
|---|---|
| schema | offline_motion_range_handoff_v1。ROS／FFB指令とは異なる |
| session／frame／source_time_sec | 元接続・元フレーム・元受信monotonic時刻。別PCの時計・UTC・ROS timeへ暗黙変換しない |
| input_verified | 元結果・表示レビュー・bridge受理・因果性・鮮度の形式検証。物理精度の認定ではない |
| range_available／distance_m | 診断値として現在使える数値／m単位。無効時はfalse／null |
| reason | 元保留理由または受信エラー。無効をCLEAR／距離ゼロへ変換しない |
| reference_* | 明示した参照frame・PNG SHA・世代に対応。受信側でも指定した参照に一致を要求 |
| metric | カメラ直下基準の床面水平距離。base_link／車体接触距離ではない |
| vehicle_xy_m／object_id | いずれもnull。スカラー値から位置や追跡IDを作らない |
| replay_only | 常にtrue。履歴値を新しいライブ観測として公開しない |
| usable_for_ffb等 | 常にfalse。リスク勾配・力覚・ROS出力の権限を付けない |

生成側は既存のchecked_result／checked_display_reviewを再利用。受信側は完全schema、有限値、明示session、frame／時刻の順序、明示参照、期限を確認する。重複・逆順・別session・改変・異常な時計では距離を消す。例外を呼出側で捕捉しても古い数値が残らないことも確認した。
サンプルの全JSONLは `recordings/2026-11-16/motion_range_handoff_replay_r02/handoff_samples.jsonl` に保存しGitへ追加しない。元の主ログ・画像・profile・UI・操縦・FFBコードは変更していない。

## 検証

[verification.json](verification.json)。新規21＋関連計90テスト成功（先行スイートと重複あり）。値の完全一致、JSON往復、保留・期限切れ、例外後クリア、重複・逆順・未来・別session・参照改変・非有限・権限flag改変・余計なFFB指令field拒否、実行系から未接続を検証した。
実ログでは元bridge JSONL全体SHA、発行参照、先行監査の計算／表示判定等12ソースSHAを照合。研究目標の原本計画書のSHAも記録した。原本計画書は別リポジトリで、今回書き換えていない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/motion_range_handoff_r01/replay.py \
  --audit Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json \
  --intake-dir recordings/2026-11-16/body_display_full_intake_r02 \
  --raw-output-dir recordings/2026-11-16/motion_range_handoff_replay_r03 \
  --output-dir Experimental_results/2026-11-16/motion_range_handoff_r01/results_r03
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_driver_motion_handoff.py tests/test_driver_body_display_guard.py \
  tests/test_driver_motion_bridge.py tests/test_driver_motion_integration.py tests/test_body_display_range_audit.py
```

これは**robo25側での再現コマンド**で、GPU PCでの実行は不要。別PCへそのままパスをコピーしない。

## 次に結ぶ部分

既存 `collision_risk.evaluate_candidate_steering()` は車体基準の前後／左右障害物位置・車速／ヨー入力・車幅を受け取り、同一観測で3経路を評価する。今回の受け渡しはそこへ入れるための前段であり、まだ有効トラック・TTC・リスク勾配を作っていない。
次はカメラ直下基準の水平距離と、車体基準の位置・同時刻の運動情報との対応条件を整理する。単にスカラー距離をobstacle_forward_mへ代入したり、横位置を0に固定したりしない。明示確認なしに方向ゲート・hardware arm・FFB強度設定を変えない。
今回の保存ログ受け渡し検証は完了。現地の追加撮影・走行・G923操作・GPU PC反映は不要。日報・commit/pushは今回未依頼。
