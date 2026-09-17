# PC間の時計に依存しない FFB 指令鮮度判定（dry-run 導入案）

## 背景と判断

2026-09-17 の r04/r05 と短時間 probe では、カメラ側の警告は送られたが、ハンコン側が送信時刻を約 51–58 ms 未来と判定して停止した。現行の `maximum_message_age_sec=0.1` と `future_tolerance_sec=0.05` は、送受信PCの時計が近いことを前提とする。FFB 出力の可否をこの前提から切り離す。

ROS 2 の `deadline` と `liveliness` は途絶検出の補助になるが、指令内容の妥当性や古い指令の再生を単独では検証しない。`lifespan` は送信元時刻を使うため、時計差がある環境では今回の問題をそのまま移す可能性がある。出典: [ROS 2 Humble QoS](https://docs.ros.org/en/humble/Concepts/Intermediate/About-Quality-of-Service-Settings.html)、[ROS 2 QoS 設計](https://design.ros2.org/articles/qos_deadline_liveliness_lifespan.html)。

## 提案プロトコル

1. ハンコン側 adapter は起動ごとにランダムな `session_id` を作り、連番の `token` を約 20 ms ごとに `/collision/ffb_challenge` へ送る。発行時刻はハンコン側の**単調時計だけ**で保存する。
2. カメラ側は直近に受け取った `(session_id, token)` を各 `/collision/ffb_command` に付ける。カメラ観測・ODOM の鮮度は送信側の単調時計で従来どおり検査する。
3. adapter はトークンが現在のセッションで発行済みか、受信時点で発行から 100 ms 以内かを自分の単調時計で判定する。無効なら必ず STOP。既存の source、連番、risk/pattern、強度上限、受信後 100 ms watchdog は維持する。
4. 以前の `header.stamp` は記録・解析用に残すが、このモードの出力可否には使わない。送信側で警告の元となる観測が古ければそもそも active 指令を生成しない。
5. 新モードは当面 `dry_run` 限定。既存の hardware と旧指令プロトコルは変更せず、新しい両PCの build・統合試験が終わるまで実機には接続しない。

受信側で発行した番号の往復時間を判定するため、時計を共有せずに遅延した最初の active 指令も拒否できる。一方、100 ms 未満の遅延は許容する。これは現行の最大メッセージ年齢と同程度の上限であり、ネットワーク遅延の実測後に妥当性を再評価する。通信相手の認証機構ではない。

## 必須試験

- 正常な 30 Hz 指令は `dry_run` で active status を返す。PCの壁時計を相対的にずらしても結果が変わらない。
- 未発行、別セッション、期限切れ token、重複・逆順 sequence は STOP し、fault を記録する。
- 発行直後の指令が輸送中に遅れ、受信時に token が期限切れなら STOP する。
- CLEAR、送信停止、challenge 停止、adapter 再起動のいずれでも出力が残らない。最後の有効 active 指令から 100 ms 以内に watchdog が STOP する。
- 欠落・遅延・再順序化を含むテストを通した後、2台のPCで rosbag と status を記録して dry-run 統合試験を行う。

## 導入条件

両PCの `oit_interfaces` を同じ版へ更新する必要がある。片側だけ新しいメッセージ定義のまま実験しない。hardware モードへの展開は、dry-run 統合試験、異常注入試験、明示的な安全レビュー後に別作業とする。

## 2026-09-17 実装・検証状況

- `FFB_feedback_control` 側に `CollisionFfbChallenge.msg`、command の受信側トークン欄、受信側単調時計による期限判定を追加。`freshness_mode=clock` が既定で、`freshness_mode=challenge` は hardware 起動を拒否する。
- `RICHO-theta` 側に challenge 購読と短命トークン添付、challenge が届かない場合の fail-closed、専用設定 `bird_eye_config_ttc_v7_ffb_triple_challenge_dryrun_20260917.json` を追加。
- FFB側 73件、カメラ側 169件の対象テストを通過。FFB ROS interface のビルドを確認。隔離したローカル ROS domain 211 で adapter と probe を接続し、active 15/15、fault 0、最大適用強度 0.05、最終 CLEAR を確認（**dry-runのみ**）。
- FFB リポジトリ全体の lint テストは未変更の旧ファイルも大量に検査して失敗する。変更対象ファイルに絞った flake8 は通過。
- **未実施:** 2台のPC間の challenge 通信、時刻差を持つ2台での実測、実カメラ・模擬ODOMの録画。hardware は新方式ではコード上で禁止している。

導入時は両リポジトリの変更を対応する2台に配布し、両方で `oit_interfaces` と `oit` を再ビルドする。新しい `.msg` と古い `.msg` を混在させた ROS グラフで試験しない。最初はカメラを使わず、受信側 adapter を `--ros-args -p output_mode:=dry_run -p freshness_mode:=challenge` で起動し、送信側の `collision_ffb_probe` を `--freshness-mode challenge --expect-output-mode dry_run` で走らせる。ROS_DOMAIN_ID は両PCで同じ値を明示する。成功条件は有効指令全件が apply、fault 0、最後の inactive。これが通ってから実カメラ・模擬ODOMへ進む。
