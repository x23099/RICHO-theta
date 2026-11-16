# 2026-11-16 日報：実測3地点・受信運動記録・時計非依存のフレーム対応準備

## 1. 本日の到達点

**現在取付での1/1.5/2m表示を実測申告・全ログへ照合し、実odometryの受信・保存も確認した。** 距離・運動のオフライン受け渡し、表示説明、任意記録機能を実装した。後半は以前の時計問題とchallenge方式の実績を再確認し、PC間時計同期・時刻換算をFFBの必須条件に戻さない方針へ修正した。

送信PC内で画像取得以前のodom callbackを選ぶ独立部品まで実装・検証済み。**受信実画像との厳密な識別・runtime接続・車体座標変換・今回の距離からG923への接続は未完了。** 11/13の走行測距確認や過去のchallenge/G923成功を取り消したわけではない。

最終目標は[RESEARCH_GOAL.md](../RESEARCH_GOAL.md)：差動2輪の遠隔操縦で、同一スナップショットのω−Δ/ω/ω+Δを評価し、危険方向を重くする抵抗型リスク勾配FFB。単なる距離表示や接近振動だけへ目標を縮小しない。

## 2. 使用条件と実施主体

- 現地ユーザー：matunucのTHETA/ROS/Kobuki、GPUPC hsr-Alienware-m16-R2の既存WebRTC受信・GPU測距を使用。ユーザーがコード反映・実測・記録・archive提出を実施。
- 解析PC：robo25の本repositoryでarchive原本照合、オフライン実装、fake ROS/peer、メモリ内VP8 codec試験を実施。こちらから実ROS/カメラ/車体/G923/WebRTCサーバは起動していない。
- 距離はカメラ直下の床上点からコーン台座手前辺中央までの水平距離。未展開1280×720、前方左レンズ、指定native ROI、既存profileを維持。車体接触距離やbase_link位置ではない。
- 電源操作でカメラを取り外すため取付の完全再現を仮定せず、当日のsession/pinに基づく天板境界参照を使用。床幾何・独立実測精度の認定とは分離。
- source_freshness/physical_metric/controlling_distance/usable_for_ffb/published_to_rosは未認定falseを維持。操縦信号、既存FFBの期限/challenge/watchdog/arm/強度上限は変更していない。

## 3. 実測3地点と全ログ監査

根拠：[画面と実測申告](../Experimental_results/2026-11-16/body_display_range_check_r01/README.md)、[正式全ログ照合](../Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json)。同session e52bb32f03d6488ebf37d769f46ec37a、pin5186、body-review世代1。

| 実測申告m | 画面表示m | 表示−申告cm | 元frame |
|---:|---:|---:|---:|
| 1.000 | 1.005 | +0.5 | 34957 |
| 1.500 | 1.480 | −2.0 | 45469 |
| 2.000 | 1.960 | −4.0 | 46432 |

3画面の値は主ログ・表示レビュー・bridge・別比較の該当frameと一致した。今回3点の最大差4cmは、常時±4cmや5mm精度を保証する結果ではない。実測の不確かさ・静止区間全体は不明で、3点へ合わせた再校正は行っていない。

| 全ログ確認 | 結果 |
|---|---:|
| 必要原本 | 16ファイル完備 |
| 主/レビュー/bridge | 各51,202件 |
| 別比較 | 51,200件 |
| 最終表示許可 / 保留 | 19,297 / 31,905件 |
| 許可値の元数値との一致 | 19,297/19,297 |
| load後の追加保留 | 自己遮蔽22＋参照範囲外5＝27件 |
| load後レビュー完了age P95/最大 | 19.00/108.06ms |
| 主完了→レビュー追加経過P95/最大 | 0.51/1.92ms |
| 終了 | 主/比較とも正常終了、強制killなし |

各時間は記録された処理区間で、カメラ露光〜GUI/FFB総遅延ではない。元主数値全体19,355件と最終表示許可19,297件を混同しない。

感度計算は保存3点のy±1px・高さ±1cm・対象方向法線±1度を固定条件で評価。2m地点では各約3.90cm/3.40cm/最大13.42cmの変化があり得た。これは仮定の一因子感度で、今回の偏りの原因・真の取付誤差ではない。[感度の根拠](../Experimental_results/2026-11-16/range_sensitivity_r01/README.md)。

## 4. 実装・オフライン受け渡し

- [日本語表示案内](../Experimental_results/2026-11-16/motion_panel_guidance_r01/README.md)：対象ROI、no_candidate等の保留理由、カメラ直下距離/非制御注意を追加。ユーザーがpush/pullしGPUPC端末で出力を確認。GPUPCへ解析PCの絶対パスを入力したエラーはパスの違いで、測距故障ではない。
- [距離受け渡し](../Experimental_results/2026-11-16/motion_range_handoff_r01/README.md)：51,202件をsession/frame/元時刻・参照付きで往復し、19,297数値と31,905保留を保持。古い値の期限切れ/無効入力でキャッシュを消す。スカラーから車体XYや追跡IDを作らない。
- [条件付き光学床面ベクトル](../Experimental_results/2026-11-16/motion_spatial_inputs_r01/README.md)：19,297点を復元し、長さが元距離へ丸め誤差内で一致。車体XYではなく、現在取付のR/t・車幅・障害物点の意味が別途必要。
- [offline運動形式/結合](../Experimental_results/2026-11-16/motion_time_join_r01/README.md)：整数ns元stamp・時計/frame/受信・有効性付き形式と保留検査。合成20ケース成功、実運動を含まない旧距離ログで実ペア0を維持。clock-binding必須のこの方式を、後半の方針変更で検査だけ緩めて流用していない。
- [任意telemetry記録](../Experimental_results/2026-11-16/receiver_telemetry_recording_r01/README.md)：既定OFF、有界queue/専用writer/件数容量上限/排他出力/有限終了。callbackでディスクIOを行わず、記録失敗を操縦へ波及させない。
- [元odom観測](../Experimental_results/2026-11-16/odometry_metadata_r01/README.md)：元stamp/frame/受信済み状態・callback連番/age・符号付きv/ωを追加。旧UIの初期0と受信した実際の0を区別。旧senderとのv1/v2互換を維持。

## 5. telemetry記録の切り分けと到達点

| 提出/段階 | telemetry件数 | 判明事項 |
|---|---:|---|
| 最初の旧形式受信 | 2,208 | 保存成功。ただし速度0だけでは初期値/実受信を区別できない |
| odom r01 | 0 | GPU summaryもoffered0。実記録がない段階で、センサ値0ではない |
| odom r02 | 3,222 | 全件not_received。保存経路の成功と元callback未受信を分離 |
| odom r03 | 2,045 | 全件受信済み、元stamp進行、受信したv/ωが0 |
| sender clock r01 | 1,177 | 全件clock sampled、同一senderのodom観測と一致 |

[odom r03正式監査](../Experimental_results/2026-11-16/odometry_metadata_received_audit_r01/README.md)：87.160979秒、peer_begin込み2,046events、queued=written、落ち/拒否/破棄0、正常closed。CLI診断ではkobuki publisherとtheta subscriberがRELIABLE/VOLATILEで存在しechoも受信できたが、r02→r03の解消原因はログ不足で断定していない。QoS変更が必要だったとはしない。

[受信→offline形式](../Experimental_results/2026-11-16/received_motion_handoff_r01/README.md)でr03全2,045件を往復し元値・stamp・frameを保持。measurement_valid/source_clock_idは不明のまま。旧距離と別sessionのため実結合試行0、実ペア0。

## 6. 時計起源の確認と方針変更

ユーザー出力でkobuki/送信nodeともuse_sim_time=false、/clockなし。貼付ソースは`node.get_clock().now()`→odom update→header stamp→publishの連鎖を含み、上部の再送は不要だった。示されたstampはdriver更新時計で、firmwareの計測時刻そのものではない。現在実行binaryとの独立一致までは未確認。[根拠](../Experimental_results/2026-11-16/spacetime_evidence_r01/kobuki_stamp_source_evidence.json)。

[sender ROS時計bracket](../Experimental_results/2026-11-16/sender_ros_clock_bracket_r01/README.md)を追加し、既存odomと同sender IDでinteger monotonic前後・ROS now・世代/設定/逆行を観測。receiver v3形式へ任意保存し、旧v1/v2も維持した。

[実記録監査](../Experimental_results/2026-11-16/sender_ros_clock_live_audit_r01/results_r02/audit.json)：

| 指標 | 実記録結果 |
|---|---:|
| telemetry / 保存event | 1,177 / 1,178 |
| 観測時間幅 / 平均Hz | 50.329734秒 / 23.3659Hz |
| sampled / 同sender scope一致 | 各1,177件 |
| ROS逆行 / 設定変化 | 0 / 0件（観測された範囲） |
| ROS読出しbracket中央値 / P95 / 最大 | 102.126 / 165.5674 / 287.649μs |
| 受信間隔最大 | 58.617648ms |
| 受信→writer timestamp最大 | 4.081418ms |
| queued / written / queue・busy落ち | 1,178 / 1,178 / 各0 |
| offered / rejected | 1,180 / 2（末尾拒否理由は未記録） |
| 終了 | closed、error=null、writer_done/shutdown_complete=true |

**287.649μsはPC間同期精度ではない。** 受信→writer差もdisk完了や通信遅延ではない。一定offset仮定で区間交差が非空でも、真clock精度/ドリフト/header時計同定へ昇格しない。

その後ユーザーから過去の時計問題の指摘を受け、[9/17設計](../handover/clock_independent_ffb_design_20260917.md)と[9/24日報](2026-09-24_daily_report.md)を確認。約51〜58msの時計差でFFBが拒否され、受信側monotonicによるchallenge方式へ変更し、後日G923まで確認した実績を再確認した。**予定していたPC間4timestamp対応の新規実装は中止し、時計同期をFFBの必須条件に戻さない。** 今回の時計観測は診断資料として残す。

## 7. 時計非依存の送信元部品と、受信画像識別の課題

[sender_frame_motion_r01](../Experimental_results/2026-11-16/sender_frame_motion_r01/README.md)に、同sender monotonicの画像read-return以前に観測した最新callbackを選ぶ独立部品を実装。実測停止0を保持し、未来値/無効値/反復stamp/古さ/欠落/drop/競合時に旧値で救済しない。sender混在・順序逆転はinstanceを退役する。呼出し時の有界policyは試験値で、実機採用やFFB期限ではない。

実aiortc1.14.0のTimestampMapperでは、先頭frameが欠けると次のcaptureがreceiver PTS0になる。実VP8 codecではframe.opaqueの任意IDは受信画像へ残らない。**送受信の連番や先頭PTS0を同一視するだけでは誤対応する**ことをローカルに確認した。ネットワーク実パケット欠落試験ではない。

部品はruntime未接続で、受信実画像の識別は未完了。challengeは指令の期限検査で、画像/運動を新鮮にする機能ではない。過去のclock joinerの条件を外して実入力へ昇格する変更はしていない。

## 8. 検証

| 検証枠 | 成功件数 | 根拠/備考 |
|---|---:|---|
| sender ROS bracket実装時の関連suite | 252 | verification.json、8.55秒 |
| 実clock提出監査を含む関連suite | 84 | 新監査10を含む、1.13秒 |
| sender-frame部品/既存odom・操縦・FFB・codec等 | 174 | 新規30を含む、3.49秒 |
| sender-frame正式check | 30 | skip0、合成4例保存 |

suiteは相互重複するので合計成功件数として加算しない。成功済みで変更のない検証は再利用した。操縦/ROS/keyboardの固定AST、旧距離表示12ソースSHAを維持。構文とgit diff --checkも確認。実露光同期・現取付車体TF・今回の実FFB接続・実走行時の新部品性能は未検証。

## 9. 成果物・原本・Git

[代表資料3点](../Experimental_results/2026-11-16/report_assets/README.md)は、当日pin元画像のbyte同一コピー、実測3地点差の図、時計読出しbracket統計図。CSV/生成script/入力出力SHAを併記。元カメラ画像に加工なし。会話スクリーンショットの未提供ローカル原本は再作成していない。

生原本/派生全件はGit非対象のrecordings/2026-11-16配下。代表的な保存先：body_display_full_intake_r02、motion_range_handoff_replay_r02、motion_spatial_inputs_r01、odometry_metadata_received_intake_r01、received_motion_handoff_r01、sender_ros_clock_live_intake_r02。r01/r02等の同入力再監査は実験回数へ加算しない。

本日の既存commitは811e455/4dc26e3/c9534a2/4a786e7/a1b2272（1116v1〜v5）。今回の日報・代表資料・clock実記録監査・sender-frame部品・最新方針を追加commitしorigin/mainへpushする。動画/生ログ/重み/外部FFB repositoryは追加しない。pushの結果とcommit IDは作業完了メッセージで報告する。

## 10. 次回：11/17扱いの作業

ユーザー指定により、この11/16終了処理とpushの完了後は**11/17扱い**で続行する。OS時計・元実験日付・Git commit時刻を11/17へ偽装しない。

次はsource bundleと受信実画像の対応方式を、先頭/途中欠落・再接続・codec丸めを含めてローカル検証する。既存のライブ映像/操縦を維持する方式を比較し、metadataの到着順や近い受信時刻だけで結合しない。GPU反映・追加撮影/走行・G923出力はまだ要求しない。現取付の車体変換/車幅/障害物点の意味は別の未解決事項として残す。
