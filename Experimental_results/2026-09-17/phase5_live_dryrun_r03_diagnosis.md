# 2026-09-17 Phase 5 実カメラ・模擬ODOM・PC間 dry-run r03 診断

## 判定

**FFBライブ接続はPASS、録画全体の自動品質判定はFAIL。** 実カメラで青箱を検出し、専用模擬ODOM 0.25 m/sによりWARNINGが生じ、同一sequenceのactive指令９件がハンコン接続PCに到達した。９件すべてに対してadapterは`dry_run`で`action=apply`・`output_active=true`・`fault=false`を返し、要求0.25を上限0.05にクランプした。最後はinactiveで終了した。これにより、r01のbag欠落とr02の`disabled`・未来時刻faultは、このr03試験では再発していない。

一方、録画の実効FPSは25.456で、要求30 FPSの±1%という既存の品質基準を満たさず、[標準一括解析](phase5_live_dryrun_r03_analysis/analysis_report.md)は`FAIL`。このFAILを無視して30 FPS相当のリアルタイム性能まで実証したとは扱わない。G923の物理振動と実走行は本試験の対象外。

## 入力と検証方法

| 入力 | 内容 | SHA-256 |
|---|---|---|
| `/home/robo25/Downloads/202609171615.tar.xz` | Kobuki PCのr03カメラ録画、CSV、raw/BEV/detection動画 | `29499cef92a38824d53467b01eec5e1998a49eaeff8659bb3e24cf1454f7f6bd` |
| `/home/robo25/Downloads/202609171613.tar.xz` | ハンコン接続PCのr03 rosbag、３topic | `dc5307a26092500d18fcf113f290bc820c09b1f9c8325bd809ee76dd63ea5bb7` |

カメラアーカイブは`src/analyze_field_recording.py`にv7設定を指定して解析した。bagのROS 2 CDRは[解析スクリプト](analyze_phase5_bag_r02.py)で復元し、[bag集計JSON](phase5_live_dryrun_r03_bag_summary.json)と[全イベントCSV](phase5_live_dryrun_r03_events.csv)を保存した。時刻比較にはbag記録時刻を使い、カメラとの対応はFFB sequenceで確認した。

## 録画・観測

| 指標 | 結果 |
|---|---:|
| セッション | `phase5_camera_mock_odom_dryrun_r03_20260917_161102_466` |
| 録画 | 1,678フレーム、65.878秒、実効25.456 FPS |
| raw/BEV/detection動画・CSV | すべて1,678フレームで一致、時刻単調性PASS |
| 青箱検出・観測採用・追跡 | 各1,678/1,678フレーム |
| ODOM available | 748/1,678フレーム |
| 0.25 m/sを観測 | 116フレーム、録画開始後29.029～33.193秒 |
| WARNING | 116フレーム、29.117～33.266秒 |
| FFB active | ９フレーム、29.117～29.526秒、要求0.25 |
| 最小有限TTC | 4.523秒 |
| FFB publish API失敗 | ０件 |

## rosbagとadapter応答

| topic | 記録数 | 主な内容 |
|---|---:|---|
| `/phase5/mock_odom` | 3,396 | 0 m/sが3,307件、0.25 m/sが89件（16:11:31.474～34.409 JST） |
| `/collision/ffb_command` | 4,084 | active９件（16:11:31.559～31.971 JST） |
| `/collision/ffb_status` | 4,165 | 全件`dry_run`、active９件、fault０件 |

カメラCSV、bag command、bag statusに共通するactive sequenceは`7129, 7130, 7131, 7134, 7135, 7136, 7139, 7140, 7141`の９件。各statusは`action=apply`、`command_active=true`、`output_active=true`、`requested_magnitude=0.25`、`applied_magnitude≈0.05`、`fault=false`。bag記録上のcommandから対応statusまで0.322～0.682 ms、中央値0.616 ms。ただし、これはROS受信後の応答差であり、カメラ撮像からの総遅延ではない。最後のstatusは`reason=shutdown`、`output_active=false`、`fault=false`。

active指令のheader時刻はbag記録時刻より23.1～27.6 ms先（中央値26.5 ms）だったが、adapterの未来時刻許容50 ms以内で、この試験中に時刻faultは０件だった。両PCの時計が今後もこの範囲に保たれるかは別途監視が必要。

## 残る性能課題と次の作業

| 指標 | 前回r02 | 今回r03 |
|---|---:|---:|
| 実効FPS | 29.882 | **25.456** |
| フレーム間隔中央値 | 33.19 ms | **38.70 ms** |
| フレーム間隔p95 | 38.16 ms | **52.45 ms** |
| 動作中の有効処理時間p95 | 28.78 ms | **45.89 ms** |
| BEV前処理中央値 | 5.96 ms | **15.37 ms** |

両録画ともカメラはV4L2・1280×720・MJPG・設定30 FPS。r03はBEV前処理などの処理時間が増えたことがFPS低下と整合するが、CPU負荷・温度・周辺プロセスの記録がないため根本原因までは特定できない。次は録画を追加する前に、既存CSVの時間推移と実行環境を調べ、30 FPS要件を回復または要件の妥当性を明示的に再評価する。FFBの安全しきい値を緩めたり、この結果だけでG923物理出力に進んだりはしない。
