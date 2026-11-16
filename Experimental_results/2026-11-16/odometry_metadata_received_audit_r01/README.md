# r03実記録：元odometryの受信・時刻進行・保存を確認

2026-11-16。**送信側odometry callbackからWebRTC受信・ファイル保存までの疎通確認は完了**。全2,045telemetryで受信済み、元stampも保存された連続観測間で進行している。今回の速度0は未受信の初期値ではなく、実際に受信したodometryメッセージの値として区別できた。物理精度・時計同期・FFB使用許可まで認定した意味ではない。

[正式全件結果](results_r01/audit.json)。提出archive `received_telemetry_odom_20261116_r03.tar.xz`、SHA `50619c1e1fb3b241ae7fe2d25c18746f0ebb17d5fd268703de0d5ab5ed55d5d2`。通常directory1＋通常file3を検査。raw原本は `recordings/2026-11-16/odometry_metadata_received_intake_r01`。入れ子の型・有限値・時刻因果関係・不明/受信状態・権限flag、共通envelope、元bytes/件数、sequence、正常終了、receiver3コードSHAを確認。

## 今回の結果

| 項目 | 結果 |
|---|---:|
| 保存イベント | peer_begin 1＋telemetry 2,045＝2,046 |
| telemetry受信時間幅 / 平均頻度 | 87.160979秒 / 23.4509 Hz |
| offered / queued / written | 2,046 / 2,046 / 2,046 |
| 保存bytes | 3,163,824、summaryと一致 |
| queue落ち / lock競合落ち / 拒否 / 受理後破棄 | 全0 |
| 保存sequence | 1〜2,046、内部欠けなし |
| 正常終了 | closed / error=null / writer_done・shutdown_complete=true |
| 対応v2 metadata / callback_received=true | 2,045 / 2,045 |
| sample_fields_valid=true / status=advanced | 2,045 / 2,045 |
| 保存観測間のcallback sequence進行 | 2,044 / 2,044区間 |
| 保存観測間の元header stamp進行 | 2,044 / 2,044区間 |
| 保存された異なる元stamp | 2,045 |
| callback sequence始点 / 終点 | 8 / 4,385 |
| observer diagnostic drops最大 | 0 |
| 受信したlinear.x / angular.z | 全0 m/s / 全0 rad/s |
| twist frame / pose frame | base_footprint / odom |
| sender内callback age P95 / 最大 | 18.225 / 25.648 ms |
| sender内stamp進行age P95 / 最大 | 18.225 / 25.648 ms |
| telemetry受信間隔 P95 / 最大 | 46.300 / 104.180 ms |
| receiver受信→writer timestamp差 P95 / 最大 | 0.616 / 5.353 ms |
| recorder投入最大 | 0.4290 ms |

元stampは整数nsで `1794822450209981778` → `1794822537374867279`。callback sequenceの飛びは、全callbackを保存する設計ではなく送信時の最新snapshotだけを保存するため、それだけで欠落やobserver dropとはしない。全callback受信の完全記録とは主張しない。

単一session `4852ed17f96f41cfbd13aa38d0ba6592`、receiver時計 `receiver-process/dc5c953f531a473697cec72b2c044ff3`、sender ID `486c49b1306c4367a76ff576283882ef`。receiverのrecorder/UI/helper SHAは現版一致。sender自身の全sourceSHAはwireにないため完全なコード一致は未確認だが、対応版metadataの生成・伝送は観測できた。

sender内ageはsender callback後の経過であり、元計測の輸送遅延やカメラ露光とのずれではない。receiver→writer差はディスク完了時間/通信遅延ではなく、投入時間もcallback全体の時間ではない。受信間隔最大104.180msがあるため常時100ms未満とはしない。

## 前回との比較と未解決事項

[r02の記録](../odometry_metadata_live_audit_r01/README.md)では全3,222telemetryが `callback_received=false / status=not_received`。今回は全2,045telemetryが受信済みかつ元stamp進行。従来UIの速度0だけでは区別できなかった初期値と受信値を、新metadataで区別できることを実記録で確認した。r02とr03は別session/別process時計で、同一の時系列として混ぜない。

ユーザーによる間の読み取り診断では `/odom` にkobukiのpublisherとthetaのsubscriberが存在し、双方RELIABLE/VOLATILE、CLI echoでも元stamp・odom/base_footprint・v/ω0を受信できた。これはユーザー貼付出力の記録であり今回archiveにCLIログが含まれているわけではない。r02未受信が解消した直接原因は、driverの起動時刻やprocess状態の記録がなく特定していない。QoS変更が必要だったとは結論しない。

`sample_fields_valid=true` は構造上の有効性で物理精度認定ではない。odomの時計種別とsender/receiver monotonicの対応・ドリフト、車体/光学変換、距離と運動の同時刻対応は未確認。全出力の `source_freshness_verified / physical_metric_verified / usable_for_ffb / published_to_ros` はfalseを維持する。今回の停止メッセージだけで走行時の速度精度・符号・リスク勾配を認定しない。

## 次の段階

この疎通確認を繰り返すための追加撮影・走行・画面録画・再記録は不要。次は既存の[offline運動・距離受け渡し形式](../motion_time_join_r01/README.md)へ新metadataをどう渡し、時計対応不明時に保留するかを検証する段階。

今回archiveはtelemetryだけで距離ログを含まない。以前の距離実験とはsession/時計も異なるため、送信wall時刻等を使って無断で実距離と結合しない。現取付の車体↔光学変換等も別途必要で、直ちに実FFBへ接続する段階ではない。まだそのadapterや実機用時計対応を新たに実装したわけではない。

## 検証と再現

[監査器](../odometry_metadata_live_audit_r01/review.py)へ明示的なarchive prefix指定と保存観測間の元stamp/sequence進行・ageの集計を追加。prefix以外の許可pathを拡大せず、raw不変・v2厳密検査・共通envelopeコピー上の投影検査を維持。過去resultsのcodeSHAは履歴として保存し、書き換えない。

新規3テスト（受信0/元stamp進行、callback進行とstamp反復の区別、明示prefix/不正path拒否）を追加。監査12＋旧監査9＋観測20＋記録22＝**63成功、0失敗（1.05秒）**。以前の60/200テスト等と重複するため独立件数として加算しない。runtime・測距・操縦・ROS/FFB処理は変更していない。

再実行は未使用の出力名を使う。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/review.py --archive /home/robo25/Downloads/received_telemetry_odom_20261116_r03.tar.xz --archive-prefix received_telemetry_odom_r03/ --raw-output-dir recordings/2026-11-16/odometry_metadata_received_intake_r02 --output-dir Experimental_results/2026-11-16/odometry_metadata_received_audit_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_odometry_metadata_live_audit.py tests/test_receiver_telemetry_live_audit.py tests/test_driver_odometry_observation.py tests/test_driver_telemetry_recording.py
```
