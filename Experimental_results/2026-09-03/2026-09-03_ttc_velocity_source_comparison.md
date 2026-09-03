# TTC速度源オフライン比較

## 入力

- `/home/robo25/Downloads/202609031410.tar.xz`

## 方式

- `visual`: 現行の画像距離差分による相対速度。
- `odom_static`: 対象物が静止していると仮定し、相対速度を`-odom_linear_mps`とする。
- `conservative`: visualと`-odom_linear_mps`のうち、接近側で大きい速度を使う。

後二方式はオフライン設計候補であり、本番実装ではない。

## 集計

| 速度源 | 現行profile PASS | HOLD必須を外したPASS | 0.20 m/s WARNING成立 |
|---|---:|---:|---:|
| visual | 6/9 | 6/9 | 0/3 |
| odom_static | 6/9 | 9/9 | 3/3 |
| conservative | 6/9 | 9/9 | 3/3 |

## 0.20 m/s接近

| ラベル | 速度源 | 速度MAE | WARNING | 初回TTC | 厳格判定 | HOLD非必須判定 |
|---|---|---:|---:|---:|---|---|
| approach_center_v0p20_r01_20260903_140715_416 | visual | 0.0385 m/s | 0 | ― | FAIL | FAIL |
| approach_center_v0p20_r01_20260903_140715_416 | odom_static | 0.0000 m/s | 10 | 4.594秒 | FAIL | PASS |
| approach_center_v0p20_r01_20260903_140715_416 | conservative | 0.0000 m/s | 12 | 4.594秒 | FAIL | PASS |
| approach_center_v0p20_r02_20260903_140754_182 | visual | 0.0384 m/s | 0 | ― | FAIL | FAIL |
| approach_center_v0p20_r02_20260903_140754_182 | odom_static | 0.0000 m/s | 8 | 4.511秒 | FAIL | PASS |
| approach_center_v0p20_r02_20260903_140754_182 | conservative | 0.0000 m/s | 10 | 4.511秒 | FAIL | PASS |
| approach_center_v0p20_r03_20260903_140831_916 | visual | 0.0341 m/s | 0 | ― | FAIL | FAIL |
| approach_center_v0p20_r03_20260903_140831_916 | odom_static | 0.0000 m/s | 12 | 4.586秒 | FAIL | PASS |
| approach_center_v0p20_r03_20260903_140831_916 | conservative | 0.0000 m/s | 12 | 4.586秒 | FAIL | PASS |

## 解釈

ODOMを使う二方式では、0.20 m/s接近の全試行でWARNINGが成立する。
厳格profileで残るFAIL理由は`warning_hold_frames=0`のみである。
`WARNING_HOLD`は警告成立後に観測が無効になった場合の有限保持状態であり、
遮蔽のない通常接近試験で1 frame以上を必須にすると、正常観測が続くほど不合格になる。
保持性能は警告後に意図的な遮蔽・欠測を入れた別試験で評価する必要がある。

`odom_static`は対象物の静止を仮定するため、未知の動的物体へそのまま適用できない。
`conservative`は接近速度の過小評価を避ける一方、対象物が遠ざかる場面では過警告になり得る。
本番採用前に、対象物クラスとFFBの安全要求を明確にする。
