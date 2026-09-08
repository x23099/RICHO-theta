# 2026年9月8日 日報

## 1. 本日の目的と到達点

本日は、事前固定した動的TTC v5候補の独立holdout評価を行い、結果を基に次期v6候補を設計・実装した。
さらに、G923のForce Feedback（FFB）能力を読み取り専用で確認し、TTC警告を実機FFBへ接続するための
実施計画を作成した。計画承認後はPhase 1として、意味付きROS 2メッセージとデバイス非依存の安全ポリシーを
実装した。

本日の主な到達点は次のとおりである。

1. v5独立holdout 12試行を解析し、固定条件でのFAILと原因を確定した。
2. UNKNOWNから誤ってWARNINGへ遷移するヒステリシス不具合を修正した。
3. 実測TTCと走行区間を基準にするv6評価条件、および近距離観測用の面積ゲート候補を追加した。
4. v6追加録画では、正式3試行すべてで確認可能な警告機会に対するWARNING成立を確認した。
5. G923が必要なFFB effectを備え、現在のユーザー権限で読み書きできることを確認した。
6. TTC連動FFBのPhase 1を実装し、ROS 2 interface、fail-closed検証、100 ms watchdogを完成させた。

G923への物理FFB出力は行っていない。Kobukiの速度指令、自動停止、YOLO認識にも変更を加えていない。

## 2. 開始時点

| 項目 | 開始時点 |
|---|---|
| TTC候補 | v5 `conservative`速度源 |
| v5評価状態 | 9月3日の既使用録画による事後診断のみ |
| v5独立holdout | 未実施 |
| 仮想FFB | 録画からデバイス非依存要求を再計算可能 |
| G923能力 | 未確認 |
| ROS 2 FFB指令 | 未実装 |
| 実機FFB | 未実装・未出力 |
| YOLO | PyTorch/Ultralytics未導入、今回の対象外 |

## 3. v5独立holdout `202609081440.tar.xz`

### 3.1 録画完全性

| 項目 | 結果 |
|---|---|
| 試行数 | 静止3、0.10 m/s接近3、0.10 m/s後退3、0.20 m/s接近3の計12 |
| 完全性 | 12/12 PASS |
| 映像・CSV・ODOM | 全試行で取得 |
| フレーム数整合 | 全試行PASS |
| SHA-256 | `e4c5f776fe5bcad5d99becf3cce380cccc2bf662e3bcf7e80ddf68414fba710d` |

ハンコンのペダル操作による速度変動と停止位置の約1～1.5 cmの差は録画不良とはしなかった。TTC解析には
実測ODOMを使用するため、公称速度と完全一致しなくても実際の速度・距離・警告状態を評価できる。

### 3.2 固定v5判定

| 条件 | 結果 | 診断 |
|---|---:|---|
| 静止 | 3/3 PASS | TTC・誤警告なし |
| 0.10 m/s接近 | 3/3 PASS | TTC応答正常 |
| 0.10 m/s後退 | 3/3 PASS | TTC・誤警告なし |
| 0.20 m/s接近 | FAIL | r01は警告成立、r02/r03は減速・観測除外が警告確認区間へ重なった |

固定済みv5の総合判定はFAILとし、結果を見た後に閾値を変更して合格扱いにはしなかった。v5設定一式の
「実機確認済み」への昇格は保留とした。

### 3.3 状態遷移不具合の修正

警告履歴のないUNKNOWN状態から、TTCが警告解除帯にあるPATHを受けた場合に、解除ヒステリシスだけで
WARNINGへ昇格する不具合を確認した。解除ヒステリシスは確定済みWARNINGを保持するための処理であり、
新しい警告を生成してはならない。

`CollisionRiskHysteresis`を修正し、警告履歴がある場合だけWARNINGコンテキストを継続するようにした。
これにより、v5のr02/r03で表示されていた根拠のないWARNINGは消え、観測不確実時はUNKNOWNとして扱われた。

## 4. TTC v6候補の設計と実装

v5の失敗を「実装が警告できなかった場合」「減速による正常解除」「警告刺激自体が成立しなかった場合」へ
分けるため、v6候補を別profileとして実装した。v5の固定結果は変更していない。

主な変更は次のとおりである。

- 録画全体ではなく実走行区間の検出・観測採用・追跡率を評価する。
- 実測TTCに3フレーム以上の警告機会が存在するときだけWARNINGを必須とする。
- 警告機会がない試行は、合格・実装失敗のどちらとも断定せずINCONCLUSIVEとする。
- 減速してTTCが安全側へ戻ったPATHを、警告脱落として数えない。
- 公称速度の相対許容を20%から25%へ変更し、ODOM量子化幅も明示する。
- 正規化面積下限を、過去34試行と遮蔽2イベントの回帰結果に基づき2000から1450へ変更する候補を作成する。

面積下限1450では、通常観測の最悪採用率98.46%、遮蔽外れ値拒否100%、遮蔽2イベントとも追跡失効・
再捕捉を維持した。実装後のRICHO-theta単体・回帰テストは152件すべてPASSした。

## 5. v6実機録画

### 5.1 `202609081616.tar.xz`

申告時は`202609081414.tar.xz`だったが、実際の対象ファイルは`202609081616.tar.xz`であった。アーカイブ内の
ラベルを確認し、v6 holdout r01～r03として解析した。

| 項目 | 結果 |
|---|---|
| 完全性 | 3/3 PASS |
| FPS | 29.995～30.010 fps |
| ODOM | 3/3で100% |
| 固定v6判定 | 0/3 PASS |

r01/r02は実測速度が不足し、r03以外は警告確認に必要な刺激を作れなかった。また3試行とも表示上の距離が
校正下限`raw_z=0.65 m`より近くなるまで接近したため、終盤の追跡率条件を満たさなかった。速度推定の
ODOMに対するMAEは全試行で0.000001 m/s未満であり、速度推定不良ではない。

r03ではWARNING 14フレーム、有限保持20フレーム、最大開始遅延0.068秒を記録し、警告状態機械の動作は
確認できた。この録画は削除せず、速度不足・校正範囲逸脱を含む失敗例として保存した。

### 5.2 `202609081640.tar.xz`

目標速度をおおむね0.17～0.20 m/sとし、約0.25 m/sまでの操作差を許容して再録した。`omake`は条件外の
参考データとし、正式判定には含めなかった。

| 試行 | ODOM速度p90 | 警告機会 | WARNING/HOLD | 固定判定 |
|---|---:|---|---:|---|
| r01 | 0.151393 m/s | あり | 28/6 | PASS |
| r02 | 0.185510 m/s | あり | 65/7 | FAIL |
| r03 | 0.151393 m/s | あり | 19/0 | PASS |

厳密な固定判定は2/3 PASSだった。r02は走行検出率92.16%が要件98%を下回ったことだけが失敗理由であり、
速度変動は許容範囲内だった。全3試行で確認可能な警告機会に対してWARNINGが成立し、警告後の危険なPATHと
CRITICALは0だった。したがって、TTC警告機能の主要動作は3/3で確認できた。

r02の未検出8フレームはWARNING成立後の至近距離で発生した。青箱下端と車体前方の白い部分が重なり、
地面接触点として使う輪郭が分断されたことが原因である。追跡器は予測で補完し、走行追跡率は100%を維持した。

## 6. G923の読み取り専用診断

| 項目 | 確認結果 |
|---|---|
| USB ID | `046d:c266` |
| 製品 | Logitech G923 Racing Wheel for PlayStation 4 and PC |
| 安定パス | `/dev/input/by-id/...-event-joystick` |
| 今回の実体 | `/dev/input/event22` |
| 権限 | `hsr`は`input`グループ所属、デバイス読み書き可能 |
| effect保持数 | 16 |
| 主な対応effect | `FF_PERIODIC`、`FF_SINE`、`FF_SQUARE`、`FF_CONSTANT`、`FF_SPRING`など |

既存`ffb_follow.py`にはevdevによるeffect操作があるが、起動時Autocenter/Spring、通信断時の強いセンタリング、
TTC用enable・dry-run・100 ms watchdogがない。そのままTTC実験へ流用せず、独立した安全なadapterを段階実装する
方針とした。

## 7. TTC連動FFB実施計画

`/home/robo25/FFB_feedback_control/FFB_feedback_control/implementation_plan.md`を作成した。初期対象は青箱の
TTC `WARNING/WARNING_HOLD`を、Kobuki停止状態でG923の弱い振動として提示するところまでとした。

設計上の主な安全条件は次のとおりである。

- 不正値、古い要求、通信断、例外では必ず停止側へ倒す。
- 物理出力は既定で無効とし、disabled、dry-run、hardwareを分離する。
- 100～120 msの有限時間effectと100 ms watchdogを併用する。
- 強度は設定上限とコード上の絶対上限0.25で二重制限する。
- G923へ書き込むプロセスは1つに限定する。
- FFB adapterからKobuki速度topicへpublishしない。
- 物理出力はソフトウェア安全ゲート完了後に改めて承認を得る。

## 8. FFB Phase 1実装

承認後、`FFB_feedback_control`リポジトリでPhase 1を実装した。

### 8.1 ROS 2 interface

`oit_interfaces/msg/CollisionFfbCommand.msg`を追加し、次を1つの意味付き指令として扱えるようにした。

- 生成時刻、sequence、source
- `CLEAR/PATH/WARNING/WARNING_HOLD/CRITICAL/UNKNOWN`
- `OFF/STEADY/STEADY_HOLD/PULSE`
- active、正規化要求強度、理由

### 8.2 デバイス非依存の安全ポリシー

`CollisionFfbSafetyPolicy`をROS・evdev非依存で実装した。

- source、uint64 sequence、時刻鮮度、単調sequenceを検査する。
- state、active、patternの不整合を拒否する。
- NaN/Inf、範囲外、未知enumをfail closedでSTOPへ変換する。
- active要求は受信値、設定上限、絶対上限0.25の最小値へclampする。
- `CLEAR/PATH`への遷移時はSTOPを返す。
- 最終有効要求から100 ms経過した場合、1回だけwatchdog STOPを返す。

### 8.3 検証

| 検証 | 結果 |
|---|---|
| 安全ポリシー単体テスト | 32/32 PASS |
| 新規ファイルのflake8 | PASS |
| 新規ファイルのpydocstyle | PASS |
| `oit` package build | PASS |
| `oit_interfaces`生成・build | PASS |
| 生成メッセージのPython import・定数確認 | PASS |
| G923へのopen/upload/write | 0回 |

リポジトリ全体のlintには既存ファイル由来の警告が残るが、Phase 1で追加したPythonファイルには警告がない。

## 9. 本日のGit履歴

### RICHO-theta

- `b0a3011`: 0908実験v1
- `9135bb5`: TTC v6候補の評価条件と観測ゲートを追加
- `5b976c4`: 9月8日TTC v6追加録画を解析
- `47c7277`: 9月8日TTC v6再録を解析

### FFB_feedback_control

- `34a1516`: TTC連動FFBの安全ポリシーを追加

録画本体は大容量のためGit管理せず、解析CSV、診断書、設定、SHA-256を保存した。

## 10. 現在地と未完了事項

1. v6の主要な警告動作は3/3で確認できたが、厳密な固定要件では走行検出率により2/3 PASSである。
2. 至近距離で青箱下端と車体が重なると、生検出が断続的に欠落する。
3. FFB Phase 1は完了したが、ROS subscriber、disabled/dry-run node、status topicは未実装である。
4. G923用evdev backend、有限時間effect、排他lock、終了時停止は未実装である。
5. `RICHO-theta`から`/collision/ffb_command`をpublishする処理は未実装である。
6. G923への物理出力は未実施であり、現時点で実行してはならない。
7. YOLOによる一般物体認識と移動物体自身の速度推定は未着手である。

## 11. 2026年9月9日の作業

明日の作業計画には、既存の
`/home/robo25/FFB_feedback_control/FFB_feedback_control/implementation_plan.md`を使用する。Phase 2の作業順、
安全条件、完了条件がすでに定義されているため、重複する日別計画書は作成しない。

明日はPhase 2「dry-run ROS adapter」を実施する。

1. 作業開始時に両リポジトリのbranch、最新commit、clean状態を確認する。
2. `collision_ffb_node`を追加し、既定`disabled`と`dry_run`だけを実装する。
3. `disabled`と`dry_run`では`InputDevice`、`upload_effect`、`write`を一度も呼ばないことをテストする。
4. 合成指令`CLEAR→WARNING→WARNING_HOLD→CLEAR`を流し、状態遷移と強度0.05へのclampを確認する。
5. publisherを停止し、100 ms後にwatchdog STOPが1回だけ発生することを確認する。
6. status topicとログへ、sequence、受信強度、clamp後強度、pattern、停止理由、faultを記録する。
7. 例外、Ctrl+C相当、topic停止後の最終状態がinactiveになることをテストする。
8. 単体テスト、interface import、ROS 2 package buildを実行し、結果を計画書へ追記する。

明日の完了条件は、合成ROS messageを用いたdisabled/dry-run試験がすべてPASSし、G923を開かずに
`CLEAR/WARNING/HOLD/CLEAR/watchdog`の状態列を再現できることである。Phase 3のRICHO-theta publisherと、
Phase 4の物理FFB出力には自動的に進まない。Phase 2完了時点で一度結果を報告し、次工程を判断する。
