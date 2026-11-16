# 元odometryの受信状態・時刻・frameを送受信するmetadata

2026-11-16。前段の実telemetry2,208件は全0だったが、元odometry未受信の初期0か受信した0か区別できなかった。**送信側でその事実を付加し、受信側で対応schemaとして別に保存する実装を完了**。未反映・未commit/未push。ユーザーの前回「GPU反映済み」はこの変更前の記録機能を指す。

今回は実機/ROS/ネットワーク/カメラ/FFBを起動していない。[正式結果](results_r02/audit.json)、[模擬14ケース](results_r02/cases.json)、[テスト記録](verification.json)。r01はobserver初期化例外の防御強化前に成功した履歴で、現行の正式版はr02。

## 変更したもの

- [driver_odometry_observation.py](../../../src/driver_odometry_observation.py): ROS依存のない観測器と厳密なwire検査。固定数・有界な数値/文字列だけを扱い、ファイル保存やROS publishはしない。
- [webrtc_stream.py](../../../src/webrtc_stream.py): 購読callbackに任意のsidecar観測を追加し、既存telemetry辞書へ `odometry_observation` を1項目追加。従来の値・topic・subscription・publish・camera・codec・送信頻度は変更しない。metadataの初期化/観測/読出し異常はmetadataだけを不採用にし、既存値は継続する。
- [driver_telemetry_recording.py](../../../src/driver_telemetry_recording.py): 対応版metadataを検査してv2 recordへ保存。従来どおり固定数の処理と有界queueだけを受信callbackで行い、保存は別thread。

UI本体・操縦信号・距離計算・校正・表示採否・FFB経路は変更していない。従来のUI用 `linear_x/angular_z` は互換のため残し、同じcallbackの時刻と値が必要な用途には新しいまとまったmetadataを使う。別threadで読まれる既存スカラーと新metadataの値が必ず同一更新になるとは仮定しない。

## senderのmetadata

`driver_odometry_observation_v1` が次の事実を持つ。

| 項目 | 意味 |
|---|---|
| `callback_received` | このobserverがodometry callbackを保持したか。未受信false、競合/時計異常では不明null |
| `callback_sequence` | observerが保持したcallbackの順序。ROSメッセージ本来のsequenceではない |
| `header_stamp_ns` | 元 `header.stamp` の整数ns。送信wall時刻へ置換しない |
| `motion_frame_id` | twistの基準である元 `child_frame_id`。base_linkへ暗黙固定しない |
| `pose_frame_id` | 元 `header.frame_id`。twistのframeと混同しない |
| `linear_mps/angular_radps` | そのメッセージから取得した符号付きv/ω。未受信は0ではなくnull |
| `callback_received_mono_sec/snapshot_mono_sec` | sender process内のcallback観測時刻/metadata読出し時刻 |
| `callback_age_sec` | 同じsender monotonic内の最終callbackからの経過時間 |
| `stamp_status` | 直近callbackの元stampがfirst/advanced/repeated/reversed/missingか |
| `stamp_progress_age_sec` | 正の元stampの最大値が最後に進んだcallbackからの経過時間 |
| `sample_fields_valid/invalid_fields` | 有限値・正のstamp・有界frame名等の構造上の検査結果 |

sender process IDとsender monotonic時計IDも記録する。callbackとsnapshotは短いlockで整合性を保ち、待たずに競合を明示する。callbackの競合はdiagnostic drop、読出し競合は `observer_busy`。時計非有限/巻戻りは旧値を返さず `clock_invalid`。stampが逆行しても高水位を下げないため、古い元時刻を新しい計測へ昇格しない。

`sample_fields_valid=true` は**構造検査に通った観測メッセージ**という意味で、センサ精度・covariance・接地・安全性の認定ではない。同じstampのcallbackが再送されても `callback_age` だけが新しくなり、`stamp_progress_age` は若返らない。逆にcallbackが止まればageが増える。`stamp_status=advanced` は直近callback時点の比較結果なので、その後何秒もcallbackがなくても同じ文字列が残り得る。ageと分けて読む。実機の許容age/FFB期限は今回選定していない。

元stamp 0/欠落/範囲外や不正なframe/数値はnullと診断へ分類する。本プロジェクトでは正の元stampだけを構造上有効とする保守的な方針で、ROSの全用途で0が不正だと主張していない。速度0も元stampとは別で、受信した停止値は0のまま保持する。

## 時計とframeに関する根拠・制約

ROS2公式の [Odometry.msg](https://github.com/ros2/common_interfaces/blob/humble/nav_msgs/msg/Odometry.msg) は、poseとtwistを別のframeで表す定義。このためtwistには `child_frame_id` を使い、poseの `header.frame_id` を流用しない。元時刻は [Time.msg](https://github.com/ros2/rcl_interfaces/blob/humble/builtin_interfaces/msg/Time.msg) のsec/nanosecから整数で組み立てる。docs.ros.orgの参照ページはアクセス拒否だったため公式GitHubのhumble定義を確認した。

ROS headerだけではその時計をsender monotonicやreceiver monotonicと同定できない。今回ROS clock nowとの照合・自動offset推定・NTP認定等は行わず、`header_clock_relation_verified=false / source_freshness_verified=false` を維持する。callback ageは**senderでcallbackが見えた後の経過**であり、元計測の輸送遅延や露光同時刻性ではない。古いstampが単調に進むケース、複数publisherの識別、時計ドリフト、センサ品質などは今回の情報だけで認定しない。

## receiverの記録と互換性

元senderのkeyがなければ `driver_received_telemetry_v1` を従来どおり保存する。keyがある場合は `driver_received_telemetry_v2` として `odometry_metadata_state` と `odometry_observation` を追加する。

- 対応版かつ厳密検査に通る: `versioned_odometry_observation`、独立コピーした観測dictを保存。
- 未知版: `unsupported_odometry_schema`、観測dictはnull。
- null/欠落フィールド/不正型/非有限/不整合/権限flag変更: `invalid_odometry_metadata`、観測dictはnull。

従来のトップレベル `linear_mps/angular_radps` は受信した旧UI用値のまま。未受信時の旧0を消したり、新metadataの代用にしたりしない。トップレベルの `measurement_valid/source_stamp_ns/motion_frame_id` 等も従来どおりnullに留め、**新しい観測は入れ子の中にだけ**保存する。これにより旧値と同一callbackの観測を混ぜず、既存offline joiner/ROS/FFBへ無断で新しい有効値を供給しない。

旧receiver/UIは追加辞書keyを無視できるが、旧記録器では新metadataは残らない。したがって今回の確認には**matsunucとGPUPC両方の反映**が必要。実行コードSHAには新helperを追加した。過去のv1実ログ・旧runtime manifestは履歴として保持し、今回のコードへSHAを書き換えたり、新metadata付きと見なしたりしない。

## 検証結果

| 項目 | 結果 |
|---|---:|
| 模擬ROS callback→実sender辞書→JSON→実receiver callback→保存 | 14/14成功 |
| 保存telemetry schema | v2 13件＋旧v1 1件 |
| 開始/終了を含む保存 | 16/16、drop0 |
| 未受信0と受信0 | 旧UI値は両方0のまま、新metadataで区別 |
| 無callbackの経過・stamp反復/逆行・stamp0・競合/時計異常 | 元情報と未認定flagを保持 |
| 元測距/表示計算12ソース | 全バイト不変 |
| 関連テスト | 200成功、0失敗 |

新20テスト＋metadata追加限定AST1を含むsuite。先行63/170/31等と重複するので加算しない。元TelemetryNodeの固定AST hashは、正確に限定したmetadata追加5箇所（初期化try・失敗flag・callback try・getter・辞書key）だけを除くと元hashに一致する。baseline hashの単なる差替えではない。publish/keyboard/control送信・sender camera/spin・旧shell末尾の固定AST/bytesも保持。

observer初期化/観測/読出し例外でも既存telemetryが続くこと、正逆走の符号、atomic v/ω/stamp、元stamp整数ns、厳密型/時刻/権限/世代の拒否、旧/新/不正metadata混在、返却後の入力変更が保存へ漏れないことを確認した。ROSの元callbackとWebRTC経路本体をfake Node/peerで実行しており、本物のROS購読・実通信・機体ではない。

合成生ログ: `recordings/2026-11-16/odometry_metadata_synthetic_r02/`。集計 `results_r02`。受信投入時間などは小規模合成環境の観測にすぎず、実機の通信/推論負荷やFFB遅延達成の保証ではない。

## 反映後の確認手順（まだ実施しない段階）

今回の変更をcommit/push等で送受信PCへ反映してから行う。ここでは外部Git操作や実反映は実行していない。

1. **matsunuc**: 普段映像送信を起動しているリポジトリで `src/webrtc_stream.py` と新しい `src/driver_odometry_observation.py` を反映。
2. **GPUPC**: `src/driver_telemetry_recording.py` と新helperを反映。UI本体は前回版のままでよい。片側だけを反映した場合、旧/不正metadataとして記録され、今回の観測が確認できないことがある。

構文確認はカメラなしで可能。senderのリポジトリrootで:

```bash
python3 -m py_compile src/webrtc_stream.py src/driver_odometry_observation.py
```

GPUPCで:

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 -m py_compile src/driver_telemetry_recording.py src/driver_odometry_observation.py
```

双方へ反映できた後に、従来の送受信を通常終了して新コードで起動する。機体を停止したまま、ハンドル/ペダル/WASDは操作しない。senderのIP/device/ROS topicは従来値を使い、推測で変更しない。新しいコーン撮影/校正/走行/画面録画は不要。

GPUPCの通常ROS/Qt端末で、記録だけの独立確認:

```bash
cd /home/hsr/yopi_ws/RICHO-theta
THETA_UI_NO_VENV=1 python3 src/webrtc_receive_ui.py \
  --cam-width 1280 --cam-height 720 \
  --telemetry-record-dir recordings/2026-11-16/received_telemetry_odom_r01
```

通常native送信を接続して10〜20秒後、UIを正常終了。距離推論を起動しないため距離欄は出ない。元odometryが届いていなければそれが記録で分かるので、0を変化させるために機体を動かさない。

```bash
python3 -m json.tool recordings/2026-11-16/received_telemetry_odom_r01/telemetry_recording_summary.json
test ! -e /home/hsr/Downloads/received_telemetry_odom_20261116_r01.tar.xz && tar -cJf /home/hsr/Downloads/received_telemetry_odom_20261116_r01.tar.xz -C recordings/2026-11-16 received_telemetry_odom_r01
```

3ファイルのarchiveを提出すれば、callback有無・元stamp進行/反復・frame・sender内ageを確認できる。既存directory/archiveは削除せず全箇所を新しいr名へ統一する。今回のコードをまだ受け取っていないPCで旧patchを再適用して回避しない。

## ローカル再現

未使用出力名を指定。実ROS/RTCサーバは起動しない。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/odometry_metadata_r01/check.py \
  --output-dir Experimental_results/2026-11-16/odometry_metadata_r01/results_r03 \
  --raw-output-dir recordings/2026-11-16/odometry_metadata_synthetic_r03

env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_driver_odometry_observation.py tests/test_driver_telemetry_recording.py \
  tests/test_driver_motion_integration.py tests/test_receiver_telemetry_live_audit.py \
  tests/test_driver_motion_shutdown.py tests/test_driver_motion_presentation.py \
  tests/test_driver_motion_time_join.py tests/test_driver_motion_handoff.py \
  tests/test_driver_motion_spatial.py tests/test_driver_body_display_guard.py \
  tests/test_driver_motion_bridge.py tests/test_body_display_range_audit.py
```
