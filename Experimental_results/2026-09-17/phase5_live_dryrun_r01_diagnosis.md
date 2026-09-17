# 2026-09-17 Phase 5 実カメラ・模擬ODOM・PC間dry-run診断

## 判定

**ライブ接続の合否は未判定。** Kobuki PCのカメラ録画では青箱検出、模擬速度0.25 m/s、TTC WARNING、triple FFB active指令生成まで成立した。しかし、ハンコン接続PCのrosbagはそのactive区間のFFB command/statusを記録していない。bagに残った後続のCLEAR指令に対しては未来時刻エラーが73件発生した。したがって、ライブWARNINGがadapterで受理されたという証拠はなく、hardware試験へ進む条件も満たしていない。

## 入力と完全性

| 入力 | 内容 | SHA-256 |
|---|---|---|
| `/home/robo25/Downloads/recoding/202609171430.tar.xz` | Kobuki PCの実カメラ録画１セッション、metadata、detections.csv、raw/BEV/detection動画 | `2e37e83e51b80ade7338bbd96d46c5778ef37b3b7e4468b8301a7c09850b01c5` |
| `/home/robo25/Downloads/recoding/202609171431.tar.xz` | ハンコン接続PCのrosbag、metadata.yaml、SQLite3 | `010c8f59dab2df2b30ee81488d7c7bf9e17ce762417cae5e2e0bd09a08da5fde` |

カメラ録画の完全性・処理統計は[`phase5_live_dryrun_r01_analysis/analysis_report.md`](phase5_live_dryrun_r01_analysis/analysis_report.md)へ保存した。録画１セッションのCSVと３動画はいずれも1,597フレームで一致し、実効29.870 FPS、有効処理時間p95は28.77 msだった。自動判定`DIAGNOSTIC`は要件CSV未指定の意味であり、ファイル破損ではない。

## カメラ録画で確定できること

録画sessionは`phase5_camera_mock_odom_dryrun_r01_20260917_142548_940`。metadataの作成時刻は14:25:48 JST、録画時間は53.452秒、ODOM topicは`/phase5/mock_odom`、FFBはv7 triple設定だった。青箱の検出・観測採用・追跡は各1,597/1,597フレーム。ODOM受信は745フレーム（46.65%）、うち0.25 m/sは121フレーム、録画開始22.888～26.916秒の間だった。

| 事象 | 録画開始後 | FFB sequence | フレーム数 |
|---|---:|---:|---:|
| PATHへ進入 | 22.888秒 | 3528 | 2 |
| 確定WARNING | 22.951～27.043秒付近 | 3530以降 | 122 |
| FFB active指令 | 22.951～23.352秒 | 3530～3542のうち10件 | 10 |
| CLEARへ復帰 | 27.043秒 | 3652 | 以後CLEAR |

active指令は約14:26:11.891～14:26:12.292 JSTに生成され、要求強度は各0.25。最小TTCは4.259秒。カメラ側のFFB publish API失敗は0件だった。ただし、この成功値はローカルpublisherの呼び出し成功であり、相手PCへの到着を保証しない。

## rosbagで確定できること

rosbagは13:53:08～14:27:03 JSTの約33分54秒を含み、総メッセージ59,089件。３topicの内容をSQLiteから読み、ROS 2メッセージとして復元した。

| topic | 件数 | 記録された時刻 | 内容 |
|---|---:|---|---|
| `/phase5/mock_odom` | 58,627 | 13:53:08～14:25:55 | 全件linear.x=0.0 m/s。0.25 m/sは記録なし |
| `/collision/ffb_command` | 363 | 14:26:51～14:27:03 | sequence 4710～5072、全件CLEAR/`no_alert`、active 0件 |
| `/collision/ffb_status` | 99 | 14:26:50～14:26:54 | 全件`dry_run`、active 0件。25件inactive CLEAR、73件future_message fault、１件shutdown |

カメラ録画は約14:26:42に終了した。一方、bagの最初のFFB commandは14:26:51.278、最初のFFB statusは14:26:50.945であり、active指令の約39秒後に初めて記録されている。bagのFFB sequenceもカメラ側activeの3530～3542より後の4698以降である。したがって、bag内に該当active区間のstatusがないことは時刻とsequenceの両方から明確である。なぜbagがFFB topicをその時点まで記録できなかったか、またadapterが警告時に起動していたかは、この２アーカイブだけでは確定できない。

bagの模擬ODOMも14:25:55で止まり、カメラ側で観測された0.25 m/sを含まない。別publisherへ切り替えた後のtopicをbagが拾えていない可能性があるが、切替時のコマンドやbagの購読ログがないため原因は未確定である。

記録されたCLEAR status 99件のうち73件は`invalid_request:future_message`で、ageは平均`-52.197 ms`、範囲`-53.030`～`-50.027 ms`だった。adapterの許容値は`-50 ms`。同区間のFFB command header時刻はbag受信時刻より平均51.647 ms先であり、両PC間の時刻差が再びしきい値近くまで広がったことと整合する。これは**警告後のCLEAR区間**で観測された現象であり、欠落したactive指令が拒否されたと断定する材料ではない。

## 次の試験

1. 両PCの時刻同期状態・NTP Offsetを試験直前に読み取り、差が大きい場合は同期を改善する。`future_tolerance_sec`等の安全しきい値は変更しない。
2. ハンコン接続PCでdry-run adapterを起動し、Kobuki PCの`bird_eye.py`がFFB topicをpublishし始めてから新しいrosbagを開始する。bag側にcommand・status・mock ODOMの３topicの購読が表示されたことを確認してからカメラ録画と模擬速度切替を行う。
3. bagは警告区間の前後だけを記録し、終了後に各topicの件数を確認する。特に0.25 m/sのODOM、active command、対応するactive statusがそれぞれ１件以上あり、fault 0件、最後inactiveであることを合格条件とする。
4. ライブdry-runの合格後に、Kobukiを停止したままG923物理出力0.05を別試験として検討する。
