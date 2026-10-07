# 2026-10-07 完全遮蔽を意図したr01の解析

## 結論

**通知の配送経路はPASS。ただし、連続3秒の完全遮蔽という収録条件は未成立のため、完全遮蔽試験としては取り直しが必要。** 今回のデータは「部分遮蔽による測定喪失→UNKNOWN単発通知→復帰」の確認資料として残す。

- raw画像を約2秒間隔で24点、検出・候補結果を見る前に独立レビューした。可視15点、部分遮蔽9点、完全遮蔽0点。板の上に青箱の上縁が残っている。
- カメラのactive intent 42件は、両PCのcommand・dry_run statusへすべて対応。fault 0件、active intentのrelay拒否0件、上限0.05、最終inactiveを確認。
- 模擬前進中の2つのUNKNOWN区間で、それぞれ単発cadenceを1回送信。同じUNKNOWN区間内での単発通知の繰り返しはない。
- 2回目の復帰で距離推定が一時的に跳び、CRITICALが7フレーム発生。完全遮蔽の成立とは別に、復帰時の距離・速度推定の課題が残る。
- 本番コード・設定・安全ゲートは変更していない。実機FFBを動かしておらず、hardwareの振動や実走行の安全性を合格にはしない。

## 入力・整合性

手順書: [完全遮蔽・距離参照の収録手順](../phase5_full_occlusion_and_distance_reference_procedure.md)。

原本は`/home/robo25/Downloads/`にある次の3点。展開先は解析用一時領域であり、原本は変更していない。

| 原本 | SHA256 |
|---|---|
| `rokuga_phase5_full_occlusion_dryrun_r01_20261007_162722_969.tar.xz` | `01d9db18853028d1b05074a8cec5c63b13c41f3089059f501d6e43eab00d05a6` |
| `K_rosbug_phase5_full_occlusion_kobuki_r01.tar.xz` | `91560ae778c54f3e4bb81a36ece32297c47426361c0069bd23190dcf6a199df2` |
| `H_rosgub_phase5_full_occlusion_hsr_r01.tar.xz` | `499cddf5227d5a735c33ba5a3cb1f781979c7fead418ee682762010f1687383b` |

| 項目 | 結果 |
|---|---|
| session | `phase5_full_occlusion_dryrun_r01_20261007_162722_969` |
| 録画範囲（session名起点） | 16:27:22.969～16:28:09.230 JST、約46.26秒 |
| CSV | 1,372行、frame連番・時刻単調増加・time alias整合 |
| 動画 | raw／bev／detection各1,372フレーム。実際の逐次デコードでも確認 |
| raw解像度・要求形式 | 1280×720、MJPG、30 fps |
| 時刻差から求めた実効fps | 29.655 fps |
| フレーム間隔 | 中央33.266 ms、p95 38.434 ms、最大75.988 ms |
| 処理時間（CSV書込み前まで） | 中央30.861 ms、p95 37.879 ms、最大80.270 ms |
| 設定 | v12 JSONの全キーでmetadataとの差分なし |
| ODOM topic | `/phase5/mock_odom` |

metadataのpublisher `freshness_mode: clock`は上流の`/collision/ffb_intent`についての値。`transport_role: intent`、`relay_enabled: true`、`downstream_freshness_mode: challenge`も記録されており、最終commandまでclock方式だったという意味ではない。

## rawでの収録条件判定

目視ラベルは[manual_review.csv](manual_review.csv)、選定・判定手順は[review_protocol.md](review_protocol.md)、対応フレームのピクセルハッシュは[review_frame_manifest.csv](review_frame_manifest.csv)。検出結果から遮蔽の正解ラベルを作っていない。

| 録画からの時刻 | rawで確認した状態 | 模擬速度・live状態 |
|---|---|---|
| 9.993／11.995／13.994秒 | 部分遮蔽。板上に青色が残る | 0.25 m/s、後半UNKNOWN |
| 21.996／23.995／25.993秒 | 部分遮蔽。板上に青色が残る | 0.25 m/s、後半UNKNOWN |
| 33.995／35.998／37.996秒 | 部分遮蔽。板上に青色が残る | 停止／ODOM失効後、CLEAR |

24点の間と録画両端を含めた未レビュー区間の最大は**2.010738秒**。どの目視点にも箱の一部以上が見えているため、録画内の「連続3秒、箱全体が見えない」区間とは両立しない。短い完全遮蔽が点の間にあった可能性までは否定しない。全1,372フレームを目視したとは扱わない。

生画像（全画角・無加工）:

- [frame 1：可視状態](../report_assets/full_occlusion_r01_raw_frame_0001.png)
- [frame 766：板上に青い上縁が残る部分遮蔽](../report_assets/full_occlusion_r01_raw_frame_0766.png)

板の位置を高くする、または大きな板に替える必要がある。上端だけでなく左右・下端もraw画面で確認する。検出枠が消えたことだけでは完全遮蔽の確認にならない。

## 模擬ODOMと状態・通知

[全体タイムライン](trial_timeline.png)、[Kobuki側ODOM区間](kobuki_mock_odom_runs.csv)、[live状態区間](camera_collision_risk_level_runs.csv)。

- Kobuki側bagの0.25 m/sは600メッセージ、録画相対9.476773～29.443473秒。次の0速度メッセージが29.476566秒なので、送信区間は約20秒。
- カメラの読み取りでは9.514371～29.463576秒の588フレームが0.25 m/s。
- 1・2回目の部分遮蔽とUNKNOWNは模擬前進区間に重なっている。3回目は模擬停止後であり、前進中の追加遮蔽試行には数えない。
- 最後のODOM受信は録画相対34.484449秒。カメラでは34.972152秒からODOM unavailableになり、計338フレーム。この停止後のデータを「ODOM完備の走行評価」に混ぜない。
- シナリオの実送信CSVは今回の提出物に含まれていない。bagで速度・区間・通知との重なりは確認できるが、Enter時刻と計画時刻との差の直接照合は未実施。

| 区間 | 時刻（録画からの秒） | 結果 |
|---|---|---|
| 最初のWARNING | 9.569981～ | tripleの3つのactive窓が発生 |
| 1回目UNKNOWN | 10.526978～14.560776 | 118フレーム、単発は10.526978～10.593614秒の3送信だけ |
| 1回目復帰 | 14.595414～ | WARNINGへ復帰、triple通知 |
| 2回目UNKNOWN | 22.562002～27.193629 | 138フレーム、単発は22.562002～22.628654秒の3送信だけ |
| 2回目復帰 | 27.227268～ | WARNING復帰後に一過性CRITICALも発生（後述） |
| 最終CLEAR | 29.561272～46.260504 | active送信なし |

UNKNOWNの「3送信」は30 Hzで約0.1秒の**単発通知を維持するための更新**であり、3連振動ではない。active最終サンプルから次のinactiveまでを含めると約0.10秒。2回のUNKNOWNの間には長い有効測定復帰があり、再arm後の2回目通知として矛盾しない。

live全体の状態: CLEAR 782、PATH 2、WARNING 274、WARNING_HOLD 51、CRITICAL 7、UNKNOWN 256フレーム。検出973／1,372、有効測定933／1,372。検出なしを完全遮蔽の証明には使わない。

## 両PCの配送・安全側の動作

[active_delivery.csv](active_delivery.csv)はカメラのactive sequenceを、両PCのbag全体にsource・sequenceで照合した結果。さらに、両PC commandの全payload（source／sequence／receiver session／tokenを含む）が一致することを確認した。時刻だけの一致で配送を判定していない。

| 項目 | Kobuki PC | ハンコン接続PC |
|---|---:|---:|
| 全bag intent | 2,885 | 2,885 |
| 全bag command | 2,872 | 2,872 |
| 全bag status | 2,871 | 2,871 |
| 今回camera activeに対応するactive intent／command／status | 各42 | 各42 |
| active intentのrelay拒否 | 0 | 0 |
| fault status | 0 | 0 |
| statusのoutput_mode | dry_runのみ | dry_runのみ |
| 最大applied_magnitude | 約0.05 | 約0.05 |
| 最終status | shutdown／inactive／0 | shutdown／inactive／0 |

カメラのpublish_successも1,372／1,372。42件の内訳はWARNING系31、CRITICAL 5、UNKNOWN 6。上限0.05はfloat32表現では0.05000000074505806となるため、検証には1e-7の許容差を用いた。

全bagのrelay拒否13件は、起動安定待ち4件、使用済みtoken 9件。**すべてinactive intent**。起動待ちは録画前であり、録画時間窓内の拒否4件はいずれもinactiveの使用済みtoken。今回のactive通知欠落の根拠ではない。

両PCの全bag長はカメラ録画より長い。録画時間で切るとbag数が境界で1件程度ずれるため、これを通信欠落とは数えない。command全payload一致とactive照合を優先する。

challengeのbag記録間隔は、ハンコン側最大21.120 ms、Kobuki側最大111.236 ms（60 ms超2回）。relay診断のstream restart countは1のまま、forwarded時のtoken ageは最大31.708 ms。200 msのstream継続性判定とtoken鮮度を分けたv12動作と整合する。ただし、bag受信間隔はrelay callback間隔そのものではなく、ネットワーク／DDS／OSの揺らぎ内訳は特定していない。

dry_runの`output_active: true`や`applied_magnitude`はソフトウェア上の出力判断であり、この試行でハンコンが物理振動したことは意味しない。

## 復帰直後のCRITICALと固定候補の比較

[復帰拡大グラフ](second_recovery_transient.png)、[live根拠CSV](second_recovery_live.csv)。

2回目復帰のraw zは27.227268秒に1.3017 m、その後27.428615秒に1.0154 m。続いて選択された相対速度が`conservative_visual`の約−0.808 m/sとなり、TTC最小約1.196秒、CRITICALが27.562374～27.760642秒の7フレーム出た。27.793793秒にはWARNINGへ戻る。

**ログ上の因果経路は「復帰時の距離変化→視覚速度を保守側として選択→TTC短縮」。** 固定箱を前提とした今回の条件では、見かけの距離変化を接近として扱った可能性が高い。どの画素・接地点選択が最初の1.3017 mを作ったかまで確定していないため、画素レベルの原因診断完了とはしない。このCRITICALによる再通知もあり、2回目復帰を「予定どおり3連だけ」とは判定しない。

既存の10/06凍結候補を同じraw全1,372フレームへ適用した。S130等の閾値・候補実装の一致をSHA256で確認し、新録画を見て変更していない。[比較CSV・provenance](frozen_comparison/provenance.json)。

| オフライン条件 | 検出 | 有効測定 | CRITICAL | UNKNOWN | 部分遮蔽レビュー点の検出 |
|---|---:|---:|---:|---:|---:|
| baseline再計算 | 972 | 930 | 7 | 259 | 2／9 |
| seeded_s130_nearest | 975 | 955 | 0 | 244 | 2／9 |
| seeded_s130_bottom | 975 | 949 | 0 | 248 | 2／9 |

可視レビュー15点は3条件とも15／15検出。baseline再計算とliveの差（検出973→972、risk一致1,367／1,372）は、raw.aviがMJPG圧縮後であること等の再計算制約を含む。完全なlive再現とは扱わない。

候補でCRITICALが0になったことは有望だが、**完全遮蔽試験の代用や本番採用の根拠にはしない**。また車体は固定しODOMだけを模擬しているため、`contact_summary.csv`のmotion residualは実移動との整合精度として解釈しない。距離参照の実測録画・メモも今回未提出なので絶対距離精度は未評価。

## 次に行うこと

1. v12・dry_runを維持する。強度・安全ゲート・本番検出器を変更しない。
2. 遮蔽板の上端を高くするか、箱より十分大きな板に替える。raw表示で箱の青い面・上縁・左右・下縁が全部消える位置を先に決める。
3. その位置で板を3秒以上維持できることを確かめ、同じ20秒模擬前進中に2回の完全遮蔽と間の可視復帰を収録する。タイミングは[元手順](../phase5_full_occlusion_and_distance_reference_procedure.md)を使用する。
4. 修正版r01が条件を満たしたことを確認してからr02／r03へ進む。今回は部分遮蔽資料として残し、完全遮蔽の反復回数へ加算しない。
5. 次の提出は今回同様のcamera＋両PC bagに、`phase5_full_occlusion_mock_odom_r01.csv`と箱までの実測距離メモも添える（実際に使ったファイル名でよい）。

## 検証と再現

[summary.json](summary.json)に全体・録画時間窓別の集計、[verification.json](verification.json)に検証結果を保存。

- 3動画の全フレームを逐次デコードし、各1,372枚を確認。
- 両PC bagのSQLite integrity確認、全6topicのCDRを公式ROS deserializerと全件比較。
- active配送、dry_run限定、faultなし、cap、最終inactive、候補3条件×1,372行の連番と凍結設定を検証。
- 代表PNG2枚は1280×720全画角のまま保存し、rawデコードのBGRピクセルSHA256と一致。
- 本番コードに変更がないため本番全unit testsは再実行せず、解析スクリプトの構文・データ整合性を検証。matplotlibは3D拡張警告が出たが、使用した2Dグラフは保存・目視確認済み。

再現はリポジトリrootから、既存のsafe extractorで3原本を個別の空ディレクトリへ展開して行う。例の`/tmp/...`は今回の解析用一時ディレクトリなので、別環境では展開先へ読み替える。

```bash
MPLCONFIGDIR=/tmp/theta_matplotlib /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-10-07/phase5_full_occlusion_dryrun_r01/analyze_trial.py \
  --session /tmp/theta_full_occlusion_20261007_f3foje2j/camera/phase5_full_occlusion_dryrun_r01_20261007_162722_969 \
  --kobuki-db /tmp/theta_full_occlusion_20261007_f3foje2j/kobuki/phase5_full_occlusion_kobuki_r01/phase5_full_occlusion_kobuki_r01_0.db3 \
  --hsr-db /tmp/theta_full_occlusion_20261007_f3foje2j/hsr/phase5_full_occlusion_hsr_r01/phase5_full_occlusion_hsr_r01_0.db3
```

候補比較は`src/compare_offline_box_contacts.py`へ同じsessionを`--input`、v12 JSONを`--detector-config`として渡し、`--variants baseline seeded_s130_nearest seeded_s130_bottom --freeze-from Experimental_results/2026-10-06/box_contact_candidates/provenance.json`を指定する。出力先は本フォルダの`frozen_comparison/`。比較完了後に`analyze_trial.py`を実行すれば独立レビュー点とのjoinも作る。

最終検証はHumbleと`oit_interfaces`のinstallをsourceしてから、`validate_analysis.py`に同じ3引数を渡す。解析・検証ともROS publishや実機アクセスは行わない。
