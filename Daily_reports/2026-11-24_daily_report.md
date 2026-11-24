# 2026-11-24 日報：G923実機でM/Bを実施、force path確立、0.05の方向トルクは知覚閾値以下

## 1. 到達点

1. **G923のFFB経路が端から端まで通った。** `bird_eye` → relay → `/collision/ffb_command` → ハンコンPCの`collision_ffb_node` → `applied_magnitude=0.05`。`ffb_status`で`output_active=true`、`direction=±1`、`pattern=1`を確認。
2. **ハンコンPCの`oit_interfaces`が旧版で、新しい`direction`付きコマンドを受信できていなかった**と特定。`~/yopi_ws`を新インターフェースで再ビルドし、adapterを再起動して解決。
3. **M（大きさのみ）を3run取得。** r010/r011/r012はいずれもWARNING/CRITICALが十分に出て、requested 0.25/0.4、direction 0。0.05の**振動**は体感3。
4. **B（側ベース）を3run取得。** r02/r03は箱左で`direction=-1`、requested 0.4。しかし**方向の重さは感じなかった**。r01は箱中央で`direction=0`のためBとして無効。
5. **決定的な切り分け**：同じ0.05でも「振動パターン（pattern 3）」は感じ、「方向パターン（pattern 1）」は感じない。**0.05の定常方向トルクが知覚閾値以下**で、force pathの故障ではない。
6. **駆動系の落とし穴**：`handle`単体では車体が動かない。`ros2 launch oit kobuki_launch.py`でmux/watchdogまで起動して初めてG923で走行できた。

## 2. 作業条件・Git状態

- 作業日は2026-11-24。学校でカメラ・Kobuki・G923を使用。
- カメラPC：`matunuc@matunuc-NUC13ANHi5:~/theta_ws`、`bird_eye`＋relay。
- ハンコンPC：`hsr@hsr-Alienware-m16-R2:~/yopi_ws`、`collision_ffb_node` hardware、`max_magnitude=0.05`（Phase 4上限）。
- 駆動：`ros2 launch oit kobuki_launch.py`。G923のペダル/ステアリング。
- 作業ツリーには実験設定・RUNBOOKの変更があり、runner preflightは`--allow-dirty-git`、`--skip-tests`で通した。
- 本日分は日報・代表資料・HANDOFFをcommit/pushする。archive（各345 MB程度）は`~/Downloads`にあり、Git管理外。

## 3. 実施内容

### 3.1 駆動系（`handle`単体では動かない）

- `handle_node`単体では`/cmd_vel_joy`にpublisherがあるが、`/cmd_vel`にpublisherがなく、`kobuki`が購読していなかった。
- `twist_mux_node`は`/commands/velocity`をpublishしていたが購読者0、`failsafe_watchdog_node`の`/cmd_vel_safety`も購読者0。mux/watchdogが駆動チェーンに入っていなかった。
- `/cmd_vel`へ直接pubすると車体は動いた（base・モータ・電源は正常）。
- 応急の`/cmd_vel_joy`→`/cmd_vel` relayでテストした後、**`ros2 launch oit kobuki_launch.py`**で本来のチェーンに戻した。`/cmd_vel`は1系統。
- 教訓：`handle`だけでは足りない。launchでmux/watchdogまで起動する。relayとlaunchを併用しない（`/cmd_vel`の二重publisher）。

### 3.2 FFB adapterとinterfaceの版差

- ハンコンPCの`~/yopi_ws/install/oit_interfaces`は旧版で、`CollisionFfbStatus`に`int8 direction`が無かった。
- カメラPCの`~/ffb/install/oit_interfaces`は新版で`direction`あり。relayはdirection付きコマンドを送っていたが、旧adapterは型が合わず受信できていなかった。
- `~/yopi_ws`の`oit_interfaces`/`oit`を新ソースでクリーンビルド（`colcon build --base-paths src --packages-select oit_interfaces oit`）。`ros2 interface show`で`int8 direction`を確認。
- adapterの`direction_enabled`は**既定False**。MはFalse、B/AはTrueで再起動。`constant_direction_sign=1.0`。符号は箱の側に従った（B r03は左で-1、live確認は右で+1）。

### 3.3 M（大きさのみ）

- r010/r011/r012。箱は前方1.2〜1.3 m、中央、操舵なし、0.35〜0.49 m/s。
- 振動は全runで体感3。`pattern=3`（振動）と推定。Mは方向0。
- r07（adapter再ビルド前）はWARNING 193 frameあったが、旧adapterでFFBが届かず、評定に使わない。

### 3.4 B（側ベース）

- r01：箱中央（x≈0.01〜0.03）で`direction=0`。Bとして無効。振動はMに近い。
- r02：箱左（x≈-0.10）、`direction=-1`が14 frame。requested 0.25/0.4。方向は感じず。
- r03：箱左（x≈-0.20）、`direction=-1`が29 frame、requested 0.4が29 frame、active 97。方向は感じず。代表run。

### 3.5 live chainの確認

B接近中に2PCで`ros2 topic echo`：

- `ffb_command`: `active:true`、`normalized_magnitude:0.4`、`direction:1`、`reason:ttc_critical:cadence_triple`
- `ffb_status`: `output_active:true`、`requested_magnitude:0.4`、`applied_magnitude:0.05`、`pattern:1`、`direction:1`、`fault:false`

UNKNOWN時は`requested 0.15`、`applied 0.05`、`pattern 3`、`direction 0`。

## 4. 定量結果

### 4.1 Mの3run

| run | active | WARNING | CRITICAL | HOLD | req 0.4 | 最初の警告 | 速度max | direction |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| r010 | 116 | 57 | 59 | 13 | 26 | 1.267 m / 0.414 m/s | 0.452 | 0 |
| r011 | 121 | 58 | 63 | 26 | 29 | 1.287 m / 0.444 m/s | 0.456 | 0 |
| r012 | 109 | 49 | 60 | 13 | 27 | 1.271 m / 0.486 m/s | 0.493 | 0 |

- 振動の体感：全run 3。
- r012の箱は中央（x median 0.035）、距離 median 1.289 m。
- 方向は全行0（M configでdirection無効）。

### 4.2 Bの3run

| run | 箱 | active | direction -1 | req 0.4 | 方向の体感 |
|---|---|---:|---:|---:|---|
| r01 | 中央 | 16 | 0 | 7 | 振動のみ（B無効） |
| r02 | 左 | 31 | 14 | 9 | 感じず |
| r03 | 左 | 97 | 29 | 29 | 感じず |

- r03はCRITICAL 55、WARNING 42、HOLD 34。最初のactiveは1.077 m、x=-0.203、0.467 m/s、TTC 1.64。
- r03の代表要約：[B_r03_summary.json](../Experimental_results/2026-11-24/report_assets/B_r03_summary.json)

### 4.3 force path

| 項目 | 値 |
|---|---|
| command | active true、0.4、direction 1、ttc_critical |
| status | output_active true、requested 0.4、applied 0.05、pattern 1、direction 1 |
| UNKNOWN | applied 0.05、pattern 3、direction 0 |
| fault | false |

- 0.05はPhase 4の安全上限。`max_magnitude>0.05`はadapterが起動時に拒否する。

### 4.4 preflight

| 項目 | 結果 |
|---|---|
| Python依存 | PASS（`numpy, cv2, PySide6, rclpy, oit_interfaces.msg`） |
| Experiment config | PASS（v12 base、relay、challenge） |
| 記録容量 | PASS（369.3 GiB free） |
| カメラ | PASS（1280×720、30 fps） |
| ROS odom | PASS（0.000 m/s） |
| Unit tests | **FAIL（errors=6、旧frame-packet実験の版ガード）** |
| Git provenance | WARN（dirty、`--allow-dirty-git`） |

- 6件は`previous verified runner changed` 4件と`test_lossless_packet_gpu_submission` 2件。今回のFFB/青箱とは無関係。
- 関連97テスト（FFB publisher/relay/motion/intent/bird_eye）は解析側の同一コードでOK。実験PCでは`--skip-tests`でpreflightを通した。

## 5. 判断

1. **force pathは正常**。intent→relay→command→adapter→0.05適用まで確認。directionも適用されている。
2. **0.05の方向トルクは知覚閾値以下**。r03で3秒続いても方向を感じない。同じ0.05の振動（pattern 3）は感じる。持続時間やforce pathの問題ではない。
3. **Mの振動は「重さ」ではない**。Mのpattern 3はアラート（振動）で、目標の抵抗型FFB（定常トルク）のベースラインではない。M/A/Bを「重さ」で比較するには、MもA/Bも同じ定常トルクにする必要がある。
4. **0.05上限では方向性のある重さの体感比較は成立しない**。上限は上げない。Phase 4の安全機構。
5. **B r01は無効**（箱中央でdirection 0）。B r02/r03はログとして有効だが、方向の体感はない。
6. **Aは未実施**。明日、Bと同じ条件で1回確認する。方向が感じられなければ、今日の結論が確定する。

## 6. 未実施・課題

- **A（勾配方向）**：未実施。明日の再開点。
- **コーンintent dry-run**：今日はG923のM/Bに集中し、未実施。別セグメントで後日。
- **方向性のある重さの実現**：0.05の定常トルクでは不足。新しい安全段階でマグニチュードを上げるか、振動に左右バイアスを付けるか（後者は「重さ」ではない）。承認が必要。
- **M/A/Bの条件統一**：Mは振動、A/Bは定常トルクで、知覚の種類が違う。Mも定常トルクにする設計が必要。
- **1.5 m/0.5 m/sの前提**：実際は箱1.2〜1.3 m、0.35〜0.49 m/s。1.5 mは0.5 m/s用。今日のログは実速度に合わせた。
- **unit testsの版ガード6件**：旧frame-packet実験の意図的検出。`--skip-tests`は今回限りの例外。恒久対応は別途。
- **adapter/interfaceの版同期**：`~/yopi_ws`と`~/ffb`の`oit_interfaces`/`oit`を同じ版に保つ。`direction_enabled`の既定False、M/A/Bで再起動が必要。
- **`constant_direction_sign`**：B r03は左で-1、liveは右で+1。符号は箱の側に従った。A/Bで同じ側を使い、符号を記録する。

## 7. 次回（2026-11-25）

1. **Aを1回**：Bと同じ箱位置（左0.15〜0.2 m）、1.2〜1.3 m、0.35〜0.4 m/s。`ffb_status`の`pattern=1`、`applied=0.05`、`direction`を確認。
2. Aで方向が感じられなければ、**M/A/Bの重さ比較は0.05では不成立**と確定。記録をまとめる。
3. **新しい安全段階/パターン設計**を相談：定常トルクの上限引き上げ（承認・安全審査）か、振動の左右バイアス（目標とは別物）か、ログのみの方向比較か。
4. **Mの評定**：振動3（M1/M2/M3）。Mは「重さ」ではなくアラートとして記録。
5. **Bの評定**：方向は感じない（1/1、方向逆0、中止0）。r03を代表。
6. **record**：`record_2026-11-24.csv`を更新し、Aの行を埋める。`analyse.py`でM/B/Aの集計。
7. **コーンdry-run**：別セグメントで実施する場合は、M/A/Bとは混ぜない。

## 8. 測定と推測の区別

**測定**

- M r010/r011/r012のrisk/requested/direction、速度、距離、active frame。
- B r01/r02/r03のrisk/requested/direction、箱の左右、active frame。
- live `ffb_command`/`ffb_status`のactive値、applied 0.05、pattern 1/3、direction ±1。
- Mの振動体感3、Bの方向不感知。
- 駆動系の`/cmd_vel`未接続→`kobuki_launch.py`で走行。
- adapter/interfaceの旧版→再ビルド→`direction`表示。
- preflightのPASS/FAIL、unit tests 6件の内容。

**推測・未確認**

- Mの`pattern=3`はlive UNKNOWNと体感からの推定。Mのstatusを全frame記録したわけではない。
- 0.05の方向トルクが知覚閾値以下という判断は、r03の3秒とlive applied 0.05からの判断。個人差・グリップ・摩耗は未評価。
- Aの方向も感じられないという予想は未確認。
- 新しい安全段階で重さが感じられるかは未検証。
- 6件のunit test失敗が「今回の実験と無関係」という判断は、テスト名と既知の版ガードによる。全テストの再設計は未実施。

## 9. 成果物

- [2026-11-24 実験索引](../Experimental_results/2026-11-24/README.md)
- [実行手順・RUNBOOK](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/RUNBOOK.md)
- [M/Bの評定CSV](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/record_2026-11-24.csv)
- [代表資料](../Experimental_results/2026-11-24/report_assets/README.md)
  - [M r012要約](../Experimental_results/2026-11-24/report_assets/M_r012_summary.json)
  - [B r03要約](../Experimental_results/2026-11-24/report_assets/B_r03_summary.json)
  - [force path確認](../Experimental_results/2026-11-24/report_assets/ffb_chain_active_check.txt)
- 元archive（Git管理外）：
  - `~/Downloads/ffb_M_r010_20261124_193317_461.tar.xz`
  - `~/Downloads/ffb_M_r011_20261124_193646_648.tar.xz`
  - `~/Downloads/ffb_M_r012_20261124_193913_440.tar.xz`
  - `~/Downloads/ffb_B_r01_20261124_200820_761.tar.xz`
  - `~/Downloads/ffb_B_r02_20261124_200954_130.tar.xz`
  - `~/Downloads/ffb_B_r03_20261124_201259_417.tar.xz`
