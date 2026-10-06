# Phase 5 v12 実Kobuki走行 hardware r03 診断

## 結論

**FFB配送・出力・停止: PASS**

**距離・TTC安定性およびWARNING 3連再現: 未達（要診断）**

実施者が振動を体感したという報告と、active 7件すべてが両PCで`intent → command → hardware status`へ届いた記録が一致する。7件すべて`output_active=true`、適用強度0.05、`fault=false`だった。録画区間内faultは0件で、通知終了後の出力停止も確認できた。

ただし、今回はr01・r02と同じWARNING 3連の再現ではない。認識不確かのUNKNOWN単発と、距離推定の急変を伴うCRITICAL起点のtriple通知が含まれる。後者は2つのactive時間窓を出した後、CLEAR復帰によって3つ目の前に中断された。「active 7件」は7回の独立した振動という意味ではない。

床を反射しない場所に変更したとの申告を記録する。元映像では検出不成立・測定不採用時にも箱が見えており、反射対策だけで検出・距離推定の問題が解消したとは判定しない。実機の速度やFFB強度を増やす前に、この録画で輪郭・接地点と追跡再初期化後の速度推定を診断する。

## 入力と評価区間

| ファイル | SHA-256 |
|---|---|
| `rokuga_phase5_v12_live_kobuki_hardware_r03_20261006_153755_541.tar.xz` | `e4f60fb8a72b6777182ca61597c43a035d06912826428c4a4b0036578c2d8266` |
| `K_rosbug_phase5_v12_live_kobuki_hardware_kobuki_r03.tar.xz` | `55adf4822ecc6745d5fd2186c3f4dba6411715fea9a91a505b1545333c1544bd` |
| `H_rosbug_phase5_v12_live_kobuki_hardware_hsr_r03.tar.xz` | `595e9771c0d819f83c527986f361999c895b708f9db4ef86f63f42c1aaed00f5` |

- 元ファイル保存場所: `/home/robo25/Downloads/`
- カメラsession: `phase5_v12_live_kobuki_hardware_r03_20261006_153755_541`
- 評価窓: **2026-10-06 15:37:55.541～15:38:11.454643 JST**。session名の開始時刻とCSV経過時間から設定した。
- 指示どおり15:37以前のテスト動作は評価対象外。15:37以降でもカメラ録画前後の動作を再現性集計へ混ぜない。
- bag集計JSONの`recording_window_*`および`active_*`が試行評価の根拠。`bag_*`は全体の来歴であり、前半のテストを含む。全体集計をr03の通知件数として使用しない。
- 終了時の安全停止のみ、録画後15:38:27の`shutdown`を補足確認した。
- Kobuki PC: `matunuc-NUC13ANHi5`、ハンコン接続PC: `hsr-Alienware-m16-R2`。
- 実ODOM: `/odom`。FFBはrelay＋challenge経路、adapterは`hardware`、適用上限0.05。
- カメラmetadataの`parameters`はr01・r02と全項目一致。対応する設定は`src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json`。

## 定量結果

| 項目 | 結果 | 解釈 |
|---|---:|---|
| 録画完全性 | raw/BEV/detection/CSV各478 frame | PASS |
| 実効FPS | 29.999 fps | 30 fps±1%内 |
| 青箱検出 | 301/478、62.97% | r01・r02の100%から低下 |
| 有効測定 | 85/478、17.78% | 全フレームを分母とする |
| 検出されたフレーム中の測定採用 | 85/301、28.24% | 標準解析の採用率の分母はこちら |
| 追跡あり | 131/478、27.41% | 予測追跡を含む |
| CSVのODOM利用可能率 | 100% | 実ODOMあり |
| 実走行中速度中央値／最大 | 0.1258／0.1450 m/s | 上限0.25以下、予定の約0.18～0.22より遅い |
| `/cmd_vel.linear.x`最大 | 0.1836 m/s | 指令値と実速度を区別 |
| ODOM正味移動／積算移動 | 0.4570／0.4575 m | 両bagで一致 |
| `/cmd_vel.angular.z` | 全119件0 | 旋回指令なし |
| CRITICAL成立時TTC／実速度 | 1.948秒／0.1450 m/s | 視覚推定の急変を伴う |
| 最小有限TTC | 1.799秒 | WARNING_HOLD中の予測値を含む |
| active intent→command→status | 7→7→7 | 両PCで同じsequence、欠落0 |
| active適用強度 | 全7件0.05 | float32表現では0.050000000745 |
| 録画窓adapter fault | 0件 | statusは両bag各477件、すべてhardware |
| 最後のactive後の停止 | ハンコンPC bag上32.6 ms後 | 出力0、faultなし |
| 体感 | 振動を感じたとの申告 | 3連完了の申告とは扱わない |

正方向走行はハンコンPC bag上15:38:01.126～15:38:05.005 JST。r03の実測初期・停止距離、および物理停止線の確認結果は未提供であり、距離精度・停止線についてPASSとはしない。最後に追跡できた距離1.2142 mは録画終了時の有効距離ではない。

## 通知の内訳

| 通知 | frame | 経過秒 | sequence | active件数 |
|---|---:|---:|---|---:|
| UNKNOWN単発 | 206 | 6.856952 | 5802 | 1 |
| CRITICAL起点tripleの第1窓 | 272～274 | 9.052618～9.127389 | 5868～5870 | 3 |
| 同tripleの第2窓 | 278～280 | 9.246670～9.314110 | 5874～5876 | 3 |

frame 207で有効測定に戻り、UNKNOWN通知は`cadence_cancelled_by_clear`で止まった。UNKNOWNの再arm待ちにより短い認識復帰ごとの通知連発は起きていない。

frame 272でCRITICAL、273～275でWARNING_HOLD、276～282でWARNINGとなった。frame 283、9.413963秒、sequence 5879でCLEARへ戻り、`cadence_cancelled_by_clear`となったため、triple第3窓は出ていない。これは配送欠落ではなく、送信元の通知中断である。

ハンコンPC bag上のactive `command → status`時間差は中央値0.589 ms、最大1.274 msだった。これは同一bagの受信記録時刻差であり、カメラから実モーターまでの遅延測定ではない。relayはforwarded 477件、rejected 1件で、見送りはinactiveの`receiver_challenge_already_used`のみだった。

## 距離・TTCが乱れた経過

| frame | 経過秒 | 記録上の事象 |
|---|---:|---|
| 1 | 0.012871 | raw z=1.5021 m、校正上限1.35 mより遠く、測定不採用 |
| 204 | 6.793135 | raw z=1.3370 mで追跡初期化 |
| 206 | 6.856952 | 箱は元映像に見えるが、ライブ検出なし。UNKNOWN単発 |
| 267 | 8.884381 | NIS棄却継続で`nis_gate_track_expired`、追跡失効 |
| 269 | 8.954981 | z=1.1708 mで再初期化、TTC=8.856秒 |
| 270 | 8.998038 | raw z=1.0510 mへ43 msで約12 cm変化。実速度0.1343 m/s |
| 272 | 9.052618 | 追跡vz=-0.7006 m/s、視覚平滑vz=-0.5428 m/s、TTC=1.948秒でCRITICAL |
| 273 | 9.087388 | 視覚平滑vz=-0.5741 m/s、実速度0.1343 m/s、TTC=1.799秒 |
| 283 | 9.413963 | TTC=8.202秒、CLEAR復帰でtriple中断 |
| 350 | 11.648719 | 実機停止中、箱は映像に残るがraw z=1.7018 m、校正範囲外 |
| 400～終了 | 13.315998～ | 箱が映像に残っていてもライブ検出が不成立 |

frame 269→270の実速度から想定する前進量は約6 mmで、推定接地点の約12 cm変化とは整合しない。静止箱への直進という試験条件では、再初期化後の測定急変が接近速度を過大に見積もった疑いが強い。

`conservative` TTCは視覚速度とODOMのうち接近側で大きい値を選ぶため、今回は視覚ノイズがODOMで抑えられず、CRITICALへつながった（`src/obstacle_tracking.py:390`）。NIS棄却後の失効は同ファイルの追跡処理、CLEAR/PATH復帰でのcadence中断は`src/collision_ffb_publisher.py:277`の動作と一致する。

測定処理の内訳は`calibration_range_gate`188、`no_detection`177、NIS棄却21、NISによる失効1、再捕捉確認6、初期化2、採用83 frame。有効測定85は初期化2＋採用83である。

## 元映像・輪郭の確認と限界

保存した元解像度PNGで、frame 206および350の箱が正面に残っていることを確認した。画像の加工はしていない。

AVIの参考再検出では、箱内部の固定小領域のV中央値が初期31で、設定下限V=30に近い。frame 206では同領域の約34%がV<30だった。また、周辺の青色輪郭が横長になり、設定`max_aspect_ratio=1.5`を超えて棄却されるフレームがある。暗い青面の欠損と周囲の青みを含む輪郭の変化が原因候補であるが、床変更自体が原因と断定しない。

**ライブ検出とAVI再検出は一部一致しない。** 例としてframe 206はライブ未検出だがAVI再検出では検出され、frame 272は逆だった。`raw.avi`は`src/bird_eye.py:1553`のMJPGで再圧縮されており、元の入力画素を完全保持していない。この閾値近傍の感度と圧縮による差があり得るため、AVIの輪郭結果をライブ時点の正確な棄却理由と決めつけない。実際に出したFFBの評価はライブCSV・rosbagを優先する。

## r01～r03の比較

| 指標 | r01 | r02 | r03 |
|---|---:|---:|---:|
| FPS | 29.920 | 29.631 | 29.999 |
| raw検出率 | 100% | 100% | 62.97% |
| 最大実速度m/s | 0.213 | 0.213 | 0.145 |
| active配送 | 8→8→8 | 11→11→11 | 7→7→7 |
| 録画窓fault | 0 | 0 | 0 |
| 通知内容 | WARNING 3窓 | WARNING 3窓 | UNKNOWN 1窓＋CRITICAL起点2窓 |
| 体感申告 | 3回、停止後不要振動なし | 3回 | 振動あり |

FFB通信・出力経路は3試行で確認できた。一方、r03は床面変更と速度差もあるため、同条件でのWARNING 3連「3/3成功」や距離精度の合格とは集計しない。

標準解析FAILは観測ゲートの安定採用率80.91%・最大abs(vz)0.7933 m/sによる。これはAVI再計算値でライブ値とは区別する。今回はライブでも実速度と不整合な距離・視覚速度変化を確認しており、r01・r02のように単に動的接近が静的検査に掛かっただけとして除外しない。

## 成果物と次に行うこと

- `phase5_v12_live_kobuki_hardware_r03_analysis/`: 標準解析、ライブ時系列グラフ、選択frameのライブ／AVI比較CSV。
- `phase5_v12_live_kobuki_hardware_r03_camera_summary.json`: カメラCSV集計。
- `phase5_v12_live_kobuki_hardware_{kobuki,hsr}_r03_bag_summary.json`: 両PC集計。
- `phase5_v12_live_kobuki_hardware_{kobuki,hsr}_r03_recording_window_events.csv`: 評価窓内のイベント。
- `report_assets/phase5_v12_live_hardware_r03_raw_frame_{0206,0350}.png`: 元解像度・無加工のカメラ画像。
- `phase5_v12_live_kobuki_hardware_r03_diagnostic_plots.py`: グラフ・PNG・参考輪郭診断CSV生成スクリプト。

再生成例（アーカイブを安全に展開したsessionディレクトリを指定）:

```bash
python3 Experimental_results/2026-10-06/phase5_v12_live_kobuki_hardware_r03_diagnostic_plots.py \
  /path/to/phase5_v12_live_kobuki_hardware_r03_20261006_153755_541
```

次は追加録画を先に要求せず、既存r01～r03でHSV輪郭・接地点の感度、NIS棄却・再初期化直後のTTCを切り分ける。閾値緩和や速度ソース変更をする場合は、見逃しと誤警告の両方を過去録画で比較し、変更前後の根拠を残す。今回は解析のみで、ソース・設定・安全ゲートは変更していない。

その後の原因切り分けは[距離・TTC不安定性診断](phase5_distance_instability_diagnosis/README.md)に記録した。ライブCSV・箱なし参考対照・輪郭設定7条件・TTC速度源4条件を比較した。追跡再初期化直後の測定急変による速度推定の増幅を局所再生で確認した一方、閾値緩和・横長除外撤去・ODOM単独への変更は本番解として採用していない。
