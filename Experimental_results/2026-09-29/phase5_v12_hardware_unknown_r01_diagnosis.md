# Phase 5 v12 hardware UNKNOWN試験 診断

## 結論

**判定: PASS（UNKNOWN単発の実ハードウェア出力）**

カメラで青箱を遮蔽した後、WARNING holdが切れた時点でUNKNOWN単発が生成され、`intent -> relay -> command -> hardware status`の全段を欠落なく通過した。ハンコン側では`output_mode=hardware`、`action=apply`、`output_active=true`、要求0.15、適用0.05、`fault=false`を確認した。利用者が全振動を体感できたという報告は、記録上の「WARNING 3連、UNKNOWN単発、復帰後WARNING 3連」と一致する。

有効測定はUNKNOWN後に4.238秒連続しており、0.5秒の再arm条件を十分に満たした。ただし、2回目の遮蔽開始は模擬速度0.25 m/s区間の終了約0.19秒前だった。0.8秒のWARNING holdが切れる前に速度0へ移行したため、2回目のUNKNOWN自体は発生していない。したがって、**同一実機試行内での2回目のUNKNOWN出力だけは未評価**であり、再arm故障を示す結果ではない。

v12 dry-runでは2回のUNKNOWNと再armを既に確認済みで、今回の試験ではUNKNOWNから実ハードウェアまでの出力経路を確認できた。この2つを組み合わせれば次段階へ進めるが、単一試行での完全な再現記録が必要なら、移動区間を延ばした再試験を行う。

## 入力

| 種別 | ファイル | SHA-256 |
|---|---|---|
| カメラ録画 | `rokuga_phase5_v12_hardware_unknown_r01_20260929_184546_956.tar.xz` | `6d06b111008a3cd4bd40a172671d5712e1aef6a3a8c4dcea036120d1d08f94e0` |
| Kobuki PC bag | `K_rosbug_phase5_v12_hardware_unknown_kobuki_r01.tar.xz` | `96b10946414da73129b81e15f6c111304b4625df994e420c5c776e353fce3415` |
| ハンコンPC bag | `H_rosbug_phase5_v12_hardware_unknown_hsr_r01.tar.xz` | `cd06d77efed6db5c7d780f2892a2a02d7ef4a140ac956c2b1461e1000cac4808` |

カメラ録画時間窓は2026-09-29 18:45:46.956–18:46:30.914 JSTである。疑似ODOM CSVは未添付だが、両bagに待機0、0.25 m/s 450件、最終0が記録されているため、今回のイベント判定には不足しない。

## カメラと状態遷移

| 項目 | 結果 |
|---|---:|
| frame数 | 1,301 |
| raw/BEV/detection完全性 | 1,301/1,301/1,301、PASS |
| 実効FPS | 29.588 |
| 青箱検出frame | 821（63.11%） |
| ODOM利用可能frame | 915（70.33%） |
| 0.25 m/s区間 | 録画経過10.599–25.579秒、約15秒 |
| WARNING frame | 269 |
| WARNING_HOLD frame | 34 |
| UNKNOWN frame | 61 |
| active FFB frame | 22 |
| FFB publish failure | 0 |

主要な状態遷移は次のとおりだった。

| 事象 | frame | 録画経過時間 | 内容 |
|---|---:|---:|---|
| 1回目WARNING | 389–528 | 13.416–18.243 s | 青箱有効、3連cadenceを出力 |
| 1回目遮蔽 | 531–616 | 18.336–21.085 s | 測定無効 |
| UNKNOWN | 556–616 | 19.127–21.085 s | 遮蔽開始約0.79秒後に成立、単発出力 |
| 有効測定復帰 | 617–744 | 21.117–25.355 s | 4.238秒連続、再arm条件0.5秒を満たす |
| 2回目遮蔽 | 745以降 | 25.391 s以降 | 0.25 m/s終了直前のためUNKNOWNへ遷移せず |

## 実機振動イベント

active 22件の内訳は、WARNING 20件とUNKNOWN 2件だった。

| イベント | sequence | active群 | 要求強度 | 適用強度 | 体感との対応 |
|---|---|---:|---:|---:|---|
| WARNING 1 | 5510–5521 | 4件・3件・3件の3群 | 0.25 | 0.05 | 3連振動 |
| UNKNOWN 1 | 5677–5678 | 2件の1群 | 0.15 | 0.05 | 短い単発振動 |
| WARNING 2 | 5738–5750 | 4件・3件・3件の3群 | 0.25 | 0.05 | 復帰後の3連振動 |

実効FPSが30 fpsをわずかに下回ったため、各WARNING cadenceは標準設計のactive 9 frameではなく10 frameになった。ただし、ON区間は3群のままであり、余分な4回目の振動イベントではない。

## PC間伝送と安全状態

| 検査 | ハンコンPC bag | Kobuki PC bag |
|---|---:|---:|
| 録画時間内 active intent | 22 | 22 |
| 録画時間内 active command | 22 | 22 |
| 録画時間内 active status | 22 | 22 |
| active intent欠落 | 0 | 0 |
| active command欠落 | 0 | 0 |
| active見送り | 0 | 0 |
| 録画時間内fault | 0 | 0 |
| adapter mode | `hardware`のみ | `hardware`のみ |

ハンコンPC bag基準の遅延中央値はactive intent→commandが0.441 ms、command→statusが0.429 msだった。Kobuki PC bagでのcommand→status中央値は2.977 msだった。

録画時間内にはinactive intentの見送りが6件あり、内訳は`receiver_challenge_already_used` 5件、`stale_receiver_challenge` 1件だった。active intentの見送りは0件である。challenge stream restart countは録画中ずっと2のままで増加せず、stream不安定化はなかった。Kobuki PC bagでのchallenge最大間隔97.3 msはstream timeout 200 ms未満である。

録画末尾のstatusは`output_active=false`、`reason=inactive:clear`、`fault=false`、bag全体の末尾は`reason=shutdown`だった。bag全体でもfaultは0件である。

## FPS判定

汎用解析器の自動判定は**FAIL**だった。理由は実効29.588 fpsが30 fpsの±1%範囲をわずかに下回ったためである。

- frame間隔中央値: 33.179 ms
- frame間隔p95: 40.599 ms
- 40 ms超過率: 5.62%
- 有効処理時間p95: 31.950 ms

録画完全性、FFB publish、PC間伝送および実機出力に欠落はなく、前回の28.670 fpsからは改善している。今回のUNKNOWN実機判定はPASSとするが、FPSは動的実走行に向けた監視項目として残す。

## 次の判断

研究進行上は、次の根拠が揃った。

1. v12 dry-runでUNKNOWN 2回、0.5秒再arm、短い復帰での再通知抑止を確認済み。
2. hardware WARNING試験で3連実機出力を確認済み。
3. 今回のhardware UNKNOWN試験で単発実機出力を確認済み。
4. いずれもactive欠落0、試験中fault 0、最終inactiveだった。

したがって、同じ試験の繰り返しは必須ではなく、次は安全条件を限定した低速Kobuki実走行の準備へ進める。単一試行で2回目UNKNOWNまで記録したい場合だけ、模擬移動区間を25秒へ延ばし、2回目遮蔽を終了5秒以上前に行う。

## 生成物

- `phase5_v12_hardware_unknown_r01_analysis/`
- `phase5_v12_hardware_unknown_hsr_r01_bag_summary.json`
- `phase5_v12_hardware_unknown_hsr_r01_recording_window_events.csv`
- `phase5_v12_hardware_unknown_kobuki_r01_bag_summary.json`
- `phase5_v12_hardware_unknown_kobuki_r01_recording_window_events.csv`
- `report_assets/phase5_v12_hardware_unknown_raw_frame_0556.png`
- `report_assets/phase5_v12_hardware_recovery_raw_frame_0617.png`

bag全体の件数と時間範囲は各`bag_summary.json`へ保存し、イベントCSVはカメラ録画時間窓だけへ限定した。
