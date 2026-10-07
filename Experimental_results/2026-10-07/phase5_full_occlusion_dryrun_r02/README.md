# 2026-10-07 完全遮蔽dry_run r02解析

## 結論

**今回は長い完全遮蔽の評価資料として使える。模擬前進中の完全遮蔽2区間、UNKNOWN各1回の単発通知、可視復帰後の3連通知、active 34件の両PC対応を確認した。** ただし、完全遮蔽の目視は約0.5秒間隔のサンプル確認であり、間の全フレームを個別に目視したという意味ではない。

- 完全遮蔽を確認した点の幅は1回目3.510秒、2回目4.496秒。r01で残っていた箱の上縁も、今回は隠れている。
- 完全遮蔽の独立レビュー20点で、liveと凍結候補3条件はすべて検出0。有効測定もliveで0。
- UNKNOWNは2区間。それぞれ単発cadenceが1回だけ出て、同じUNKNOWN中に繰り返していない。復帰後はWARNINGと3連通知へ戻る。
- r01の復帰時にあった一過性CRITICALは、今回はliveも候補再計算も0フレーム。
- **全bagの通信が無異常だったわけではない。** 前進前にchallenge stream断と再安定待ち、録画開始前にinactive commandのtoken期限切れfaultがある。遮蔽試行中のactive配送とは切り分ける。
- 本番・hardwareへの採用判定は行わず、v12・dry_runを維持する。同条件の次の独立収録（r03）へ進める。

詳細判定は[trial_assessment.json](trial_assessment.json)。共通集計の[summary.json](summary.json)が`recorded_delivery_decision: REVIEW_REQUIRED`なのは、全bagのfault・payload集合差を厳格に見るため。これを消さず、以下の条件付き判定と併記した。

## 入力・整合性

入力は`/home/robo25/Downloads/`の3原本。path/link/サイズを検査する既存safe extractorで、解析用の一時ディレクトリへ展開した。原本は変更していない。

| ファイル | SHA256 |
|---|---|
| `rokuga_phase5_full_occlusion_dryrun_r02_20261007_165130_432.tar.xz` | `fef3a2256a81f1009d6b5f9b8413c6442b55788062cdd40d9e54f649c6c2b14d` |
| `K_rosbug__phase5_full_occlusion_kobuki_r02.tar.xz` | `b13c451d72a5458851e8aec78d3953e0c3c4afd0797b25fd3ab48bd34fe75de9` |
| `H_rosgub_phase5_full_occlusion_hsr_r02.tar.xz` | `69f2703e8738f572a19419588aa93b4a063cdbc2bbafe00dc0195fce8f3bf10a` |

| 項目 | 測定結果 |
|---|---|
| session | `phase5_full_occlusion_dryrun_r02_20261007_165130_432` |
| session名起点の時刻 | 16:51:30.432～16:52:15.916 JST、約45.48秒 |
| CSV／raw／bev／detection | 各1,359フレーム、動画は全フレーム逐次デコードでも一致 |
| frame・time | 連番、単調増加、time alias整合 |
| v12 JSONとmetadata | 全キー差分なし |
| raw・要求fps | 1280×720、MJPG、30 fps |
| 実効fps | 29.870 fps |
| フレーム間隔 | 中央33.260 ms、p95 38.767 ms、最大72.886 ms |
| 処理時間（CSV書込み前） | 中央30.296 ms、p95 39.200 ms、最大83.848 ms |

metadataのclock方式は上流のintentについての記録であり、standalone relayの下流はchallenge方式。通信の片道遅延を両PCのwall clock差から求めてはいない。

## raw独立レビューと模擬前進

[目視手順](review_protocol.md)、[独立ラベル41点](manual_review.csv)、[レビュー点とliveの照合](review_live_join.csv)、[区間集計](visual_review_intervals.csv)。検出・候補結果を見る前にラベルを固定した。

| 区間 | 完全遮蔽を目視した点の範囲 | 確認点数・幅 | 模擬前進との重なり |
|---|---|---|---|
| 1回目 | frame 390～493、12.985979～16.496134秒 | 8点、3.510155秒 | 全点0.25 m/s |
| 2回目 | frame 731～864、24.490371～28.986715秒 | 10点、4.496344秒 | 全点0.25 m/s |
| 停止後の追加遮蔽 | frame 1134／1194、37.985550／39.984044秒 | 2点 | ODOM失効後。前進中の試行に数えない |

第1・第2区間の最大レビュー間隔は0.543456／0.533872秒。箱のあった位置全体を大きな黒い遮蔽物が覆っており、今回の長い完全遮蔽の確認資料として使用する。正確な開始・終了時刻、レビュー点間の全フレームの正解ラベルまでは確定していない。

生画像は[frame 420](../report_assets/full_occlusion_r02_raw_frame_0420.png)と[frame 836](../report_assets/full_occlusion_r02_raw_frame_0836.png)。全画角1280×720、無注釈・無加工であり、rawデコードと保存PNGのピクセルSHA256を照合した。

Kobuki側bagの模擬0.25 m/sは600送信、録画相対10.477111～30.443956秒、次の0速度送信が30.477341秒。約20秒の前進区間がある。カメラ側は10.510724～30.484387秒の595フレームで模擬前進を読み取っている（[camera_odom_linear_mps_runs.csv](camera_odom_linear_mps_runs.csv)）。

最後の模擬ODOM受信は35.485175秒。カメラは35.984296秒以降、286フレームでODOM unavailable。これは最後の停止送信終了後の記録で、前進中の遮蔽2区間には重ならない。シナリオ実送信CSVと実測距離メモは今回も未提出なので、Enter時刻との照合と絶対距離精度は未評価。

## 状態・通知

[全体タイムライン](trial_timeline.png)、[UNKNOWN通知区間](unknown_notifications.csv)、[active窓](camera_collision_ffb_active_runs.csv)。

| イベント | 録画相対時刻 | 結果 |
|---|---|---|
| 模擬前進開始 | 10.510724秒（camera） | PATH確認後、10.582021秒にWARNING |
| 1回目UNKNOWN | 13.385332～16.917555秒 | 105フレーム。単発のactive窓1つ、更新4件 |
| 1回目復帰 | 16.950548秒 | WARNING、active窓3つのtriple通知 |
| 2回目UNKNOWN | 25.017670～29.085335秒 | 121フレーム。単発のactive窓1つ、更新3件 |
| 2回目復帰 | 29.117479秒 | WARNING、active窓3つのtriple通知 |
| 最終CLEAR | 30.584497秒～終了 | active通知なし |

UNKNOWNの更新4件／3件は、単発通知を維持するための連続送信であり、4回／3回の振動ではない。最初のinactiveまで含めると第1単発約0.133秒、第2単発約0.102秒。設定の0.1秒に対してフレーム時刻で切り替わるため、送信数を固定3件とは判定しない。

可視復帰が十分続いた後に2回目のUNKNOWNで再通知している。同じUNKNOWN区間中の単発繰り返しはない。live状態はCLEAR 762、PATH 2、WARNING 301、WARNING_HOLD 68、UNKNOWN 226、CRITICAL 0。検出940／1,359、有効測定928／1,359。

復帰2回目の推定速度は[28.7～30.5秒のCSV](second_recovery_live.csv)で−0.25 m/sのまま、有限TTCは4.061～4.245秒。[復帰グラフ](second_recovery_transient.png)でも、r01の約−0.808 m/sへの跳び・CRITICALは再現していない。ただし1試行で再現しなかったことを原因の解消とは扱わない。

## 配送と残った通信上の注意点

[active配送の照合](active_delivery.csv)では、**全34件のcamera activeが両PC intent・command・正常active statusへ対応**。両PCのactive command payloadも完全一致。34件はWARNING系27、UNKNOWN 7で、CRITICALのactiveは0。全statusはdry_run、最大appliedはfloat32の約0.05、最後は両PCともinactive。録画時間窓内のfaultは0。

一方、全bagでは次の差があるので、通信全体を無条件PASSにはしない。

| 観測 | 内容・範囲 | 今回のactive通知への影響 |
|---|---|---|
| 録画開始前のfault | 相対−67.338秒付近、sequence 62、`invalid_request:expired_receiver_token`。inactive／要求0 | 遮蔽試行より前。全bagでは1件として残す |
| stream断 | 約8.26秒にrelayのprevious gap 314.117 ms、restart count 1→2 | まだ模擬停止・CLEAR・inactive |
| 再安定待ち | stale／stream_not_stableで見送り、9.290680秒にforward再開 | 模擬前進開始10.477秒より前に復帰 |
| command差1件 | inactiveのsequence 2320はK bagのみ。H bagと両statusには記録なし | activeではない。配送かbag記録かの内訳は未確定 |
| その他のbag差 | H側にintent 2320～2323、diagnostic 2320～2322の記録がない | いずれもinactive。activeの欠落は観測なし |

全bag command数はK 3,493、H 3,492。共有3,492件のpayloadは一致。statusはK 3,492、H 3,493で、Hには最後のshutdown statusも残る。bag停止時刻の違いもあるため、件数だけで全てを通信欠落と扱わない。[bag差のCSV](cross_pc_bag_differences.csv)へ具体的な記録を保存した。

K側relay拒否は全bag 51件、うち録画時間窓40件で、すべてinactive intent。active拒否は0。ハンコン側challenge bag間隔最大22.422 ms、K側最大313.945 ms。relay callbackでも314.117 msのgapが記録されているため、今回は200 ms超の断で1秒再安定化した実例である。ネットワーク／DDS／OSのどこで遅れたかは未確定。

これは安全ゲートを緩める根拠にはしない。将来active中に同様の断が起きれば、通知を見送り得る。今回成功した34件の配送とは別の可用性課題として残す。dry_run statusのactiveは物理振動の証明ではない。

## 10/06凍結候補のオフライン比較

同じraw全1,359フレームへ既存3条件を適用し、候補設定・実装ハッシュが10/06凍結版と一致することを確認した。新録画に合わせた調整、本番設定への反映は行っていない。

| 条件 | 検出 | 有効測定 | UNKNOWN | CRITICAL | 完全遮蔽レビュー20点の検出 |
|---|---:|---:|---:|---:|---:|
| baseline再計算 | 940 | 910 | 226 | 0 | 0／20 |
| seeded_s130_nearest | 940 | 935 | 226 | 0 | 0／20 |
| seeded_s130_bottom | 940 | 935 | 226 | 0 | 0／20 |

可視レビュー19点は全条件19／19、部分遮蔽2点は2／2検出。候補が完全遮蔽時に別の青色を誤検出する問題は、この20点では出ていない。

baseline再計算とliveのriskは18／1,359フレームで異なり、virtual activeは35件（live34件）。圧縮後rawからの再計算はliveと完全同一ではない。[比較provenance](frozen_comparison/provenance.json)と[比較CSV](frozen_comparison/risk_summary.csv)を参照。車体固定・模擬速度の試験なのでmotion residualを実移動の距離精度として評価しない。

## 次の作業・検証

1. 同じ大きな遮蔽物、v12、dry_run、専用mock ODOMでr03へ進む。今回r02が長い完全遮蔽の有効な収録1本目で、r01は部分遮蔽資料として別扱い。
2. 今回と同様に可視→完全遮蔽→復帰を模擬前進中に2回。3回目の停止後遮蔽を増やすより、先の2区間を確実に実施する。
3. 原本camera＋両PC bagに、シナリオCSVと実測距離メモも添える。実験中のダウンロード・同期・圧縮を避ける。再発する通信断の原因特定には別途負荷・通信計測が必要。
4. 今回の結果だけでhardwareへ進めたり、強度や鮮度ゲートを変更したりはしない。

[verification.json](verification.json)に、3動画全フレームデコード、全6topicのCDRと公式ROS deserializerの全件一致、active配送・上限・mode・録画時間窓fault、凍結比較4,077行の連番、PNGピクセル一致を保存。解析スクリプトは構文確認済み。本番コード変更がないため本番unit testsは再実行していない。2Dグラフは保存・目視確認した。

再現にはr01フォルダの共通`analyze_trial.py`へ今回の`--session`／`--kobuki-db`／`--hsr-db`を渡し、`--output-dir Experimental_results/2026-10-07/phase5_full_occlusion_dryrun_r02 --plot-title '2026-10-07 r02: fully hidden box samples during mock forward motion' --recovery-window 28.7 30.5`を指定する。

候補比較はr01と同じ`compare_offline_box_contacts.py`、v12 JSON、`--variants baseline seeded_s130_nearest seeded_s130_bottom`、10/06の`--freeze-from`を使い、今回の`frozen_comparison/`へ出力。完了後に共通解析を実行し、Humble・oit_interfacesのinstallをsourceした環境で今回の`finish_analysis.py`へ同じ3入力引数を渡す。展開先は今回`/tmp/theta_full_occlusion_r02_20261007_qpvg5uoe/`であり、一時領域のため別環境では読み替える。どの処理もROS publishや実機アクセスは行わない。
