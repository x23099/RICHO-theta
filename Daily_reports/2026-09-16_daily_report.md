# 2026年9月16日 日報

## 本日の到達点

G923の衝突警告を`triple / 0.05 / 0.5秒`で識別できることを停止状態で確認し、この有限cadenceを`bird_eye.py`のv7設定に接続した。実カメラ・模擬ODOMによるライブ録画では青箱検出からWARNING、FFB active指令の生成まで成立したが、最初の実機接続試験では振動を感じなかった。記録を取り直して切り分けた結果、PC間dry-runで時刻妥当性チェックによる指令拒否を再現し、両PCの時刻再同期後には同じ録画riskのPC間dry-runが**PASS**した。

本日確認したのは「録画済みriskからのPC間FFB通信とdry-run adapter受理」までである。実カメラを動かしながらのadapter受理、およびカメラ由来警告によるG923物理振動は未確認であり、走行実験にも進んでいない。

## 使用したPCと安全条件

| 呼称 | ホスト名 | 役割 |
|---|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5` | 360度カメラ、`bird_eye.py`、録画、模擬ODOM、FFB指令送信 |
| ハンコン接続PC | `hsr-Alienware-m16-R2` | G923、`collision_ffb_node`、FFB status確認 |

ROSドメインは両PCで`88`とした。ハンコン側の物理試験は停止状態・上限0.05で行い、後半の原因切り分けは`output_mode=dry_run`のみで行った。模擬速度は実ロボットの`/odom`に混ぜず、再試験では専用`/phase5/mock_odom`を使った。安全上限、future/stale時刻しきい値、watchdogは緩めていない。

## 実施内容と結果

### 1. G923の通知cadence比較とv7実装

合成FFB指令を使い、continuous、double、tripleをそれぞれ0.05・約0.5秒で比較した。３条件ともadapterの自動判定はPASS、fault 0件、最後のCLEAR停止も確認した。操作者の体感ではcontinuousは知覚できるがやや弱く、doubleは２回の区切りが不明瞭、tripleは３回と識別できた。tripleの応答時間p95は1.244 ms、最終CLEAR停止は1.047 msだった。watchdog試験では通信停止から約106 msで安全停止した。

この結果を受け、v7設定でWARNING時に３回ONとなる有限cadenceを実装した。継続WARNINGだけでは再発火せず、CLEAR/PATHで途中停止する。既定設定のcontinuousは維持し、実機強度上限0.05も変更していない。実装時の全回帰試験は173件PASSした。詳細は[triple cadence実装・実機比較](../Experimental_results/2026-09-16/2026-09-16_triple_cadence_implementation.md)と[実機比較CSV](../Experimental_results/2026-09-16/hardware_cadence/hardware_cadence_summary.csv)を参照。

### 2. 実カメラ・模擬ODOMのライブ試験

起動準備では、Kobuki PCのシェルが誤ったROSドメインを参照したため`/odom` preflightが失敗した。ドメインを`88`に揃えて起動できた。また、作業ツリーに変更がある状態では`--require-clean-git`が起動を止めることも確認した。

17:47の録画`202609161750.tar.xz`は1,191フレーム・39.790秒、実効29.929 FPS。青箱検出・観測採用・追跡・ODOM受信はいずれも100%で、模擬速度0.25 m/sを100フレーム記録した。確定WARNINGは116フレーム、FFB active指令は32フレーム、送信API失敗は0件だった。しかし操作者はG923振動を感じなかった。ハンコン側で得られた初回adapterログとrosbagは警告区間のstatusを証明できず、この初回無振動の単独原因は確定できなかった。この試験では模擬速度0と0.25が交互に見える区間もあり、送信元の競合が疑われた。

18:31の再録画`202609161835.tar.xz`は専用`/phase5/mock_odom`を使い、402フレーム・13.396秒、実効29.997 FPSだった。青箱検出・観測採用・追跡は各402/402フレーム、模擬速度0.25 m/sは123フレーム連続で受信した。確定WARNINGは123フレーム、FFB active指令はtripleの３つのON区間に対応する10フレームだった。どちらの録画もraw/BEV/detection動画とCSVのフレーム数が一致した。詳細は[17:47解析](../Experimental_results/2026-09-16/phase5_synthetic_odom_live_analysis/analysis_report.md)と[18:31解析](../Experimental_results/2026-09-16/phase5_synthetic_odom_dryrun_r02_analysis/analysis_report.md)に保存した。両解析の`DIAGNOSTIC`は事前要件CSV未指定によるもので、完全性検査の失敗ではない。

### 3. 無振動原因の切り分けと時刻再同期

端末のスクロールバックでは警告時のstatusを追えなかったため、18:31録画のriskをKobuki PCから再生し、ハンコン接続PCのdry-run adapterが出すstatusをCSV保存した。

| PC間再生 | 指令 / active | status / active | fault | 最大適用強度 | 判定 |
|---|---:|---:|---:|---:|---|
| 再同期前 r03 | 403 / 9 | 382 / 0 | 376 | 0.000 | FAIL |
| 再同期後 r04 | 403 / 9 | 402 / 9 | 0 | 0.050 | PASS |

r03ではactive９件すべてがハンコン側へ届いたものの、全件`invalid_request:future_message`で拒否された。全status中ではfuture faultが375件、stale faultが１件で、future faultのage平均は`-62.842 ms`だった。これは許容値`-50 ms`を超える。両PCとも`timedatectl`は同期済みと表示したが、再同期前のNTP Offset推定値はハンコン側`-26.020 ms`、Kobuki側`-93.338 ms`で、その差67.318 msが拒否時のageと近かった。異なるNTPサーバーを使い、通信遅延・jitterも大きかったため、Offsetの差を厳密なPC間時計差とは扱わない。

両PCの`systemd-timesyncd`を再起動し、新しいNTP応答を各２件受け取った後のOffset推定値はハンコン側`+21.450 ms`、Kobuki側`-6.508 ms`、差27.958 msだった。続くr04は自動判定PASS。active sequence 201～203、206～208、211～213の９件すべてで`action=apply`、`output_active=1`、要求0.25を上限0.05へ制限し、fault 0件、最後はinactiveを確認した。CLEARのstatusが１件欠けたが、activeの欠落はない。詳細は[r03失敗レポート](../Experimental_results/2026-09-16/phase5_dryrun_crosspc_replay_r03/replay_report.md)、[r04成功レポート](../Experimental_results/2026-09-16/phase5_dryrun_crosspc_replay_r04/replay_report.md)、[原因診断](../Experimental_results/2026-09-16/phase5_synthetic_odom_no_vibration_diagnosis.md)を参照。

## 判断と未確認事項

- 録画riskからの指令生成、PC間ROS配送、adapterの時刻検査、dry-runの強度制限と停止は成立した。
- 「NTP同期済み」表示だけでは50 ms以内のPC間時刻精度を保証しない。時刻の安全しきい値を緩めず、実験直前に再確認する。
- r04の`output_active=1`はdry-run adapterでの論理出力であり、G923物理振動を意味しない。
- 実カメラ動作中にadapter側でactive受理した証拠はまだない。走行中のTTC連動FFBも未実施。
- r04はユーザー提供のreportとstatus CSVを保存した。完全な再生コマンドCSV・summary JSONは未取得であり、次回は出力フォルダ全体を保存する。

## 成果物と次回作業

[成果報告用の画像・グラフ](../Experimental_results/2026-09-16/report_assets/README.md)には、生カメラ画像１点とcadence比較・dry-run再生のグラフ２点を保存した。生画像は無加工だが元録画は９月８日である。今日の録画から切り出した生画像には人物が明瞭に写っていたため、公開リポジトリへの追加を見送った。元の大容量動画アーカイブはGitへ追加していない。

次回は、両PCの時刻同期と`ROS_DOMAIN_ID=88`を確認したうえで、Kobuki停止・専用`/phase5/mock_odom`・実カメラ・ハンコン側dry-runのライブ試験を行う。速度0と0.25 m/sのpublisherを同時に起動せず、FFB command/statusの全区間をCSVまたはbagに保存する。合格条件はWARNING中のactive status、fault 0件、最終inactiveである。それを満たした後に限り、強度上限0.05のG923物理試験を別段階として検討する。走行試験と強度引き上げは自動的には行わない。

## Git

本日のv7ライブ実装は`RICHO-theta`の`7f0bb56`、ハンコン側の比較・手順は`FFB_feedback_control`の`359637a`以降に記録されている。本日新たに作成した解析・診断・日報は`RICHO-theta`へコミットしてpushする。ハンコン側作業ツリーには未コミット変更がないため、追加コミットは行わない。
