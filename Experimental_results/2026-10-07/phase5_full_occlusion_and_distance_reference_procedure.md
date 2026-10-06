# 2026-10-07 長い完全遮蔽・距離参照の収録手順

## 明日の優先順位

**Kobukiを走らせず、adapterはdry_runのまま、長い完全遮蔽の録画を先に行う。** 10/06のオフライン候補は本番へ入っていないので、カメラは従来のv12設定で収録し、あとから同じ動画を固定候補で比較する。

1. 共通確認と準備。
2. 可視→完全遮蔽→復帰の30秒シナリオ。まずr01、収録成立を確認してr02・r03。
3. 余力があれば箱なし10秒、中央0.90／1.10／1.30 mの静止録画各20秒。
4. カメラ原本、両PC bag、mock ODOM CSV、実測メモを保存・提出して判定。

本番設定の調整、FFB強度変更、hardware adapterの起動、Kobuki実走行はこの手順に含めない。明日実施できなければ日付と出力先を変更して使う。

## 0. PC・配置・停止条件

| 呼び方 | ホスト | 役割 |
|---|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5` | カメラ、カメラアプリ、relay、専用mock ODOM |
| ハンコン接続PC | `hsr-Alienware-m16-R2` | challenge、dry_run adapter、bag。今回はG923を触る必要なし |

- Kobukiは固定して停止。操縦系・keyopを起動しない。可能なら駆動電源を切り、カメラだけ使う。
- 模擬速度は`/phase5/mock_odom`だけへ送る。`/odom`や`/cmd_vel`へ送らない。模擬速度0.25 m/sは車体の走行指令ではない。
- 青箱は正面中央、カメラ直下から箱手前面の床との境界まで約1.0 m。カメラ高さ・傾き・箱向きを固定する。
- 青色でない大きい不透明な板を準備する。左右、上、下に箱の面・縁が残らないことをraw表示で確認する。車体やレンズに触れない。
- 一人なら板をすぐ動かせるよう配置する。二人なら一人がPC、もう一人が板を担当する。
- ダウンロード・圧縮・Drive同期は録画と同時に行わない。
- dry_runなのに振動、予期しない車体移動、複数adapter、模擬ODOM複数publisherがあれば中止する。

## 1. 最新版と環境

Kobuki PCは、これまでのログどおり`~/theta_ws/src/bird_eye.py`がある配置を想定する。実際に`~/theta_ws/RICHO-theta/src/`へcloneしている場合だけ、以下の各`cd ~/theta_ws`を`cd ~/theta_ws/RICHO-theta`へ読み替える。環境の`source`は絶対に`~/theta_ws/theta-env/bin/activate`を使用する。

Kobuki PC：

```bash
cd ~/theta_ws
git status --short
git pull --ff-only
git log -1 --oneline
test -f src/run_field_experiment.py
test -f src/publish_mock_odom_scenario.py
test -f src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json
```

未コミット変更があれば勝手に破棄しない。clean gitへ整理するまでpreflightを進めない。今回のPUSHはカメラ側リポジトリのみで、FFB側の新たなbuildは不要。ハンコン接続PCでは既に使用したv12対応install環境を使う。

Kobuki PCの**K1～K4の各ターミナルで**、最初に次を実行する：

```bash
cd ~/theta_ws
source /opt/ros/humble/setup.bash
source ~/ffb/install/setup.bash
source ~/theta_ws/theta-env/bin/activate
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

ハンコン接続PCの**H1～H3の各ターミナルで**、最初に次を実行する：

```bash
cd ~/yopi_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0
```

`source`でエラーがあれば次へ進まない。domain設定はsourceの**後**に行う。

## 2. H1：dry_run adapter（ハンコン接続PC）

まずプロセスを調べる。

```bash
pgrep -af collision_ffb_node
```

既存adapterがあれば元のターミナルでCtrl+Cして出力停止を確認する。二重起動しない。なければ次を実行する：

```bash
ros2 run oit collision_ffb_node --ros-args \
  -p output_mode:=dry_run \
  -p freshness_mode:=challenge \
  -p max_magnitude:=0.05 \
  -p challenge_max_age_sec:=0.1 \
  -p challenge_rate_hz:=50.0 \
  -p watchdog_timeout_sec:=0.1
```

`mode=dry_run`、`freshness=challenge`を確認し、このターミナルは起動したままにする。処理が終わっても自動的にはプロンプトへ戻らない。

H3で確認：

```bash
ros2 param get /collision_ffb_node output_mode
ros2 topic info /collision/ffb_status -v
ros2 topic info /collision/ffb_challenge -v
```

output_modeがdry_runで、statusとchallengeのpublisherが各1であること。`disabled`や`hardware`なら中止する。

## 3. K2：同じpublisherで待機→模擬速度→停止

試行番号はまずr01。ログはGit管理外の録画フォルダへ書くため、preflight直前にGitがdirtyになることを避けられる。

```bash
python3 src/publish_mock_odom_scenario.py \
  --topic /phase5/mock_odom \
  --lead-in-sec 5 \
  --motion-sec 20 \
  --lead-out-sec 5 \
  --speed-mps 0.25 \
  --rate-hz 30 \
  --wait-for-enter \
  --output-csv src/recordings/2026-10-07_full_occlusion/phase5_full_occlusion_mock_odom_r01.csv
```

`[WAIT]`で速度0を送りながら待つ。**まだEnterを押さない。** 別publisherへ切り替えず、この一つのプロセスを最後まで使う。

K4で確認：

```bash
ros2 topic info /phase5/mock_odom -v
ros2 topic echo /phase5/mock_odom --once
git status --short
```

Publisher count 1、待機速度0、Git cleanを確認。古い模擬送信器が残っていれば終了する。

## 4. H2・K1：両PC bag

bagはclone内部でなく`~/ffb_recordings/`へ保存する。metadataによるGit dirtyを避け、録画原本を結果CSVと混ぜない。同じ名前のbagが既にある場合は上書きせず試行番号を増やす。

H2（ハンコン接続PC）：

```bash
mkdir -p ~/ffb_recordings/2026-10-07
ros2 bag record \
  -o ~/ffb_recordings/2026-10-07/phase5_full_occlusion_hsr_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /phase5/mock_odom
```

K1（Kobuki PC）：

```bash
mkdir -p ~/ffb_recordings/2026-10-07
ros2 bag record \
  -o ~/ffb_recordings/2026-10-07/phase5_full_occlusion_kobuki_r01 \
  /collision/ffb_challenge \
  /collision/ffb_intent \
  /collision/ffb_command \
  /collision/ffb_status \
  /collision/ffb_relay_diagnostics \
  /phase5/mock_odom
```

`oit_interfaces not found`が出たら、同じターミナルでROS・FFB installのsourceをやり直す。カメラ前はintent等が未発行でもよいが、カメラ起動後に対象topicのsubscriptionが成立することを確認する。

## 5. K3：カメラとrelay

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --record-dir src/recordings/2026-10-07_full_occlusion \
  --experiment-label phase5_full_occlusion_dryrun_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

preflightが全PASSしてからGUIが開く。git/ODOM検査を迂回しない。起動直後のchallenge安定待ちが終わってから次へ進む。

1. raw表示で青箱の全体・底部が見えることを確認する。
2. 青箱の有効測定・追跡が1秒以上連続して成立することを確認する。未検出や範囲外のままなら録画シナリオを始めない。
3. 板で試しに箱全体を覆い、上下左右に縁が残らないことを確認する。板を外し、再び有効測定を1秒以上待つ。
4. GUI録画を開始してからK2へ戻り、Enterを1回押す。

## 6. 30秒の操作タイムライン

時刻の起点は**K2でEnterを押した時点**。録画はその前から動いているため動画の経過時刻とは異なる。シナリオCSVの実送信時刻が照合用になる。秒数は人手目安でよく、速度は自動送信される。

| Enter後の目安 | 模擬速度 | 箱の状態・操作 |
|---|---:|---|
| 0～5秒 | 0 | 箱を見せたまま、触らない |
| 5～10秒 | 0.25 m/s | `forward_0p25`表示後、まず有効測定を約5秒維持 |
| 10～13秒 | 0.25 m/s | 板で全体を隠し、約3秒維持（完全遮蔽1） |
| 13～18秒 | 0.25 m/s | 板を外し、箱を約5秒見せる。有効測定の復帰を確保 |
| 18～21秒 | 0.25 m/s | 再び全体を隠して約3秒（完全遮蔽2） |
| 21～25秒 | 0.25 m/s | 板を外して箱を見せる |
| 25～30秒 | 0 | `final_stop`、箱は見せたまま |

完全遮蔽開始・終了はあとからraw全frameで確定する。人手の操作時刻やUNKNOWN表示だけで完全遮蔽正解ラベルにしない。速度0へ切り替わった後の遮蔽だけでは前進中UNKNOWNの条件を満たさない。

実Kobukiは動かず箱も固定なので、カメラ相対位置は変わらない。これは模擬ODOMによる衝突状態・遮蔽・通知の統合確認であり、実接近のTTC精度や物理振動の試験ではない。WARNINGが必ず出るとは仮定せず、有効測定・UNKNOWN・復帰を別に採点する。

## 7. 終了・r02/r03

1. K2がシナリオ完了し、最後に速度0を送ったことを確認。
2. GUI録画を停止し、K3を正常終了。relayも終了したことを確認。
3. H3で最終出力を確認してから、H1 adapterをCtrl+Cしshutdownを記録する。
4. K1・H2 bagをCtrl+Cし、終了・metadata書き出しを待つ。先にbagを止めるとshutdownが保存されない。

H3での確認コマンド：

```bash
ros2 topic echo --once \
  --qos-reliability best_effort \
  --qos-durability volatile \
  /collision/ffb_status \
  oit_interfaces/msg/CollisionFfbStatus
```

`output_mode: dry_run`、`output_active: false`、`applied_magnitude: 0.0`、`fault: false`を確認する。active中の1件だけを取得できなくても、bagから後で評価できるので追加で危険操作をしない。

Kobuki PCでシナリオCSV確認：

```bash
tail -3 src/recordings/2026-10-07_full_occlusion/phase5_full_occlusion_mock_odom_r01.csv
```

末尾がfinal_stop、速度0、publish_success=1であること。待機行があるので行数は一定ではない。

r01のraw動画に2～3秒の完全遮蔽があり、模擬速度区間が合っているか確認する。成立していれば同じ条件でr02・r03を収録する。各コマンドの`r01`を**CSV・カメラlabel・両bagのすべて**でr02/r03へ変更し、H1を再起動する。K2は毎試行、新しいCSVで待機から開始する。隠し方を変更した場合は変更内容をメモする。

全3試行をまとめて提出してよい。条件が不成立のr01を消さず、再試行は新しい番号で保存する。

## 8. 余力がある場合：静止距離の参照収録

完全遮蔽の収録を優先し、時間がなければここは次回へ回す。Kobukiは同じ姿勢で停止、hardwareには進まない。

| label | 条件 | 録画時間 |
|---|---|---:|
| `distance_reference_no_box_r01` | 青箱なし、同じ床・照明 | 約10秒 |
| `distance_reference_center_z0p90_r01` | x=0、z=0.90 m | 約20秒 |
| `distance_reference_center_z1p10_r01` | x=0、z=1.10 m | 約20秒 |
| `distance_reference_center_z1p30_r01` | x=0、z=1.30 m | 約20秒 |

メジャーの起点はカメラ光学位置の床への直下。箱側は**手前面と床の境界の中央**。前後方向zを測り、平面斜距離や車体前端からの距離と混ぜない。x=0を合わせ、許容する設置の不確かさ（例1～2 cm）もメモする。カメラ高さ・取り付け角度・箱寸法・照明・床を記録し、可能ならメジャーと配置の写真を保存する。魚眼投影のどの表面点を選ぶかの差はあとで診断する。

完全遮蔽試験のK2・K3が残っていないことを確認する。K2で速度0だけのpublisherを起動：

```bash
ros2 topic pub -r 30 \
  /phase5/mock_odom nav_msgs/msg/Odometry \
  "{header: auto, child_frame_id: base_footprint, twist: {twist: {linear: {x: 0.0}, angular: {z: 0.0}}}}"
```

この静止参照では途中でpublisherを切り替えない。H1は上のdry_run adapterを再起動する。K3でまず箱なし：

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --record-dir src/recordings/2026-10-07_distance_reference \
  --experiment-label distance_reference_no_box_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

GUIで10秒録画し正常終了。その後、箱を0.90 mへ置いて次を実行する：

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --record-dir src/recordings/2026-10-07_distance_reference \
  --experiment-label distance_reference_center_z0p90_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /phase5/mock_odom \
  --odom-timeout-sec 10
```

同じコマンドのlabelだけ`distance_reference_center_z1p10_r01`、`distance_reference_center_z1p30_r01`へ変更し、各配置を実測して各20秒録画する。`--camera-frames 60`はpreflightのカメラ確認枚数で、録画秒数を制限する引数ではない。録画開始・停止はGUIで行う。

1.30 mで測定が範囲外でもそのまま保存する。GUIに合わせて箱を動かしたり、範囲・校正を変更しない。欠落・不採用も比較対象となる。終了後はカメラ、ゼロODOM、adapterを正常終了する。静止参照の最低提出物はカメラ原本と実測メモで、UNKNOWNの通信評価には前段の両bagを使う。

## 9. 圧縮・提出

**録画とbagをすべて終了してから**行う。既存アーカイブ名がある場合は新しい番号を使い、上書きしない。Kobuki PC：

```bash
tar -cJf ~/ffb_recordings/2026-10-07/phase5_full_occlusion_kobuki_r01.tar.xz \
  -C ~/ffb_recordings/2026-10-07 phase5_full_occlusion_kobuki_r01

tar -cJf ~/ffb_recordings/2026-10-07/phase5_full_occlusion_camera_all.tar.xz \
  -C src/recordings/2026-10-07_full_occlusion .
```

ハンコン接続PC：

```bash
tar -cJf ~/ffb_recordings/2026-10-07/phase5_full_occlusion_hsr_r01.tar.xz \
  -C ~/ffb_recordings/2026-10-07 phase5_full_occlusion_hsr_r01
```

r02/r03のbagも同様に圧縮する。カメラallには3試行と3つのODOM CSVを含める。元ディレクトリは削除しない。静止参照は別アーカイブでよい。

提出物：カメラall、各試行の両PC bag、設置距離・測定点・板操作のメモ。bagの原本metadataとdb3を一緒に含める。圧縮ファイルを解析PCの`Downloads/recoding/`へ移動／Driveからダウンロードし、ファイル名を知らせる。これらをGitへ追加しない。

## 10. 解析・評価（追加走行なし）

標準解析だけでは、完全遮蔽正解・challenge経路の配送・候補採用まで判定できない。今回は原本を渡した後、次の順で解析する。

1. raw動画の全frame対応・完全性を確認し、板の全遮蔽／部分遮蔽／可視／判定不能を、候補結果を見る前にラベル化する。
2. ODOM CSVとbagで模擬速度0.25中の完全遮蔽2～3秒、復帰後0.5秒以上の有効測定、最終停止を照合する。
3. ライブCSV・両bagでintent→command→dry_run status、fault、最終inactiveを評価する。
4. 同じ保存動画をbaseline＋固定S130 2方式で再計算し、新規検出・測定採用・予測track・喪失・復帰を分けて比較する。
5. 距離参照は不採用の推定値も残し、距離ごとの偏りとばらつきを比較する。データの同じ点で校正して採点することは避ける。

固定候補比較用の既存CLI（**展開済み録画フォルダ**を指定。アーカイブを直接指定するCLIではない）：

```bash
python3 src/compare_offline_box_contacts.py \
  --input src/recordings/2026-10-07_full_occlusion \
  --detector-config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json \
  --output-dir Experimental_results/2026-10-07/full_occlusion_frozen_comparison \
  --variants baseline seeded_s130_nearest seeded_s130_bottom \
  --freeze-from Experimental_results/2026-10-06/box_contact_candidates/provenance.json
```

これはROS・物理FFBなしのオフライン比較で、録画終了後にだけ実行する。別PCでは`--input`を安全に展開した録画フォルダへ変更する。3方式の設定をこの新しい録画に合わせ直さない。

最低限の評価条件は、画像で確認した長い完全遮蔽、前進模擬速度との重なり、未知状態を安全なCLEARへ隠さないこと、復帰、active配送と停止の記録である。不成立はNOT_EVALUATEDにし、部分遮蔽を完全遮蔽へ読み替えない。合格しても実接近・hardware・YOLO統合の安全認定とはしない。

本番へ候補を入れるか、新たな実走行へ進めるかは、今回の独立録画結果を確認してから別途判断する。
