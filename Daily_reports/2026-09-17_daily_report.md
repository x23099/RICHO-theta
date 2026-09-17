# 2026年9月17日 日報

## 本日の到達点

実カメラ・青箱・専用模擬ODOMを用いて、Kobuki PCからハンコン接続PCへ衝突警告を送るPhase 5試験を進めた。従来の時刻比較方式では、PC間時刻差の変動により、警告指令が届いてもadapterに拒否される事象を再現した。その対策として、受信側が短命tokenを発行する時計非依存のchallenge方式を両リポジトリに実装し、ローカルとPC間probeを通した。

最終の実カメラ・模擬ODOM・PC間**dry-run**では、WARNINGからのactive指令8件がすべてadapterに受理され、0.05の論理出力になった。ただし、カメラ側でchallengeを利用できず送信を見送ったフレームが455/742、期限切れ等のfaultが3件、実効FPSが29.524で既存の30fps±1%基準を下回った。したがって、経路の成立は確認したが、**統合試験全体は未合格**。新方式のG923物理出力、実走行は行っていない。

## 実験条件と安全条件

| 項目 | 条件 |
|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5`：カメラ、`bird_eye.py`、FFB command送信 |
| ハンコン接続PC | `hsr-Alienware-m16-R2`：adapter、FFB status・ROS bag記録 |
| ROSドメイン | 両PCとも`88`。旧ドメインのadapter混在に注意 |
| 対象・速度 | 青箱、専用`/phase5/mock_odom`に0.25 m/sを短時間送信。実ロボットの`/odom`へは混入させない |
| FFB | v7 triple cadence、adapter上限0.05。新方式は`dry_run`限定で、hardware起動はコード上禁止 |
| 記録 | Kobuki側カメラ録画とハンコン側ROS bagを別々に保存し、FFB sequenceで照合 |

## 本日の主な検証結果

| 試験 | active指令 | adapterのactive status | 判定・主な理由 |
|---|---:|---:|---|
| r01 実カメラ・dry-run | カメラ側10 | bagに該当区間なし | bagが警告区間を記録せず、受理は未判定 |
| r02 実カメラ・再試験 | 8 | 0 | 指令は届いたが`future_message`。status全件が想定外の`disabled` |
| r02録画riskのPC間再生 | 9 | 9 | `dry_run`でPASS、fault 0。ただしライブカメラではない |
| r03 実カメラ・dry-run | 9 | 9 | ライブFFB経路はPASS。録画品質は25.456 FPSでFAIL |
| r04 停止状態のhardwareライブ | 10 | 0 | active全件が未来時刻として拒否。`dry_run`と`hardware`のadapter二重起動もbagで確認 |
| r05 hardwareライブ | 9 | 0 | active全件が約58 ms未来として拒否。振動なしはログと一致 |
| r06 challenge方式・実カメラdry-run | 8 | 8 | 8件適用、future fault 0。ただしchallenge見送り・token fault・FPSで全体未合格 |

r01～r05の詳細は[当日の診断群](../Experimental_results/2026-09-17/)を参照。r04/r05の無振動は、少なくとも該当指令については強度不足ではなく安全検査で出力されなかったことを示す。r03で一度受理できても時刻差が後の試験で変化したため、NTPの「同期済み」表示だけに依存した運用は採らない。

## 時計非依存方式の実装・検証

受信側adapterが約50 Hzでsession/tokenを発行し、送信側が直近tokenを指令へ添付する。adapterは**自身の単調時計**で発行後100 ms以内かを検証し、無効・欠落時は停止する。既定の時刻比較方式、強度上限、watchdogは維持した。Kobuki側はchallengeが新鮮でないと指令を送らない。設計と制約は[handover文書](../handover/clock_independent_ffb_design_20260917.md)に記録した。

FFB側の対象テスト73件、カメラ側169件がPASS。隔離したローカルROS dry-runではactive 15/15、fault 0。カメラなしのPC間probeは操作者からPASS・問題なしとの報告を受けた。ただし、その報告に対応するbag/CSVをここでは独立照合していない。FFBリポジトリ全体lintは旧ファイルも含めて失敗する状態で、変更対象ファイルのflake8はPASSした。

## r06 実カメラdry-runの定量結果

使用アーカイブはハンコン側`202609171820.tar.xz`、Kobuki側`202609171821.tar.xz`。SHA-256、sequence照合、faultの内訳は[詳細診断](../Experimental_results/2026-09-17/phase5_challenge_dryrun_r06_diagnosis.md)に保存した。

| 指標 | 実測 |
|---|---:|
| フレーム・青箱検出 | 742・742/742 |
| 録画完全性 | CSVとraw/BEV/detection動画が各742フレームで一致 |
| 実効FPS / 有効処理p95 | 29.524 / 29.47 ms |
| 模擬ODOM 0.25 m/s | bagで89件、約2.93秒 |
| WARNING / FFB active | 24フレーム / 8フレーム |
| active指令とstatus | 同一sequenceの8/8が`dry_run`、`action=apply`、`output_active=true`、適用0.05、faultなし |
| 最初のWARNINGから初回activeまで | 約0.266秒。先頭8 WARNINGフレームはchallengeなしで見送り |
| challenge利用不可による送信見送り | 455/742フレーム（61.3%） |
| adapter fault | 3件：期限切れ1、未知token2。いずれも非active指令で安全停止 |
| 最終status | `shutdown`、`output_active=false` |

ハンコン側bagにはchallengeが約50 Hzで記録され、発行間隔最大は約21 msだった。しかし、それだけではKobuki PCでの受信を証明できない。受信ネットワークとカメラ側callback処理のどちらが見送りの主因かは**未確定**。3件のtoken faultは、送信側が受信後100 ms近くまでtokenを使う一方、受信側は発行後100 msで失効させる境界条件と整合する。録画一括解析の自動FAILはFPS基準によるもので、FFB activeの8/8受理とは分けて扱う。

## 成果物・未解決事項・次回

- [r06標準解析](../Experimental_results/2026-09-17/phase5_challenge_dryrun_r06_analysis/analysis_report.md)、[bag集計](../Experimental_results/2026-09-17/phase5_challenge_live_r06_bag_summary.json)、[全イベントCSV](../Experimental_results/2026-09-17/phase5_challenge_live_r06_events.csv)を保存した。生録画は`/home/robo25/Downloads/`に置き、Gitへは入れない。
- [代表グラフ2点](../Experimental_results/2026-09-17/report_assets/README.md)をCSV・JSONから作成した。生カメラ画像は追加していないため、画像の加工も行っていない。
- 明日は、Kobuki側challenge受信を別bagとカメラ側診断値で可視化し、配信欠落かcallback不足かを切り分ける。その後、送信側token利用期限を安全側に短縮する案を検証し、単一adapter・専用模擬ODOMでdry-runを再試験する。**hardwareへの移行と走行は、安定性・fault 0・FPS基準が確認されるまで保留する。**
- 手順と停止条件は[2026-09-18作業計画](../Experimental_results/2026-09-18/2026-09-18_work_plan.md)に記載した。

## Gitの状態

本日の先行コミットは`0f27723`、`cfcb90d`、`45ad116`。この日報・r06解析・図表は追加成果物として同じリポジトリで管理する。FFB側リポジトリに今回新たな未コミット変更はない。
