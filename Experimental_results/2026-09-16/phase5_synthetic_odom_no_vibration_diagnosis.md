# Phase 5 実カメラ・模擬ODOM試験の無振動診断

## 結論

18:50アーカイブの追診により、Kobuki PCからハンコン接続PCへのactive指令9件はすべて配送されたが、全件が`invalid_request:future_message`でadapterに拒否されたと確認した。従って少なくともこのdry-run再試験の直接の失敗箇所は時刻妥当性チェックであり、未配送や物理強度不足ではない。両PCの時計・時刻同期状態を確認するまではhardware試験に進まない。

初回の無振動試験では、操作者はG923の振動を感じなかった一方、Kobuki PCの録画で青箱認識、TTC警告、FFB active指令の生成まで成立した。初回のハンコン接続PCのadapterログには起動とshutdown以外の状態遷移がなく、rosbagにも指令は記録されていなかったため、その試験で指令が届かなかった理由は事後には確定できない。`collision_ffb_publish_success=1`はローカルpublisherの送信呼び出し成功を表し、相手PCへの到着や物理出力を保証しない。

## 入力と完全性

- 録画: `/home/robo25/Downloads/202609161750.tar.xz`
- SHA-256: `56e8b221db4cab057fe87f0b38edbba0c8678f38b42847e0535f190fff2af10e`
- session: `phase5_camera_synthetic_odom_r01_20260916_174710_016`
- 実験条件: 実カメラ、停止したKobuki、模擬ODOM、v7 triple設定
- 録画フレーム: 1,191（raw/BEV/detectionの動画フレーム数とCSVが一致）
- 実効FPS: 29.929、青箱検出・観測採用・追跡・ODOM受信: 各100%
- 処理時間p95: 28.83 ms

これらの完全性・処理指標は[`phase5_synthetic_odom_live_analysis/analysis_report.md`](phase5_synthetic_odom_live_analysis/analysis_report.md)に記録した。同レポートの`DIAGNOSTIC`は、条件別の正式要件CSVを指定していないことを意味し、解析失敗ではない。

## ライブCSVから確定できること

| 項目 | 結果 |
|---|---:|
| 録画時間 | 39.790秒 |
| 模擬ODOMの`linear.x=0.25 m/s`を記録したフレーム | 100 |
| 衝突経路内と判定したフレーム | 100 |
| TTCが計算されたフレーム | 100 |
| 最小TTC | 3.534秒 |
| 確定WARNING | 116フレーム、進入5回 |
| FFB active指令 | 32フレーム |
| FFB publish失敗 | 0フレーム |

最初のWARNINGは録画開始から約8.007秒、FFB active指令は同じフレーム240で発生した。約31.557秒からはtriple cadenceの3つのON区間とOFF区間が記録されている。従って、無振動の主因を「カメラが青箱を検出しなかった」「TTC警告が生成されなかった」とは説明できない。

模擬ODOMの`0.25 m/s`と`0.0 m/s`が、警告区間内でも数フレーム間隔で交互に現れた。速度0のpublisherが残ったまま速度0.25のpublisherを追加した可能性があるが、録画CSVのみではpublisher数を確定できない。再試験時は`/odom`のPublisher countを常に1にする。

## ハンコン接続PCの証拠

- rosbagアーカイブ: `/home/robo25/Downloads/202609161800.tar.xz`
- SHA-256: `ebb9ac6554a88cd9ffc0dbd6ba269fcafa4f805d2f7c6298710f26179c5ac181`
- `metadata.yaml`上のmessage_count: **0**。登録されたtopicは`/collision/ffb_status`のみで、`/odom`と`/collision/ffb_command`は登録されていない。ただし、bag起動コマンドは未確認なので、この2 topicを録画対象に指定したかは不明である。
- SQLite実体でも`messages`は0行、`topics`は`/collision/ffb_status`の1行だった。
- 提示されたadapterログは17:36:21 JSTの`mode=hardware`起動と18:02:27 JSTの`reason=shutdown`停止のみ。17:47開始の録画時間を含むが、`action=apply`、通信異常、watchdog発火は記録されていない。

adapter実装は受信コマンドごとにstatusをpublishする。したがって、adapterログとbagがともに空であることは、少なくとも試験中の警告指令がadapterへ届かなかったことを強く支持する。shutdownのstatusはbag停止後だった可能性がある。bagに`/odom`と`/collision/ffb_command`がないことだけから、ネットワーク障害とは断定しない。

## ROSドメインの訂正

ユーザーが既存環境のドメインは`ROS_DOMAIN_ID=88`だと確認し、88でのPC間`/phase5/link_test`受信は成功した。また、無振動試験時も両PCのドメインは一致していたとの申告を受けた。以前の「ドメイン不一致が最有力」という判断は撤回する。提示されたコマンド文字列と実行時の環境には食い違いがあるため、どちらの値で試験したかを録画metadataだけでは復元できない。重要なのは、一般的なString topicのPC間通信が成功しても、実際のFFB topicの発見・配送まで保証されない点である。

その後、ハンコン接続PCのシェルでbest-effort/volatileの`ros2 topic echo --once /collision/ffb_command`を実行し、`source=bird_eye`、`sequence=202`、`risk_level=0`、`active=false`、`reason=no_alert`のCLEAR指令を受信した。これにより、その時点の`bird_eye.py`からハンコン接続PCのシェルまで、実際のFFB型・topic・QoSでの配送は確認できた。ただし、以前のhardware adapterプロセスが同じドメインで起動していたことまでは証明しない。`.bashrc`の既定値も、すでに起動したプロセスの環境を書き換えない。旧adapterが終了済みなら、実行時ドメインの事後確認はできない。

さらにハンコン接続PCで`output_mode=dry_run`のadapterを起動し、`/collision/ffb_status`に`source=bird_eye`、`sequence=10481`、`action=none`、`command_active=false`、`output_active=false`、`reason=inactive:clear`、`fault=false`を確認した。従って、その時点では実際のFFB指令がadapterへ届き、statusもpublishされている。これはCLEAR（非警告）だけの確認であり、WARNING中のactive配送やG923物理出力の確認ではない。過去の無振動試験時に何が違ったかは依然として確定していない。

追加のdry-run status抜粋では、CLEAR受信8件に加え、`invalid_request:future_message:age=-0.052673`～`-0.060311`秒のfaultが10件確認された。これはadapterの既定`future_tolerance_sec=0.05`秒を超えて、指令の送信時刻がadapter時計より未来と判定されたことを意味する。両PCの時刻ずれが強く疑われるが、時刻同期の状態は未確認であり、正確な差はこの抜粋だけでは算出できない。抜粋中の`output_active=true`は0件で、active WARNINGがadapterを通過した証拠はない。安全しきい値を緩めたりhardwareへ進めたりせず、両PCの時刻同期を確認する。

同時に添付された`202609161800.tar.xz`は前回確認済みのSHA-256 `ebb9ac6554a88cd9ffc0dbd6ba269fcafa4f805d2f7c6298710f26179c5ac181`と一致し、message_count=0の旧bagである。今回のdry-run試験を記録した新しいbagではない。

## 18:35アーカイブによるdry-run再試験の追診

ユーザーが正しい録画として`/home/robo25/Downloads/202609161835.tar.xz`を提示した。SHA-256は`da9f790bc896a363c0a3fd07cf0600e74a525ee45a4d1aeb693005b5d75f2c75`。中身は`phase5_camera_synthetic_odom_dryrun_r02_20260916_183117_154`のカメラ録画（metadata、detections.csv、raw/BEV/detection動画）であり、ハンコン接続PCのrosbagやadapter statusは含まれない。完全性と処理指標は[`phase5_synthetic_odom_dryrun_r02_analysis/analysis_report.md`](phase5_synthetic_odom_dryrun_r02_analysis/analysis_report.md)に保存した。

| 項目 | 結果 |
|---|---:|
| 録画 | 402フレーム、13.396秒、実効29.997 FPS。動画とCSVは一致 |
| 青箱検出・観測採用・追跡 | 各402/402フレーム |
| 模擬ODOM 0.25 m/s | 123フレーム、録画開始6.661～10.724秒 |
| 確定WARNING | 123フレーム、6.732～10.787秒 |
| FFB active指令 | 10フレーム、sequence 1013～1026、録画開始6.732～7.155秒 |
| FFB publish失敗 | 0フレーム |

activeの10フレームはtriple cadenceの3つのON区間（4+3+3フレーム）に対応し、要求振幅は0.25だった。ハンコン側の安全上限を0.05に設定した場合、受理されれば0.05に制限されるはずだが、`collision_ffb_publish_success=1`はKobuki PC側でのpublish呼び出し成功に限る。adapterへの到着、dry-runでの受理、物理振動は証明しない。ODOMは0.25 m/s区間では連続して受信され、速度0と0.25の混在はこの録画には認められない。録画前半と後半にはODOM未受信のフレームが計122件あり、Publisher停止後のCLEAR復帰も記録されている。

提示されたdry-run status抜粋は2026-09-16 18:32:00～18:32:02 JST、sequence 2120～2166。一方、この録画は18:31:17開始、約18:31:30終了で、active指令は約18:31:24、sequence 1013～1026。したがってstatus抜粋は録画終了後のものであり、録画中のactive指令と同一sequenceでは突き合わせられない。抜粋のCLEAR受信とfuture_message faultは有効な診断情報だが、active区間のadapter出力の証拠にはならない。`output_active=true`の有無を判定するには、ハンコン接続PCでsequence 1013～1026付近のstatus記録が必要である。

## 18:50アーカイブ：録画riskのPC間dry-run再生

ユーザーが`/home/robo25/Downloads/202609161850.tar.xz`を提示した。SHA-256は`03a93d193f399ae8df6dfe6a4145f3319fac807473c878677746b9b180ced353`。中のCSV・JSON・レポートは[`phase5_dryrun_crosspc_replay_r03/`](phase5_dryrun_crosspc_replay_r03/)へ展開した。入力は上記18:35録画の`detections.csv`、送信元はKobuki PC、adapterはハンコン接続PCの`dry_run`である。

| 指標 | 結果 |
|---|---:|
| publishした指令 | 403件、うちactive 9件 |
| 受信したstatus | 382件 |
| future_message fault | 375件 |
| stale_message fault | 1件 |
| faultなし | 6件、すべてinactive:CLEAR |
| active status | 0件 |
| 最大適用強度 | 0.000 |
| 自動判定 | FAIL |

active指令のsequenceは201～203、206～208、211～213の9件。対応する9件のstatusは**すべて受信され**、いずれも`invalid_request:future_message`で停止した。したがって今回のactive経路については、ROS未配送や警告未生成ではなく、adapterの時刻妥当性チェックによる拒否が直接の失敗箇所である。375件のfuture faultで観測されたageは平均`-0.06284`秒、範囲`-0.06407`～`-0.05116`秒。既定の許容`-0.05`秒を越える。これは送信・受信PC間の時計のずれと整合するが、両PCの時刻同期状態や発生源はまだ未確認である。安全なしきい値を変更せず、両PCの時刻同期状態・使用中の時刻同期サービス・offsetを確認してから、同じdry-run再生で再検証する。hardwareは起動しない。

追加確認では、ハンコン接続PC `hsr-Alienware-m16-R2` とKobuki PC `matunuc-NUC13ANHi5`の両方で`timedatectl status`が`System clock synchronized: yes`、`NTP service: active`を表示した。両PCに`chronyc`はインストールされていない。この表示はNTP同期が有効であることを示すが、両PC間の時刻差が50 ms未満であることまでは保証しない。送信側は`node.get_clock().now()`で指令をstampし、adapter側も`node.get_clock().now()`を用いて`age = receiver_now - command_stamp`を判定する実装である。次は各PCの`timedatectl timesync-status`等から同期先・offsetを確認する。

両PCの`timedatectl timesync-status`は、ハンコン接続PCがoffset `-26.020 ms`、delay `221.579 ms`、jitter `42.830 ms`、Kobuki PCがoffset `-93.338 ms`、delay `351.943 ms`、jitter `61.386 ms`だった。offset推定値の差は`67.318 ms`で、dry-runで観測された`future_message`の平均age `-62.842 ms`と近い。各PCは異なる`ntp.ubuntu.com`のIPへ同期しており、このログはPC間時刻差が主因であるという仮説を強く支持する。ただし、NTPのoffsetは各サーバーに対する測定値であり、同時刻の直接的なPC間時計差ではない。特にdelay/jitterが大きいため、数ms精度の証明としては使わない。次はhardwareを停止し、時刻サービスを再同期させてからoffsetとdry-run結果を再測定する。効果がなければ低遅延の共通時刻源を検討する。

両PCで`systemd-timesyncd`を再起動した直後は`Packet count: 0`で、新しいNTPサンプルはまだなかった。約19:05 JSTの再確認では、両PCとも`Packet count: 2`となり、ハンコン接続PCのoffsetは`+21.450 ms`（jitter `8.107 ms`）、Kobuki PCのoffsetは`-6.508 ms`（jitter `2.459 ms`）だった。offset推定値の差は`27.958 ms`に縮まった。ただしこれは直接のPC間測定ではなく、FFBの受理を保証しない。次はhardwareを使わず、同じ録画riskをdry-runで再生して`fault=0`、active statusあり、最終inactiveを確認する。

## 再同期後のPC間dry-run再生（r04）

再同期後、同じ録画riskをKobuki PCから送信し、ハンコン接続PCのdry-run adapterで再試験した。ユーザー提供の[`replay_report.md`](phase5_dryrun_crosspc_replay_r04/replay_report.md)と[`adapter_status.csv`](phase5_dryrun_crosspc_replay_r04/adapter_status.csv)を保存した。レポートの自動判定は**PASS**。指令403件のうちactiveは9件、statusは402件、active statusは9件、faultは0件、最大適用強度は安全上限の0.05、最後のstatusはinactiveだった。status CSVでもactive sequence 201～203、206～208、211～213の9件すべてで`action=apply`、`output_active=1`、`requested=0.25`、`applied=0.05`を確認した。CLEARのsequence 26だけstatus CSVに見当たらないが、activeの欠落はない。

これにより、録画riskからのFFB指令生成、PC間ROS配送、時刻妥当性チェック、dry-run adapterでの強度制限と停止までは成立した。G923への物理出力はdry-runでは行っていない。また、生カメラを動かした同一試験でのadapter受理を今回直接確認したわけではない。次は実カメラ＋専用模擬ODOMのライブ構成をdry-runで記録し、同じ判定条件で通ることを確認する。

## 次の切り分け

1. 時刻同期状態を再試験直前に確認する。失効・未来時刻の安全しきい値は変更しない。
2. 実カメラ＋専用模擬ODOM `/phase5/mock_odom` のライブ試験をdomain 88のdry-run adapterで実施し、active status、fault 0件、最終inactiveを記録する。速度0と0.25のpublisherは同時起動しない。実ロボットの`/odom`へ模擬速度を注入しない。
3. ライブdry-run合格後に限り、G923物理試験を安全上限0.05のまま検討する。録画riskのdry-run PASSだけを物理出力成功と取り違えない。

時刻同期とdry-runの診断中はhardware adapterを起動しない。安全条件を満たすまで走行試験や強度引き上げにも進まない。
