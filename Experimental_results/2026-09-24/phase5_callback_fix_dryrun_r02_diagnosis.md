# Phase 5 callback修正後 dry-run r02診断（2026-09-24）

## 判定

**challenge/ODOM callback安定化とPC間dry-run FFB経路はPASS。録画品質の30 fps±1%条件だけFAIL。**

録画中のchallenge受信累計は1,566から3,095へ毎フレーム増加し、3フレーム以上停止した区間は0件だった。challenge ageは平均9.77 ms、p95 19.19 ms、最大29.89 msで、送信側期限60 msを全897フレームで満たした。修正前に発生した数秒単位の`no_recent_receiver_challenge`は0件となり、FFB publishは897/897件成功した。

青箱検知、0.25 m/s模擬ODOM、WARNING、triple active指令、PC間伝送、dry-run adapter適用まで同じ9 sequenceで成立した。全statusは`dry_run`、faultは0件、最後はinactiveの`shutdown`だった。

標準解析の自動判定FAILは実効FPS 29.286が許容下限29.7を下回ったためであり、callback/FFB経路の機能判定とは分ける。今回の主目的であるcallback修正効果の確認に、同条件の再録画は不要である。

## 入力

| 入力 | SHA-256 |
|---|---|
| `phase5_callback_fix_dryrun_r02_20260924_172351_631.tar.xz` | `51e21cd207f07fb8624ee6d1e7131561d090b7113edf59f8e0183106e5899b1e` |
| `phase5_callback_fix_kobuki_r02.tar.xz` | `30328c7d9d8ad25c44ad30f2197ff57ffc8446f6359c83b815b6cd89c5d5cf64` |
| `phase5_callback_fix_hsr_r02.tar.xz` | `11883431fbd022244827b015fe6c80fc05a444af63df3c5aad9082d78b4f3025` |

## カメラ・認識・TTC

| 指標 | 結果 |
|---|---:|
| frame / raw・BEV・detection | 897 / 897・897・897 |
| 実効FPS | 29.286（品質条件FAIL） |
| 有効処理時間p95 | 34.76 ms |
| 青箱検出・観測採用・追跡 | 各897/897（100%） |
| ODOM available | 702/897（78.26%） |
| 0.25 m/s観測 | 104フレーム、録画開始16.041～19.474秒 |
| 最小TTC | 4.51141秒 |
| WARNING | 104フレーム、16.108～19.541秒 |
| FFB active | 9フレーム、16.108～16.508秒 |

リスクは`CLEAR`791、`PATH`2、`WARNING`104フレームだった。active 9件はtriple cadenceの3回のON区間に対応し、要求強度はすべて0.25だった。WARNING継続中の残りはcadence gapまたはcadence完了であり、異常な欠落ではない。

## callback診断

| 指標 | 結果 |
|---|---:|
| challenge受信累計 | 1,566 → 3,095（増分1,529） |
| challenge累計の減少 | 0回 |
| 3フレーム以上の停止 | 0区間 |
| challenge age 平均 / p95 / 最大 | 9.77 / 19.19 / 29.89 ms |
| 60 ms超過 | 0/897 |
| `no_recent_receiver_challenge` | 0/897 |
| FFB publish成功 | 897/897 |
| ODOM受信累計 | 957 → 1,653（増分696、減少0回） |

50 Hz challengeに対し、約30.6秒で1,529件増加しており、期待値約1,530件と一致する。全フレームで新鮮なchallengeを利用できたため、専用executorへの変更により前回の長時間callback停止は解消したと判定する。

ODOM累計が同じフレームは、0→0.25→0 m/sのpublisher手動切替中に送信元が存在しない区間と対応する。0.25 m/sはKobuki bagで90件記録され、カメラ側で104フレーム利用された。ODOM callbackにも説明不能な停止はない。

## 両PCのbag・FFB照合

| 指標 | Kobuki PC bag | ハンコン接続PC bag |
|---|---:|---:|
| challenge | 3,352 | 6,101 |
| command | 1,801 | 1,912 |
| status | 1,800 | 1,911 |
| 0.25 m/s ODOM | 90 | 81 |
| active command / status | 9 / 9 | 9 / 9 |
| fault | 0 | 0 |
| status mode | 全件`dry_run` | 全件`dry_run` |
| 最終status | inactive `shutdown` | 同左 |

bag全体の開始・終了時刻が異なるため全件数は直接比較しない。カメラ、Kobuki bag、ハンコンbagに共通するactive sequenceは次の9件で完全一致した。

`1326, 1327, 1328, 1332, 1333, 1334, 1336, 1337, 1338`

9件すべてでadapterは`action=apply`、`output_active=true`、要求0.25、適用0.05、`fault=false`だった。ハンコン側のcommand→status応答は0.211～0.682 ms、中央値0.504 ms。利用tokenのchallenge発行からactive command到着まではハンコン側で3.95～24.55 ms、Kobuki側で1.98～21.86 msであり、60 ms/100 msの期限内だった。

## FPS低下

実効FPSは29.286、フレーム間隔p95は43.67 ms、有効処理p95は34.76 msだった。前半FPS 28.611、後半29.993であり、後半は目標へ復帰している。raw/BEV/detection/CSVは各897件で一致し、映像欠損はない。callback安定性とFFB sequence照合は成立しているため、このFPS単独FAILを理由に同じ統合試験を繰り返す必要はない。今後、正式な30 fps録画品質を要求する試験では、bag圧縮・ファイル転送・ダウンロードなどの負荷を録画と同時に動かさない。

## 結論と次段階

challenge方式のdry-run統合は機能的にPASSした。次は同一録画の反復ではなく、challenge方式をhardwareへ展開する前の安全レビュー、またはFPS低下要因の独立診断へ進む。現行adapterはchallenge + hardwareをコード上で禁止しているため、当日の判断だけでhardwareへ切り替えない。

## 成果物

- [標準解析](phase5_callback_fix_dryrun_r02_analysis/analysis_report.md)
- `phase5_callback_fix_kobuki_r02_bag_summary.json`
- `phase5_callback_fix_kobuki_r02_events.csv`
- `phase5_callback_fix_hsr_r02_bag_summary.json`
- `phase5_callback_fix_hsr_r02_events.csv`
- [WARNING区間の無編集生画像](report_assets/raw_phase5_callback_fix_dryrun_r02_active.png)
- [challenge受信安定性グラフ](report_assets/callback_health_and_ffb_r02.png)
