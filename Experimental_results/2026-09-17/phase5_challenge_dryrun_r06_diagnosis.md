# Phase 5 challenge方式 実カメラ・模擬ODOM dry-run 診断（r06）

## 入力と照合

- ハンコン接続PCのROS bag: `202609171820.tar.xz`（SHA-256 `80309e1013d46ac5c0c840d906dbc4894c0ae0fe51a86022fc20f516432e3f61`）
- Kobuki PCのカメラ録画: `202609171821.tar.xz`（SHA-256 `f664cef4e639a3512fde36ca96604792165e05476b4b351ab2909258079feea4`）
- 派生成果物: `phase5_challenge_live_r06_bag_summary.json`、`phase5_challenge_live_r06_events.csv`、`phase5_challenge_dryrun_r06_analysis/`
- 実行モード: status全289件が `dry_run`。実機の振動は評価していない。

## 判定

**カメラ→警告→PC間指令→dry-run出力の経路は成立。ただし全体試験は未合格。** 警告に対応するactive指令8件はカメラCSV、bag command、adapter statusのsequenceが一致し、すべて `action=apply`、`output_active=true`、`applied_magnitude=0.05`、`fault=false`。従来の `future_message` は0件だった。一方、challengeがカメラ側で利用できず送信を見送ったframeが455/742件、期限切れなどのfaultが3件、実効FPSが29.524で30fps±1%基準を下回った。hardwareへはまだ進めない。

## 定量結果

| 項目 | 結果 |
|---|---:|
| カメラframe・青箱検出 | 742・742/742 |
| 実効FPS / 処理p95 | 29.524 / 29.47 ms |
| 模擬ODOM 0.25 m/s | bagで89件、約2.93秒 |
| WARNING | 24 frame（録画内13.957–14.724秒） |
| 最初のWARNINGから最初のFFB activeまで | 約0.266秒（challenge未取得8 frame） |
| active指令 / 対応するactive status | 8 / 8 |
| active時のchallenge往復時間（bag記録時刻で概算） | 6.65–26.04 ms、中央値14.31 ms |
| publish見送り | 455/742 frame、全件 `no_recent_receiver_challenge` |
| adapter fault | 3件、activeではないCLEAR/PATH相当の指令のみ |
| fault内訳 | `expired_receiver_token` 1、`unknown_receiver_token` 2 |
| 最終status | `shutdown`、`output_active=false` |

challenge token `32440` はbag上18:19:14.249に発行され、18:19:14.351のinactive指令で期限切れ（約102 ms）。token `32668` は18:19:18.809に発行され、18:19:18.917と18:19:18.955のinactive指令では期限切れ・既に破棄済み（約108/146 ms）だった。拒否時はどれもSTOPしており、fail-closedは維持された。

録画を5秒ごとに見ると、送信見送りは0–5秒142件、5–10秒109件、10–15秒8件、15–20秒44件、20秒以降152件。ハンコン側のbagではchallengeは全期間約50 Hzで記録され、最大発行間隔は約21 msだった。ただしこれはハンコン側での発行を示すだけで、Kobuki PCが受信した証拠ではない。カメラ処理遅延だけでなく、PC間のchallenge配信または受信コールバックを切り分ける必要がある。

## 次の切り分け

1. hardwareは使わない。Kobuki PC側でも `/collision/ffb_challenge` をbagに記録し、ハンコン側bagの発行件数と同時区間で照合する。カメラ起動前・録画中・終了後の受信頻度を分けて見る。
2. カメラ側で直近challengeの受信時刻・経過時間・見送り理由を記録し、ROS配信欠落かGUI側callback処理不足かを区別する。
3. senderが受信後100 msぎりぎりのtokenを返してinactive faultを出すため、sender側の利用期限をreceiver側100 msより短くすることを検討する。安全上限を広げる変更はしない。
4. 再試験ではchallenge見送り0に近づき、warning開始からFFB activeまでの遅延、fault 0、FPS基準を確認してからhardware展開の可否を再判断する。

`phase5_challenge_dryrun_r06_analysis/analysis_report.md` の自動判定FAILの直接理由はFPSであり、上記のFFB経路の成否とは別に扱う。
