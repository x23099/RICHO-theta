# 勾配方向の時間方向一致 r01（2026-11-21改訂）

## 1. 決定

- 方式：**直近3件の連続一致**（3-of-3 consecutive）
- 追加遅延の上限：**0.4 s**（5 Hzで2 frame）
- 確定しないときは**保留**。前回値を保持しない。
- 票は**個別に失効**する（`max_sample_age_sec`=0.5 s）。空白後に古い票を使わない。
- 実装：[src/driver_risk_consistency.py](../../../src/driver_risk_consistency.py)、試験：[tests/test_driver_risk_consistency.py](../../../tests/test_driver_risk_consistency.py)
- **まだ実装経路へ接続していない**（既定off・純粋ロジック）。ROS/FFB/操縦へは出さない。

## 2. なぜ2-of-3から変えたか

初版の2-of-3には2つの欠陥があった（合成入力で再現）。

1. **空白後に古い票で確定**：鮮度判定が最新sampleだけを見ており、2秒前の2票＋新1票で`confirmed=true`を返した。
2. **交互入力を落とせない**：`+,-,+,-,...`では常に3件中2件が一致するため、毎frame「確定」しながら符号が反転した。さらに1件の新sampleで古い方向へ戻る確定も起きた。

連続一致に変えると、交互入力は永久に確定せず、古い方向へ戻るには3件必要になる。遅延上限は2 frame（0.4 s）で変わらない。

## 3. 状態と出力

| 入力列（方向のみ） | 出力 | 理由 |
|---|---|---|
| `-1, -1, -1` | `-1` 確定 | 3連続一致 |
| `-1, -1, +1` | **保留** | 連続していない |
| `-1, +1, +1` | **保留** | 連続していない |
| `+1, +1, +1` | `+1` 確定 | 新しい方向が3連続 |
| 無効値・NaN | **保留**（windowをclear） | 欠測で古い合意を残さない |
| 0.5 sを超えた票 | **失効** | 空白後の古い票を使わない |
| 最終sampleが0.5 s超 | **保留**（stale） | 古い合意を確定に使わない |
| 時計逆行 | **停止**（closed） | 以後は確定しない |

- 方向は`gradient_normalized`へ既存と同じdeadband（0.1）を適用。
- 確定値は**最新sampleの`gradient_normalized`**（平均しない）。
- `added_latency_sec`は確定に使った3件のspan（3連続なら0.4 s）。方向変化の確定遅れの上限に対応する。
- `risk_level`は最新sampleの値を返すが、`confirmed=false`のときconsumerは使わない。

## 4. 遅延

固定0.4 s遅延ではない。定常状態でも3件のspanは0.4 sだが、**出力値は常に最新sample**である。方向が変わった場合、新しい方向が3件揃うまで確定しないため、最大2 frame（0.4 s）の確定遅れが生じる。これは「常に0.4 s古い値を出す」ことではない。

## 5. 接続時の契約（未実施）

1. motion bridgeの結果（`gradient_normalized`, `risk_level`, `valid`）を1 frameごとに`offer`する。
2. `confirmed=false`なら**FFBを保留**（effect停止または中立）。前回値の保持・再送はしない。
3. `confirmed=true`のときだけ`direction`と`gradient_normalized`をFFBへ渡す。
4. セッション変更・切断・時計逆行で`reset`する。
5. 既存`SteeringGradientFilter`のEMA・deadbandと二重になるため、接続時に役割分担を決める（本moduleは方向の確定、既存filterは値の平滑化）。

## 6. 未解決

- 実フィールドの`g`系列での検証は未実施。
- 3連続は単発外れ値で1〜2 frame保留になる。安全性側（保留）に倒れるが、可用性とのトレードオフは実機で確認する。
- リスク段階（WARNING/CRITICAL）自体の時間安定性は対象外。
- `controlling_distance` / `physical_metric_verified` / `usable_for_ffb` / `published_to_ros`はfalseのまま。
