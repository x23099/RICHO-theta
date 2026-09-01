# 衝突警告ヒステリシス実装・回帰結果（2026年8月18日）

## 結論

近距離で位置観測またはTTCが不安定になった際、確定済みの警告が即座に`PATH`へ戻る問題へ対処した。警告を無期限に固定する方式にはせず、最大0.8秒の`WARNING_HOLD`後に`UNKNOWN`へ移す。これにより、誤警告で永久に警告が残ることと、不明な状態を安全扱いすることの両方を避ける。

過去の0.20 m/s接近3試行を再生した結果、修正前に存在した「警告後・前進中の`PATH`」は全試行で0フレームになった。静止6条件では新たな警告は0件だった。単体・統合テストは32件すべて成功した。

## 状態と遷移条件

| 状態 | 意味 | 主な遷移条件 |
|---|---|---|
| `CLEAR` | 予測経路外 | 有効な経路外観測 |
| `PATH` | 経路内だが警告条件外 | 有効なTTCが解除しきい値以上 |
| `WARNING` | TTCが警告しきい値以下 | 3フレーム連続確認 |
| `CRITICAL` | TTCが重大しきい値以下 | 有効観測なら即時、確認待ちなし |
| `WARNING_HOLD` | 確定警告後の短時間の不明 | 最後の確定警告から最大0.8秒 |
| `UNKNOWN` | 安全とも危険とも確定不能 | 保持時間超過、または前進中の無効観測 |

解除は警告成立より慎重にし、次のいずれかを3フレーム連続で確認する。

- 障害物が予測経路外へ移った。
- TTCが5.0秒以上になった。
- 車体が停止または後退した。

TTCが4.0秒を超えて5.0秒未満の範囲では警告を維持する。TTCが算出不能なだけでは安全証拠にならないため、前進中は`PATH`へ解除しない。

## 固定した設定値

| 設定 | 値 |
|---|---:|
| 警告TTC | 4.0 s |
| 重大TTC | 2.0 s |
| 警告解除TTC | 5.0 s |
| 警告成立確認 | 3 frames |
| 警告解除確認 | 3 frames |
| 有限警告保持 | 0.8 s |
| 前進判定しきい値 | 0.03 m/s |

CSVには従来の最終`collision_risk_level`に加えて、生判定、遷移理由、保持経過時間、観測有効性を記録する。

- `collision_raw_risk_level`
- `collision_state_reason`
- `collision_hold_age_sec`
- `collision_measurement_valid`

## 過去録画の再生結果

### P0-C、0.20 m/s接近

| 試行 | 生警告 | フィルタ後警告系 | 保持 | 不明 | 警告後・前進中の`PATH` |
|---|---:|---:|---:|---:|---:|
| r01 | 12 | 27 | 21 | 0 | 0 |
| r02 | 13 | 25 | 20 | 16 | 0 |
| r03 | 13 | 24 | 20 | 13 | 0 |

フィルタ後警告系は`WARNING/CRITICAL/WARNING_HOLD`の合計である。警告成立の最大遅延は約0.081秒で、0.5秒以内という実験条件を十分下回った。

### 回帰確認

- P0-B静止6条件: 警告0、保持0、不明0。
- P0-C 0.10 m/s接近・後退6条件: 警告0。1試行のみ前進中の無効観測を`UNKNOWN`として49フレーム記録した。

詳細は次のCSVへ保存した。

- `Experimental_results/2026-08-18_p0b_hysteresis_replay.csv`
- `Experimental_results/2026-08-18_p0c_v0p10_hysteresis_replay.csv`
- `Experimental_results/2026-08-18_p0c_v0p20_hysteresis_replay.csv`

## 実装範囲と安全上の位置づけ

本実装は画面表示とCSV記録を安定化する評価用ロジックであり、Kobukiの速度指令、FFB、自動停止には接続していない。`UNKNOWN`は安全判定ではない。実験中に`UNKNOWN`が出た場合は操作者が停止する。

## 次の実機確認

1. NUCへ実装と設定を反映し、全32テストを実行する。
2. P0-B中央静止を1回録画し、誤警告がないことを確認する。
3. 青箱中央、開始z=1.30 m、0.20 m/s接近を新規holdoutとして3回録画する。
4. `WARNING`表示で停止操作を開始し、z=0.65 mの物理停止線を越えない。
5. 3試行すべてで警告発生、警告後・前進中の不明区間が`PATH`にならないこと、停止後に解除できることを確認する。

## 設計根拠

Autowareの動的障害物停止モジュールは、状態の頻繁な切替えを防ぐためヒステリシスと追加・解除の時間バッファを分けている。境界逸脱判定でもON/OFFバッファを分け、緊急時は待ち時間を省略する。AEBには衝突状態と直前障害物を有限時間保持する設定があり、長い保持は不要作動を増やすというトレードオフが明記されている。本実装は、この考え方を小型ロボットの表示・記録用途へ縮約した。

参考:

- Autoware Dynamic Obstacle Stop: https://autowarefoundation.github.io/autoware_universe/main/planning/motion_velocity_planner/autoware_motion_velocity_dynamic_obstacle_stop_module/
- Autoware Boundary Departure Checker: https://autowarefoundation.github.io/autoware_universe/main/common/autoware_boundary_departure_checker/
- Autoware Autonomous Emergency Braking: https://autowarefoundation.github.io/autoware_universe/main/control/autoware_autonomous_emergency_braking/
