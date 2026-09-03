# TTC速度源オフライン比較

## 入力

- `/home/robo25/Downloads/recoding/recoding_08181725.tar.xz`
- `/home/robo25/Downloads/recoding/recoding_08181740.tar.xz`
- `/home/robo25/Downloads/recoding/202609011435.tar.xz`
- `/home/robo25/Downloads/202609031410.tar.xz`

## 方式

- `visual`: 現行の画像距離差分による相対速度。
- `odom_static`: 対象物が静止していると仮定し、相対速度を`-odom_linear_mps`とする。
- `conservative`: visualと`-odom_linear_mps`のうち、接近側で大きい速度を使う。

後二方式は候補方式であり、production既定値は`visual`のままとする。

## 集計

| 速度源 | 指定profile PASS | HOLD必須を外したPASS | 0.20 m/s WARNING成立 |
|---|---:|---:|---:|
| visual | 16/28 | 16/28 | 7/10 |
| odom_static | 22/28 | 22/28 | 10/10 |
| conservative | 21/28 | 21/28 | 10/10 |

## 0.20 m/s接近

| ラベル | 速度源 | 速度MAE | WARNING | 初回TTC | 厳格判定 | HOLD非必須判定 |
|---|---|---:|---:|---:|---|---|
| approach_center_v0p20_r01_20260818_173859_761 | visual | 0.0227 m/s | 35 | 4.504秒 | PASS | PASS |
| approach_center_v0p20_r01_20260818_173859_761 | odom_static | 0.0000 m/s | 35 | 4.597秒 | FAIL | FAIL |
| approach_center_v0p20_r01_20260818_173859_761 | conservative | 0.0060 m/s | 35 | 4.597秒 | FAIL | FAIL |
| approach_center_v0p20_r02_20260818_173929_852 | visual | 0.0203 m/s | 37 | 4.581秒 | PASS | PASS |
| approach_center_v0p20_r02_20260818_173929_852 | odom_static | 0.0000 m/s | 49 | 4.507秒 | FAIL | FAIL |
| approach_center_v0p20_r02_20260818_173929_852 | conservative | 0.0050 m/s | 54 | 4.507秒 | FAIL | FAIL |
| approach_center_v0p20_r03_20260818_173959_164 | visual | 0.0197 m/s | 34 | 4.588秒 | PASS | PASS |
| approach_center_v0p20_r03_20260818_173959_164 | odom_static | 0.0000 m/s | 43 | 4.542秒 | FAIL | FAIL |
| approach_center_v0p20_r03_20260818_173959_164 | conservative | 0.0070 m/s | 43 | 4.542秒 | FAIL | FAIL |
| approach_center_v0p20_r01_20260901_143052_426 | visual | 0.0268 m/s | 15 | 4.599秒 | FAIL | FAIL |
| approach_center_v0p20_r01_20260901_143052_426 | odom_static | 0.0000 m/s | 30 | 4.397秒 | PASS | PASS |
| approach_center_v0p20_r01_20260901_143052_426 | conservative | 0.0000 m/s | 30 | 4.397秒 | PASS | PASS |
| approach_center_v0p20_r02_20260901_143130_004 | visual | 0.0250 m/s | 13 | 4.569秒 | PASS | PASS |
| approach_center_v0p20_r02_20260901_143130_004 | odom_static | 0.0000 m/s | 21 | 4.478秒 | PASS | PASS |
| approach_center_v0p20_r02_20260901_143130_004 | conservative | 0.0001 m/s | 21 | 4.478秒 | PASS | PASS |
| approach_center_v0p20_r03_20260901_143206_639 | visual | 0.0239 m/s | 19 | 4.563秒 | FAIL | FAIL |
| approach_center_v0p20_r03_20260901_143206_639 | odom_static | 0.0000 m/s | 29 | 4.427秒 | FAIL | FAIL |
| approach_center_v0p20_r03_20260901_143206_639 | conservative | 0.0000 m/s | 29 | 4.427秒 | FAIL | FAIL |
| approach_center_v0p20_r04_20260901_143249_502 | visual | 0.0289 m/s | 13 | 4.566秒 | FAIL | FAIL |
| approach_center_v0p20_r04_20260901_143249_502 | odom_static | 0.0000 m/s | 26 | 4.583秒 | FAIL | FAIL |
| approach_center_v0p20_r04_20260901_143249_502 | conservative | 0.0000 m/s | 26 | 4.583秒 | FAIL | FAIL |
| approach_center_v0p20_r01_20260903_140715_416 | visual | 0.0385 m/s | 0 | ― | FAIL | FAIL |
| approach_center_v0p20_r01_20260903_140715_416 | odom_static | 0.0000 m/s | 10 | 4.594秒 | PASS | PASS |
| approach_center_v0p20_r01_20260903_140715_416 | conservative | 0.0000 m/s | 12 | 4.594秒 | PASS | PASS |
| approach_center_v0p20_r02_20260903_140754_182 | visual | 0.0384 m/s | 0 | ― | FAIL | FAIL |
| approach_center_v0p20_r02_20260903_140754_182 | odom_static | 0.0000 m/s | 8 | 4.511秒 | PASS | PASS |
| approach_center_v0p20_r02_20260903_140754_182 | conservative | 0.0000 m/s | 10 | 4.511秒 | PASS | PASS |
| approach_center_v0p20_r03_20260903_140831_916 | visual | 0.0341 m/s | 0 | ― | FAIL | FAIL |
| approach_center_v0p20_r03_20260903_140831_916 | odom_static | 0.0000 m/s | 12 | 4.586秒 | PASS | PASS |
| approach_center_v0p20_r03_20260903_140831_916 | conservative | 0.0000 m/s | 12 | 4.586秒 | PASS | PASS |

## 解釈

ODOMを使う二方式では、0.20 m/s接近の全試行でWARNINGが成立する。
`WARNING_HOLD`は警告成立後に観測が無効になった場合の有限保持状態であり、
遮蔽のない通常接近試験で1 frame以上を必須にすると、正常観測が続くほど不合格になる。
保持性能は警告後に意図的な遮蔽・欠測を入れた別試験で評価する必要がある。

`odom_static`は対象物の静止を仮定するため、未知の動的物体へそのまま適用できない。
`conservative`は接近速度の過小評価を避ける一方、対象物が遠ざかる場面では過警告になり得る。
本番採用前に、対象物クラスとFFBの安全要求を明確にする。
HOLD必須を外してもODOM候補には13件のFAILが残る。
これは速度源以外の条件も含むため、方式採否とは分けて試行別理由を確認する。

| HOLD以外の未達指標 | 件数 |
|---|---:|
| `direction_response_delay_sec` | 1 |
| `maximum_warning_entry_delay_sec` | 8 |
| `motion_track_rate` | 4 |
| `path_while_forward_after_warning_frames` | 2 |
| `steady_direction_correct_rate` | 1 |
