# Phase 5 v12 hardware WARNING試験 診断

## 結論

**判定: PASS（静止青箱 + 模擬ODOMによるWARNINGの実ハードウェア出力）**

青箱を正面に置いた状態で模擬ODOM `0.25 m/s`を与えると、カメラ側でWARNINGが成立し、`intent -> relay -> command -> hardware status` の全段を同じ9 sequenceが欠落なく通過した。9件のactiveは3件ずつの3群に分かれ、ハンコン側では各群が `output_mode=hardware`、`action=apply`、`output_active=true`、`applied_magnitude=0.05` となった。利用者の「しっかり3連続の振動を感じた」という体感報告とも一致する。

録画時間内のfaultは0件で、通知後はinactiveへ戻り、bag終了時にも`shutdown`で出力停止している。したがって、今回の範囲ではv12のWARNING通知を実機へ安全に到達させる経路を確認できた。

ただし、これはUNKNOWN通知や実走行Kobukiを含む総合試験の完了判定ではない。また、汎用録画解析は実効FPS不足だけを理由にFAILであり、別途性能上の注意として残す。

## 入力

| 種別 | ファイル | SHA-256 |
|---|---|---|
| ハンコンPC bag | `H_rosbug_phase5_v12_hardware_hsr_r01.tar.xz` | `f3fc62b313e7e8c582e910166675a8488d9857e18bf89494dd2c0f20bed33220` |
| Kobuki PC bag | `K_rosbug_phase5_v12_hardware_kobuki_r01.tar.xz` | `a641f53c6bc22bf408069cb6f5da64373fa484eb93db2db4efc0c0e67f9f0280` |
| カメラ録画 | `rokuga_phase5_v12_hardware_warning_r01_20260929_180756_604.tar.xz` | `66e055c8140d30691011ab536f1b16e6913b1bd05f75831417e8398d0219ad9b` |

カメラ録画時間窓は2026-09-29 18:07:56.604–18:08:40.480 JSTである。以下の試験判定はこの時間窓を主対象とした。

## カメラ・模擬ODOM

| 項目 | 結果 |
|---|---:|
| frame数 | 1,258 |
| raw/BEV/detection完全性 | 1,258/1,258/1,258、PASS |
| 青箱検出率 | 100.00% |
| ODOM利用可能frame | 1,088（86.49%） |
| `0.25 m/s`区間 | 18:08:19.18–18:08:29.17 JST、約10秒 |
| 移動判定frame | 286 |
| WARNING frame | 286 |
| active FFB frame | 9 |
| FFB publish failure | 0 |
| 青箱のfiltered distance | 中央値1.0867 m、範囲1.0862–1.0872 m |
| 有限TTC | 中央値4.3469 s、最小4.3452 s |

模擬ODOMの開始からWARNINGおよび最初のactiveまで約78.3 msだった。WARNINGは移動区間中に維持された一方、3連cadenceの完了後にactiveを繰り返さず、1イベントだけを通知できている。

## 3連cadence

カメラ側active sequenceは次の9件である。

`110704, 110705, 110706 / 110709, 110710, 110711 / 110714, 110715, 110716`

| 群 | frame | カメラ経過時間 | active継続 | 次群までの非active間隔 |
|---:|---|---|---:|---:|
| 1 | 646–648 | 22.688–22.771 s | 82.8 ms | 108.7 ms |
| 2 | 651–653 | 22.880–22.941 s | 61.1 ms | 112.0 ms |
| 3 | 656–658 | 23.053–23.118 s | 65.5 ms | ― |

ハンコンPCのstatusでも3件ずつの3群を確認した。各群の開始時刻間隔は約189 ms、173 msで、各active statusは要求値0.25を安全上限0.05へ制限して実機へ適用している。

## PC間伝送とhardware status

| 検査 | ハンコンPC bag | Kobuki PC bag |
|---|---:|---:|
| 録画時間内 active intent | 9 | 9 |
| 録画時間内 active command | 9 | 9 |
| 録画時間内 active status | 9 | 9 |
| intentのみでcommandなし | 0 | 0 |
| commandのみでstatusなし | 0 | 0 |
| 録画時間内 fault | 0 | 0 |
| status output mode | `hardware`のみ | `hardware`のみ |
| active status action | 9件すべて`apply` | 9件すべて`apply` |
| active status output | 9件すべて`true` | 9件すべて`true` |
| applied magnitude | 9件すべて0.05 | 9件すべて0.05 |

ハンコンPC bag基準の遅延中央値は、active intent→commandが0.464 ms、active command→statusが0.485 msだった。全9 sequenceはカメラ、intent、command、statusのすべてで一致した。

relay診断では録画時間内に1,256件をforwardし、2件を`receiver_challenge_already_used`として安全に見送った。active 9件はいずれもforwardされている。challengeは録画窓内で継続し、ハンコンPC側の最大間隔は21.1 msだった。`challenge_stream_restart_count`は全時間窓で5のまま増えず、試験中のstream再起動はない。

## 停止とfault

- 録画末尾のstatusは`command_active=false`、`output_active=false`、`reason=inactive:clear`、`fault=false`だった。
- bag全体の末尾は`reason=shutdown`、`output_active=false`、`fault=false`だった。
- bagには録画開始より前の17:14–17:49 JSTに16件のtoken拒否faultが残っているが、すべて`output_active=false`であり、今回の18:07以降の試験時間窓には含まれない。

## FPSに関する別判定

`analyze_field_recording.py`の自動判定は**FAIL**だった。理由は実効FPSが28.670で、要求30 fpsの±1%外だったことだけである。frame間隔中央値は33.234 msだが、p95は44.096 ms、40 ms超過率は15.67%だった。処理時間中央値は30.001 msで、処理時間が33.3 msを超える割合は32.19%だった。

今回のWARNING検知・3連hardware出力は欠落なく成功しているため、本試験の主判定はPASSとする。ただし、今後の動的試験に向け、FPS低下は性能課題として継続監視する。

## 次の試験

1. 同じv12構成でUNKNOWNを発生させ、実機で「単発振動」になることを確認する。
2. 有効測定を0.5秒以上復帰させて再armした後、2回目のUNKNOWNでも単発が1回だけ出ることを確認する。
3. 上記を通過後に、低速かつ停止余裕を確保したKobuki実走行へ進む。

一人試験で遮蔽タイミングが難しい場合は、今回のように自動模擬ODOMを使い、遮蔽担当とハンコン確認担当の二人で行う。実走行へ進む前に、UNKNOWNの実機出力と最終inactiveを先に確定させる。

## 生成物

- `phase5_v12_hardware_hsr_r01_bag_summary.json`
- `phase5_v12_hardware_hsr_r01_recording_window_events.csv`
- `phase5_v12_hardware_kobuki_r01_bag_summary.json`
- `phase5_v12_hardware_kobuki_r01_recording_window_events.csv`
- `phase5_v12_hardware_warning_r01_analysis/analysis_report.md`

bagは試験前の約1時間分も含むため、イベントCSVはカメラ録画時間窓だけを保存した。bag全体の件数、時間範囲および録画前faultは各`bag_summary.json`に残している。
