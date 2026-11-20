# 勾配方向の時間方向一致 r01（2026-11-20）

## 1. 決定

- 方式：**2-of-3**（直近3 frameのうち2つが同じ方向なら確定）
- 追加遅延の上限：**0.4 s**（5 Hzで2 frame）
- 確定しないときは**保留**。前回値を保持しない。
- 実装：[src/driver_risk_consistency.py](../../../src/driver_risk_consistency.py)、試験：[tests/test_driver_risk_consistency.py](../../../tests/test_driver_risk_consistency.py)
- **まだ実装経路へ接続していない**（既定off・純粋ロジック）。ROS/FFB/操縦へは出さない。

## 2. なぜ必要か

[入力経路の決定](../input_path_decision_r01/README.md)の感度解析で、距離が**1 cm**動くだけでFFB方向場が反転する格子が225中4件あった。原因は`in_collision_corridor`の二値判定で、境界近傍では測定のわずかな差が方向反転になる。codecを可逆にしても、実運動や検出揺れで境界を跨げば同じことが起きる。

したがって、**1 frameの`g`をそのままFFBへ出さない**ことを入力契約にする。

## 3. 状態と出力

| 入力列（方向のみ） | 出力 | 理由 |
|---|---|---|
| `-1, -1, -1` | `-1` 確定（遅延0） | 定常一致 |
| `-1, -1, +1` | `-1` 確定（遅延1 frame） | 単発の反転を落とす |
| `-1, +1, +1` | `+1` 確定（遅延0） | 新しい側が2票 |
| `-1, +1, 0` | **保留** | 3方向に割れた |
| 無効値・NaN | **保留**（windowをclear） | 欠測で古い合意を残さない |
| 最終sampleが0.5 s超 | **保留**（stale） | 古い合意を確定に使わない |
| 時計逆行 | **停止**（closed） | 以後は確定しない |

- 方向は`gradient_normalized`へ既存と同じdeadband（0.1）を適用して求める。
- 確定時の`gradient_normalized`は**一致した最新sampleの値**。平均しない。
- `risk_level`は最新sampleの値を返すが、`confirmed=false`のときconsumerは使わない。
- `added_latency_sec`を出力し、遅延を記録できる。

## 4. 遅延の考え方

固定0.4 s遅延ではなく、**遷移時のみ最大0.4 s**。

- 定常：3 frameが一致しているので、最新sampleで即確定（遅延0）。
- 変化：新しい方向が2票になるまで確定しない。最大で2 frame（0.4 s）。
- これは「常に0.4 s遅らせる」より応答が良く、安全性の要件（古い値を保持しない）も満たす。

## 5. 接続時の契約（未実施）

1. motion bridgeの結果（`gradient_normalized`, `risk_level`, `valid`）を1 frameごとに`offer`する。
2. `confirmed=false`なら**FFBを保留**（effect停止または中立）。前回値の保持・再送はしない。
3. `confirmed=true`のときだけ`direction`と`gradient_normalized`をFFBへ渡す。
4. セッション変更・切断・時計逆行で`reset`する。
5. 既存`SteeringGradientFilter`のEMA・deadbandと二重になるため、**どちらを最終段にするか**を接続時に決める（本moduleは方向の確定、既存filterは値の平滑化）。

## 6. 未解決

- 実フィールドの`g`系列での検証は未実施（保存frameは3枚のみ）。
- リスク段階（WARNING/CRITICAL）自体の時間安定性は本moduleの対象外。必要なら同様の2-of-3を段階へ適用する。
- 0.4 sが衝突リスクに対して十分短いかは、実速度・制動距離との比較が必要。今回はユーザー指定の上限として実装した。
- `controlling_distance` / `physical_metric_verified` / `usable_for_ffb` / `published_to_ros`はfalseのまま。
