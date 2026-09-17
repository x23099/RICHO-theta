# 2026-09-17 Phase 5 停止状態G923ライブ試験 r04 無振動診断

## 結論

**G923ライブ試験はFAIL。振動が無かった直接の理由は、WARNINGのactive指令10件をhardware adapterがすべて`future_message`として拒否したこと。** 0.25 m/sの模擬ODOM、青箱検出、カメラ側WARNING、ROS command到着までは成立した。hardware adapterの対応statusは10件とも`action=stop`、`output_active=false`、`applied_magnitude=0.0`、`fault=true`。したがって、G923物理効果の強さやデバイス機能について、この試験からは評価できない。

さらに、同じ10件のactive指令それぞれに`dry_run`と`hardware`の２つのstatusがほぼ同時刻に記録された。試験中に両modeのadapterが並存した証拠であり、前試験のdry-runプロセスが残った可能性がある。次の物理試験前に両方停止し、FFB status publisherを１つにする必要がある。

## 入力と解析

| 入力 | 内容 | SHA-256 |
|---|---|---|
| `/home/robo25/Downloads/202609171638.tar.xz` | Kobuki PCの実カメラ録画、CSV、３動画 | `376a0c28014cfd3ac28e18c0136fa273a368bbd658677b1db3616ea11a4c4bf6` |
| `/home/robo25/Downloads/recoding/202609171637.tar.xz` | ハンコン接続PCのrosbag、３topic | `294b3d2ff12cecf076242ecb100d81aaaab7722c84060432ca01db3722d8cd74` |

カメラ録画の[標準一括解析](phase5_live_r04_analysis/analysis_report.md)と、bagの[集計JSON](phase5_live_r04_bag_summary.json)・[全イベントCSV](phase5_live_r04_events.csv)を保存した。bagのCDR復元には[解析スクリプト](analyze_phase5_bag_r02.py)を使用した。bagの受信時刻とメッセージheader時刻、FFB sequenceを照合した。

## カメラ・FPS

| 指標 | 結果 |
|---|---:|
| セッション | `phase5_camera_mock_odom_dryrun_r04_20260917_163414_067` |
| 録画完全性 | CSVとraw/BEV/detection動画が各1,068フレームで一致、PASS |
| 実効FPS | 29.804（要求30の±1%以内） |
| 青箱検出・観測採用・追跡 | 各1,068/1,068フレーム |
| 0.25 m/s観測 | 121フレーム |
| WARNING | 121フレーム |
| FFB active | 10フレーム、要求強度0.25、publish API失敗0件 |

r03で低下したFPSは回復し、BEV前処理中央値は15.37 msから5.62 msへ戻った。録画中のダウンロードがr03低下の原因だったというユーザー報告とは整合するが、システム負荷を同時記録していないため因果関係は確定しない。自動判定`DIAGNOSTIC`は事前要件CSV未指定によるもので、録画破損ではない。

## PC間FFB経路

| topic | 記録数 | 内容 |
|---|---:|---|
| `/phase5/mock_odom` | 3,841 | 0.25 m/sが90件、16:34:24.135～27.104 JST |
| `/collision/ffb_command` | 4,108 | active10件、16:34:24.282～24.688 JST |
| `/collision/ffb_status` | 8,319 | `dry_run`4,160件、`hardware`4,159件 |

カメラCSVとbag commandのactive sequenceは`3754, 3755, 3756, 3757, 3760, 3761, 3762, 3764, 3765, 3766`で完全一致。各sequenceに対して`dry_run`と`hardware`のstatusが１件ずつ存在し、計20件がすべて`invalid_request:future_message`、`action=stop`、`command_active=false`、`output_active=false`、`applied_magnitude=0.0`だった。active statusは０件。bag全体ではfault8,068件がすべて未来時刻エラーで、平均ageは`-56.79 ms`、範囲`-58.536`～`-50.047 ms`。active commandのheader時刻はbag受信時刻より57.26～57.76 ms先にあり、adapterの未来時刻許容50 msを超えた。

２つのadapterが同時にstatusを出したことはbagで確定する。ただし、各プロセスの起動コマンドやPID、NTP設定はbagからは分からず、「前回のdry-runを止め忘れた」とまでは断定できない。hardware modeのプロセスが実際にG923への物理出力を行えるかも、この指令拒否試験では未確認。

参考として、約23分前のr03ではactive commandのheaderがbag受信時刻より中央値26.49 ms先で、faultは０件だった。r04では約57.7 ms先となり、50 msを超えた。両試験間で時刻差が変化したことと整合するが、NTP Offset・jitterの同時ログがないため変動要因は未確定。

## 次の安全な順序

1. ハンコン接続PCで`dry_run`と`hardware`の両adapterを終了し、`ros2 topic info /collision/ffb_status -v`の`Publisher count: 0`、`/collision/ffb_command`のadapter購読数0を確認する。PIDを確認せずに広範なkillを行わない。
2. 両PCのNTP Offsetと通信状態を確認し、50 msの安全しきい値は緩めない。先に**単一のdry-run adapter**で数十秒のPC間再生を行い、fault 0件とactive受理を再確認する。前回１回のCLEAR成功後にも時刻差が再び広がったため、単発CLEARだけを合格条件にしない。
3. その後dry-runを完全停止し、status publisher数0を確認してから、G923を固定したまま単一のhardware adapterを上限0.05で起動する。起動直後のpublisher数1、実際のmode、他FFB writer停止、即時電源断手段を確認し、短い１イベントだけ試す。fault、予定外の力、残留出力があれば中止する。

実ロボットは停止を維持し、実際の`/odom`に模擬速度を流さない。走行試験と強度上限引き上げには進まない。
