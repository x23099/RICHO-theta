# 2026-10-07 完全遮蔽dry_run r03解析

## 結論

**r03は、模擬前進中の完全遮蔽2回・UNKNOWN各1回の単発通知・復帰後の3連通知を確認できた反復資料として使える。active 38更新すべてが両PCの正常active statusへ対応した。** 完全遮蔽の確認は生画像のサンプル目視であり、中間の全フレームを目視したという意味ではない。

- 完全遮蔽の確認点の幅は約3.035秒／4.488秒。両方とも模擬0.25 m/sの区間内。
- UNKNOWNは2区間で、単発通知の繰り返しはない。可視復帰後は各3連通知へ戻る。
- liveのCRITICALは0、録画時間窓内のadapter faultは0、activeのrelay拒否は全bagで0。
- ただし**全bagを無異常PASSとはしない**。録画開始前にinactiveのtoken不認識faultが3件あり、録画中にもinactive指令の見送り4件がある。
- rawからのbaseline再計算ではCRITICALが1フレームあり、liveと完全同一ではない。凍結候補の採用・hardwareへの移行判定はしない。

[詳細判定](trial_assessment.json)と[共通集計](summary.json)を併記する。共通集計の`recorded_delivery_decision: REVIEW_REQUIRED`は全bagのfaultを含めた厳格な判定であり、成功したactive経路と区別する。

## 入力・整合性

原本はすべて`/home/robo25/Downloads/`。既存の安全展開処理でパス・リンク・展開サイズを検査し、一時ディレクトリへ展開した。原本は変更していない。

| 原本 | SHA256 |
|---|---|
| `rokuga_phase5_full_occlusion_dryrun_r03_20261007_171609_894.tar.xz` | `e23d3e0d46f5f9117d53940a0fc25cd62074e235c3354591c5f51f8b7a6f6c43` |
| `K_rosbug_phase5_full_occlusion_kobuki_r023.tar.xz` | `9a06d7c90fedbbe0528a47aad43e5d83b9013e66f164b3b6724b8b9be674564e` |
| `H_rosbug_phase5_full_occlusion_hsr_r03.tar.xz` | `9d1777c40a8816555a99e8065bc1679f233a2a8ad1f7c416ee4ecdb56d717ebc` |

K側の内部bag名も`r023`だが、ユーザー確認によりr03として対応付けた。元のファイル名・内部記録名を改変していない。

| 項目 | 結果 |
|---|---|
| session | `phase5_full_occlusion_dryrun_r03_20261007_171609_894` |
| session名起点の時刻 | 17:16:09.894～17:16:47.718 JST、約37.82秒 |
| CSV／raw／bev／detection | 各1,131フレーム。動画全フレーム逐次デコードでも一致 |
| frame／time | 連番・単調増加・time alias整合 |
| v12設定とmetadata | 全キー差分なし |
| 取得 | 1280×720、MJPG、要求30 fps、実効29.893 fps |
| フレーム間隔 | 中央33.251 ms、p95 38.294 ms、最大76.907 ms |
| CSV書込み前処理時間 | 中央30.497 ms、p95 37.009 ms、最大75.778 ms |

metadataの上流intentはclock方式だが、下流standalone relayはchallenge方式。両PCのwall clock差から片道遅延を計算していない。

## 独立生画像レビュー・模擬速度

検出結果や候補比較を見る前に目視ラベルを固定した。[手順と確認順序](review_protocol.md)、[独立ラベル52点](manual_review.csv)、[liveとの照合](review_live_join.csv)、[区間集計](visual_review_intervals.csv)を保存。

最初は2秒グリッド、遮蔽付近は0.5秒グリッドで確認。1回目が3秒の境界に近かったため、開始・終了付近だけ0.1秒グリッドと隣接4フレームを追加確認した。可視25、部分遮蔽2、完全遮蔽25点。

| 区間 | 完全遮蔽の確認点 | 点数・確認範囲の幅 | 最大確認間隔 |
|---|---|---|---|
| 1回目 | frame324～415、10.787774～13.822685秒 | 15点、3.034911秒 | 0.518456秒 |
| 2回目 | frame583～716、19.504999～23.992841秒 | 10点、4.487842秒 | 0.508826秒 |

両区間の全レビュー点でmock ODOMは0.25 m/s、live検出0、有効測定0。1回目の直前frame323と直後frame416には箱下端が残るため、部分遮蔽として別ラベルにした。3秒条件は緩めていない。ただし確認点間の全フレームの可視性や厳密な境界時刻までは確定しない。次回も同条件を撮るなら、手動タイミングの余裕を持たせて4～5秒隠すとよい。

生画像：[frame359・11.993116秒](../report_assets/full_occlusion_r03_raw_frame_0359.png)、[frame656・21.990126秒](../report_assets/full_occlusion_r03_raw_frame_0656.png)。全画角1280×720、注釈・切抜き・リサイズ・色補正なし。保存PNGのBGRピクセルとrawデコードの一致を検証した。

K bagの模擬前進は600送信、相対9.640034～29.606876秒、次の0速度送信は29.640033秒。カメラ側は9.656497～29.625641秒の596フレームで前進を認識した（[camera ODOM区間](camera_odom_linear_mps_runs.csv)）。35.154878秒以降の81フレームは停止送信終了後のODOM unavailableで、遮蔽評価区間とは重ならない。

シナリオ実送信CSVと実測距離メモは今回の3原本には含まれていない。速度の時間帯はbagで確認できるが、Enter時刻との厳密な対応や絶対距離精度は未評価。車体固定・模擬速度であり、実走行試験ではない。

## 状態・通知・配送

[全体タイムライン](trial_timeline.png)、[通知エピソード](notification_episodes.csv)、[UNKNOWN区間](unknown_notifications.csv)、[active配送照合](active_delivery.csv)。以下の時刻は録画相対秒。

| イベント | 時刻 | active更新数 | 通知のactive窓数 |
|---|---|---:|---:|
| 最初のWARNING通知 | 10.188878～10.621617 | 11 | 3 |
| 1回目UNKNOWN通知 | 11.488497～11.587954 | 4 | 1 |
| 1回目復帰WARNING通知 | 13.924233～14.356319 | 10 | 3 |
| 2回目UNKNOWN通知 | 19.921837～20.021269 | 4 | 1 |
| 2回目復帰WARNING通知 | 24.156898～24.589853 | 9 | 3 |

UNKNOWN状態自体は11.488497～13.889810秒の73フレームと、19.921837～24.122938秒の125フレーム。各区間で単発通知1回だけ。更新4件は1回の通知を維持する連続送信であり、4回振動という意味ではない。最初のinactiveまでの幅は各約0.133秒。設定0.1秒に対して画像フレームで切り替えるため、更新件数を固定3件とは判定しない。

live状態はCLEAR547、PATH2、WARNING334、WARNING_HOLD50、UNKNOWN198、CRITICAL0フレーム。検出875、有効測定853。最終CLEARは29.722350秒以降で、以降のactive通知なし。

全38 active更新（WARNING30、UNKNOWN8）について、両PCのintent・command・正常active statusへの対応を確認。両PC commandは全bag4,398件で、sequenceとpayloadが一致。intentとrelay diagnosticも両PC間のsequence差0件。全statusはdry_run、最大applied約0.05、最後は両PCともinactive。**dry_runのactiveは実振動の証明ではない。**

2回目復帰後のTTCに採用された速度は−0.25 m/s、有限TTCは4.124～4.271秒。r01復帰時の大きな負速度・CRITICALは今回のliveでは再現していない（[復帰CSV](second_recovery_live.csv)、[復帰グラフ](second_recovery_transient.png)）。再現しないことを原因の解消とは扱わない。

## 通信上の留保

| 観測 | 範囲と内容 | active通知への影響 |
|---|---|---|
| adapter fault 3件 | 録画前−68.443、−55.437、−4.947秒付近（K bag時刻）、sequence1020／1410／2922。いずれもinactive、要求0、`invalid_request:unknown_receiver_token` | 今回の遮蔽・active通知より前。原因の内訳は未確定 |
| relay見送り4件 | 録画中sequence3088／3862は`receiver_challenge_already_used`、3863／3864は`stale_receiver_challenge`。すべてinactive | activeの見送りは0 |
| challenge間隔の揺らぎ | K bag最大131.077 ms、H bag最大20.886 ms（全bag） | 鮮度60 msを超える瞬間は存在。ただしstream restart countは1のまま増加せず |
| status総数差1件 | K4,396、H4,397 | H側の終了時shutdown記録が追加。active数は両側38 |

K側の見送り時刻は約0.462秒と26.395～26.464秒。後者のfresh token ageは約72／108 msで、60 ms鮮度制約によって拒否された。200 msのstream断基準は超えておらず、1秒再安定待ちを増やしていない。実験中にactiveが重なれば見送る可能性がある点は残る。

録画時間窓内のadapter faultは両PC0、全bag active拒否も0。採用されたtokenのrelay側ローカルageは最大30.966 ms。K側bag受信間隔はcallback遅延そのものではなく、ネットワーク／DDS／OS負荷の内訳までは特定していない。安全ゲートを緩める根拠にはしない。

## 10/06凍結候補のオフライン比較

同じraw1,131フレームへ既存3条件を適用した。[比較provenance](frozen_comparison/provenance.json)で設定・候補実装ハッシュが10/06凍結版と一致することを検証。新録画へ合わせた調整はしていない。

| 条件 | 検出 | 有効測定 | UNKNOWN | 再計算CRITICAL | 完全遮蔽レビュー検出 |
|---|---:|---:|---:|---:|---:|
| baseline再計算 | 870 | 844 | 200 | 1 | 0／25 |
| seeded_s130_nearest | 889 | 886 | 196 | 0 | 0／25 |
| seeded_s130_bottom | 889 | 886 | 196 | 0 | 0／25 |

可視25点はbaseline23／25、候補2条件25／25、部分遮蔽2点は全条件0／2。完全遮蔽を別の青色と誤認する問題は、レビュー25点では観測していない（[候補と目視の照合](review_candidate_join.csv)）。

baseline再計算のCRITICALはframe318・10.588499秒の1フレームで、TTC1.997774秒が2秒閾値をわずかに下回った。完全遮蔽成立前・最初のWARNING通知中であり、2回目復帰時ではない。liveは同フレームWARNINGで、risk差は全体10／1,131フレーム。rawはMJPG圧縮後の画像なので、再計算をliveと完全同一とは扱わない（[risk集計](frozen_comparison/risk_summary.csv)）。

候補は今回も改善傾向だが、絶対距離精度は未評価。車体固定に模擬速度を与えているため、motion residualを実移動の距離誤差として評価しない。候補のsegmentation中央時間は約19.7 ms、baseline約8.3 msであり、処理時間の検討も残る（今回のオフライン環境での値）。本番設定・鮮度・強度・hardware gateは変更していない。

## 到達点・次の作業

r01は部分遮蔽資料、r02とr03は模擬前進中の長い完全遮蔽の有効収録2本として整理できる。両方でUNKNOWN単発・復帰3連・active全件配送を確認した。ただし通信可用性やhardware安全性まで合格した意味ではない。

次は[既存手順書の「8. 静止距離の参照収録」](../phase5_full_occlusion_and_distance_reference_procedure.md)へ進める。箱なし約10秒、中央0.90／1.10／1.30 m各20秒と、カメラ直下／Kobuki中心から箱手前面までの実測メモを揃える。v12・dry_runを維持し、表示値に合わせて箱の位置を変えない。距離候補の採用判定より先に参照データを集める。

## 検証と再現

[verification.json](verification.json)に、動画全デコード、両bag全6topicの公式ROSデシリアライズと独自CDRデコードの全件一致、代表PNGのピクセル一致、比較3,393行の連番・凍結一致、active配送・mode・上限・録画時間窓fault確認を保存。2Dグラフは生成後に目視確認。本番コード変更はないため本番unit testsは再実行していない。

解析はr01の共通[analyze_trial.py](../phase5_full_occlusion_dryrun_r01/analyze_trial.py)を再利用。独立レビュー後、展開済sessionと両db3を渡し、`--output-dir Experimental_results/2026-10-07/phase5_full_occlusion_dryrun_r03 --plot-title '2026-10-07 r03: full occlusion and dry-run delivery' --recovery-window 23.5 26`で実行した。

凍結比較は`src/compare_offline_box_contacts.py --input SESSION --detector-config src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json --output-dir Experimental_results/2026-10-07/phase5_full_occlusion_dryrun_r03/frozen_comparison --variants baseline seeded_s130_nearest seeded_s130_bottom --freeze-from Experimental_results/2026-10-06/box_contact_candidates/provenance.json`。その後共通解析を再実行して目視ラベルと比較結果を結合する。

r02の[finish_analysis.py](../phase5_full_occlusion_dryrun_r02/finish_analysis.py)を出力先・確認区間指定に対応させて再利用した。ROS Humbleとローカルinterfaceをsourceした環境で`--session SESSION --kobuki-db K_DB --hsr-db H_DB --output-dir Experimental_results/2026-10-07/phase5_full_occlusion_dryrun_r03 --review-interval 324 415 --review-interval 583 716 --asset-prefix full_occlusion_r03`を指定。これは記録のデシリアライズのみで、ROS nodeやpublisher、実機を起動しない。
