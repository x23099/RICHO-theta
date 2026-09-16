# 2026-09-16 triple cadence実機比較・ライブ経路実装

## 結論

G923を停止状態で比較した結果、`triple / 0.05 / 0.5秒`だけが回数を明瞭に識別できた。
この条件をPhase 5の採用候補とし、認識側publisherへ有限cadenceとして実装した。
強度上限、ROS message、hardware adapter、watchdogは変更していない。

## 実機比較

| cadence | 応答p95 [ms] | CLEAR停止 [ms] | fault | 操作者評価 | 判定 |
|---|---:|---:|---:|---|---|
| continuous | 1.272 | 0.849 | 0 | 危険通知として知覚可能だが少し弱い | PASS |
| double | 1.200 | 0.717 | 0 | 2回の区切りは明瞭でない | PASS |
| triple | 1.244 | 1.047 | 0 | 3回として識別可能 | PASS |

watchdog試験は、0.05 active指令の約106 ms後に`watchdog_timeout`で停止した。
この試験の`fault=True`は意図した安全停止である。CLEAR、shutdown、node再起動でも残留出力、
slot枯渇、writer競合、異音、急回転、発熱は確認されなかった。

## 実装仕様

- 従来設定の既定値は`continuous`とし、後方互換性を維持する。
- `bird_eye_config_ttc_v7_ffb_triple_20260916.json`だけが`triple`を明示する。
- WARNING開始時に、3フレームON、2フレームOFFを3回、計0.5秒で生成する。
- WARNING_HOLDだけでは再発火せず、継続警告中も1セットで終了する。
- CLEAR/PATHはcadence途中でも即座に停止し、次の警告を再び許可する。
- CRITICALへの上昇時は、新しいtripleを開始する。
- publisher要求0.25/0.40は維持し、adapter側で実機上限0.05へ制限する。

警告パルスの長さ・回数が運転者反応へ影響し得るという先行研究と、今回のG923実測を根拠に、
強度増加より先に識別可能な有限パターンを採用した。

- Brown et al., “Effects of Haptic Brake Pulse Warnings on Driver Behavior during an Intersection Approach”:
  https://doi.org/10.1177/154193120504902202
- ROS 2 Humble QoS documentation:
  https://docs.ros.org/en/humble/Concepts/Intermediate/About-Quality-of-Service-Settings.html

## 過去録画dry-run

- 入力: `202609081640.tar.xz`
- session: `approach_center_v0p20_r02_v6holdout_20260908_163811_391`
- command/status: 630/630
- active command/status: 13/13
- fault: 0
- 最大adapter適用強度: 0.05
- 最終状態: inactive
- 自動判定: PASS

最初のWARNING区間では3回のON区間を生成し、後続WARNING_HOLDでは再発火しなかった。
後半の短いUNKNOWN区間は従来policyどおり注意通知を開始し、PATH/CLEARで即時停止した。

## 検証

- 関連単体試験: 31 passed
- 全回帰試験: 173 passed
- 新規・独立モジュールflake8/pydocstyle: PASS
- legacy統合ファイル: fatal syntax/name検査PASS
- shell構文: PASS
- `git diff --check`: PASS

## 次の実機作業

1. ハンコン接続PCとKobuki PCで最新commitを取得する。
2. 新しいv7設定を使い、Kobukiを停止したままpreflightを実行する。
3. adapterをhardware 0.05で起動する。
4. 録画riskまたは静止した青箱で、ライブ経路のtriple、CLEAR、終了停止を1イベント確認する。
5. 停止状態でPASSした後にだけ、走行を伴う試験を別段階で実施する。
