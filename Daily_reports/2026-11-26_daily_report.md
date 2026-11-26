# 2026-11-26 日報：Aの勾配反転、continuous cadence、autocenter 15、0.15の方向力不足

## 1. 到達点

1. **A r01を取得**。箱左で`direction=+1`（Aの勾配反転）。0.4の定常36 frameは方向として感じず、0.25/direction 0の振動を1回感じた。Aは箱の側と逆を向く既知の幾何反転を、実機ログで確認。
2. **ベンチ0.075/0.10/0.15の「ドッドッド」をcadenceと特定**。patternは`steady`、riskは連続なのに、activeが3〜4 frame ON/OFFし、`cadence_gap:triple`が出ていた。定常力がtriple cadenceでパルスになっていた。
3. **Bをcontinuous cadenceで再試験**。0.1/0.15の初期runは箱が真横/青い経路外でrisk/hold/UNKNOWNが切れ、「ドドド」。箱を青い経路に入れ、CRITICALで停止する必要を確認。
4. **B continuous 0.15（19:13）は最初のCRITICALが成功**。箱が経路内（1.21 m、direction -1、pattern steady）。最後は箱が真横/経路外でUNKNOWN pulse 0.15。CRITICALで停止が正解。
5. **autocenter 15でベースラインを軽量化**。`ffset`でG923のautocenterを15に設定。ベースラインは軽くなった。しかし20:27のB continuous 0.15は、箱左・direction -1・active 72・corridor 63/72でも、0.15の方向定常を左で感じなかった。右が軽いのは逆側なので正しい。
6. **次の段階を0.20→0.25→0.30に決定**。0.15で感じないため、0.5へ飛ばさず、短いパルス・車輪浮かせ・e-stop・安全確認者で段階試験。0.5は最後の手段。フィールド0.05は不変。

## 2. 作業条件・Git状態

- 作業日は2026-11-26。学校でカメラ・Kobuki・G923を使用。
- カメラ/Kobuki PC：`matunuc-NUC13ANHi5:~/theta_ws`、`bird_eye`＋relay、A/B config、`collision_ffb_cadence=continuous`。
- GPU/ハンコンPC：`hsr-Alienware-m16-R2:~/yopi_ws`、`collision_ffb_node` hardware、`max_magnitude=0.15`、`autocenter=15`（`ffset`）。
- 駆動：`kobuki_launch_no_ffb_follow.py`（`ffb_follow`を外したローカルlaunch）。`handle`/`twist_mux`/`cmd_vel_mirror`。
- 前日までのcommit `842fe92`。本日分は日報・代表資料・HANDOFFをcommit/pushする。archiveは`~/Downloads`、Git管理外。

## 3. 実施内容

### 3.1 A（勾配方向）r01

- A config（`gradient_direction`）で15:37に実施。箱は左0.15〜0.5 m、速度0.35〜0.5 m/s。
- ログ：risk WARNING 89、CRITICAL 70、HOLD 6、PATH 9。FFB active 48、pattern steady 48。`direction=+1`が36、`direction=0`が12。requested 0.4が36、0.25が12。
- `direction=+1`＋0.4は定常36 frame。`direction=0`＋0.25は12 frame。
- 体感：振動を1回。0.4の定常は方向として感じず。Aは箱左で+1（箱の側と逆）で、既知の勾配反転。

### 3.2 ベンチ0.075/0.10/0.15（triple cadence）

- 17:32/17:36/17:40にBベンチ（実際は`direction=+1`、箱左、`gradient_reason=ok`のためA config相当）。
- r01 0.075：active 41、pattern steady 41、direction +1 30、requested 0.4 39。
- r02 0.10：active 33、steady 33、+1 27、0.4 29。
- r03 0.15：active 47、steady 47、+1 24、0.4 38。
- activeが3〜4 frame ON/OFF。`collision_ffb_reason`は`ttc_critical:cadence_triple`→`cadence_gap:triple`→`cadence_complete`。
- 体感：0.10/0.15で「ドッドッド」。**riskの切替ではなく、triple cadenceによる定常力のパルス**。

### 3.3 B continuous cadence

- B configの`collision_ffb_cadence`を`continuous`へ変更（ベンチB configのみ）。
- 18:34/18:40の0.1/0.15：
  - r01 0.1：risk WARNING 12、CRITICAL 80、HOLD 77、UNKNOWN 26。active 176、pattern steady 92/hold 77/pulse 7、direction -1 122。箱x -0.534、z min 0.201。
  - r02 0.15：CRITICAL 82、HOLD 72、UNKNOWN 65、WARNING 26。active 191、steady 108/hold 72/pulse 11、direction -1 129。箱x -0.479、z min 0.201。
- 体感：箱が真横になると「ドドド」。箱が青い経路から外れ、`not_approaching`/`warning_hold_expired`、UNKNOWN pulseが原因。

### 3.4 B continuous 0.15（経路・19:13）

- 443 rows、active 36、pattern steady 19/hold 14/pulse 3、direction -1 23、requested 0.4 18/0.25 15/0.15 3。
- 最初のactive：1.21 m、x -0.42、0.52 m/s、CRITICAL、direction -1、steady、corridor 1。
- 最後：0.37 m、x -0.67、0.03 m/s、UNKNOWN pulse 0.15、corridor 0、`warning_hold_expired`。
- 画面：`COLLISION CANDIDATE: CRITICAL clearance=-0.11 m`、`BLUE[CAL] x=-0.38 z=0.96`。箱が青い経路/衝突候補内。
- 体感：最初のCRITICALは正しいテスト。最後のUNKNOWN pulseは真横/経路外の「ドドド」。**CRITICALで停止**。

### 3.5 autocenter 15（20:27）

- `collision_ffb_node`に`autocenter`パラメータを追加し、`ffset <device> -a 15`を起動時に実行。`Autocenter set to 15%`を確認。
- `ffb_follow`の設定：`idle_autocenter=15`、`manual_autocenter=60`、`failsafe_lock_autocenter=95`、`idle_spring_coeff=13500`。collision側はautocenter/springを設定していなかったため、`ffb_follow`を外すとG923のデフォルト（重い）が残っていた。
- 20:27のB continuous 0.15：979 rows、active 72、pattern steady 46/hold 26、direction -1 61、requested 0.4 38/0.25 34、corridor 63/72。箱x -0.421、最初のCRITICAL 1.10 m/0.47 m/s。
- 体感：ベースラインは軽くなった。箱左で左へ切っても0.15の方向定常は感じず。右へ切ると軽い（逆側なので正しい）。
- **0.15の定常方向力はまだ知覚閾値以下**。autocenterだけでは足りない。

### 3.6 駆動・interface・単一writer

- `ffb_follow`は通常のフォローFFBで、`collision_ffb_node`と**同じG923 writerロック**を奪い合う。`kobuki_launch.py`は`ffb_follow`を無条件で起動するため、collision起動中は`ffb_follow`が落ちる。`kobuki_launch_no_ffb_follow.py`で駆動系（`handle`/`twist_mux`/`cmd_vel_mirror`）だけ起動。
- `oit_interfaces`は`int8 direction`付きへ再ビルド。ハンコンPCの旧版を解消。`bench_mode`/`bench_max_magnitude`、`autocenter`のパッチを適用。
- `direction_enabled=true`、`constant_direction_sign=1.0`。箱左→Bは-1、Aは+1（勾配反転）。

## 4. 定量結果

### 4.1 A r01

| 項目 | 値 |
|---|---:|
| rows | 2,626 |
| risk WARNING / CRITICAL / HOLD / PATH | 89 / 70 / 6 / 9 |
| risk active | 159 |
| FFB active | 48 |
| pattern steady | 48 |
| direction 0 / +1 | 2,590 / 36 |
| requested 0.4 / 0.25 | 36 / 12 |
| box x median / z median | −0.279 / 1.369 m |
| corridor | 159 |
| 最初のactive | 14.71 s、1.05 m、x −0.25、0.35 m/s、WARNING、+1、gradient −0.25 |

- 体感：振動1回（direction 0 / 0.25）。direction +1 / 0.4の定常は感じず。箱左でA +1（勾配反転）。

### 4.2 ベンチ0.075/0.10/0.15（triple）

| run | 値 | rows | active | pattern | direction +1 | requested 0.4 | box x | 体感 |
|---|---:|---:|---:|---|---:|---:|---:|---|
| r01 | 0.075 | 1,820 | 41 | steady 41 | 30 | 39 | −0.482 | 弱い |
| r02 | 0.10 | 1,958 | 33 | steady 33 | 27 | 29 | −0.481 | ドッドッド |
| r03 | 0.15 | 1,928 | 47 | steady 47 | 24 | 38 | −0.495 | ドッドッド |

- activeは3〜4 frame ON/OFF。`cadence_gap:triple`。riskは連続。**cadenceのパルス**。

### 4.3 B continuous

| run | 値 | rows | active | pattern | direction -1 | corridor | box x | z min | 体感 |
|---|---:|---:|---:|---|---:|---|---:|---:|---|
| r01 | 0.1 | 2,665 | 176 | steady 92/hold 77/pulse 7 | 122 | 125 | −0.534 | 0.201 | 真横でドドド |
| r02 | 0.15 | 2,001 | 191 | steady 108/hold 72/pulse 11 | 129 | 少 | −0.479 | 0.201 | 真横でドドド |
| path | 0.15 | 443 | 36 | steady 19/hold 14/pulse 3 | 23 | 23/36 | −0.417 | 0.365 | 最初のCRITICALは成功、最後のUNKNOWNは真横 |
| autocenter | 0.15 | 979 | 72 | steady 46/hold 26 | 61 | 63/72 | −0.421 | 0.562 | 0.15の方向は感じず、右は軽い |

- B pathの最初：1.21 m、x −0.42、0.52 m/s、CRITICAL、direction −1、steady、corridor 1。最後：0.37 m、x −0.67、UNKNOWN pulse 0.15。
- 20:27の最初：1.10 m、x −0.42、0.47 m/s、CRITICAL、direction −1、steady、corridor 1。最後：0.75 m、hold。

### 4.4 autocenter / force path

| 項目 | 値 |
|---|---|
| autocenter | 15（`ffset`） |
| `ffb_follow` idle / manual / failsafe | 15 / 60 / 95 |
| `ffb_follow` idle spring coeff | 13,500 |
| collisionのautocenter/spring | なし（今回autocenterのみ追加） |
| 0.15の方向定常 | 左で感じず、右は逆側で軽い |
| force path | 11/24 liveでapplied 0.05/direction ±1/pattern steadyを確認。0.15の適用は`ffb_status`で要確認 |

- ベースラインは軽くなった。0.15の方向定常はまだ足りない。`FF_GAIN`、spring 13,500、autocenterの組み合わせを確認する価値。

### 4.5 検証

- `oit_interfaces`の`int8 direction`、`bench_mode`/`bench_max_magnitude`、`autocenter`のビルド・`py_compile`。
- `ffset`の`Autocenter set to 15%`。
- 駆動：`kobuki_launch_no_ffb_follow.py`で`handle`/`twist_mux`/`cmd_vel_mirror`、`/cmd_vel` 1系統。
- 11/24のunit testsは旧frame-packet版ガード6件でFAIL、`--skip-tests`。11/26はadapterパッチ中心で、全unit testsは未再実行。

## 5. 判断

1. **Aは箱左で+1（勾配反転）**。Bは箱左で-1（側）。A/Bの方向方針の差がログで確認できた。Aの0.4定常は方向として感じず。
2. **ベンチの「ドッドッド」はtriple cadence**。pattern steady、risk連続、active 3〜4 frame ON/OFF、`cadence_gap:triple`。riskの切替ではない。
3. **Bの「ドドド」は箱が青い経路外/真横**。risk/hold/UNKNOWNが切れる。箱を青い経路に入れ、CRITICALで停止する。
4. **autocenter 15でベースラインは軽量化**。しかし0.15の方向定常はまだ知覚閾値以下。
5. **次は0.20→0.25→0.30**。短いパルス、車輪浮かせ、e-stop、安全確認者。0.30で感じれば0.5は不要。0.5は最後の手段（明示承認、50〜120 ms）。
6. **フィールドの0.05は不変**。0.20/0.30/0.5はベンチ専用。
7. **0.15で感じない原因**は、単純なマグニチュードだけではなく、`FF_GAIN`、spring 13,500、autocenterの組み合わせの可能性。0.30/0.5の前に確認。

## 6. 未実施・課題

- **0.20/0.25/0.30のベンチ**：次回。0.5は最後。
- **`FF_GAIN`/spring**：`ffset`のgain、`ffb_follow` idle spring 13,500のcollision側への追加を検討。
- **0.15のapplied確認**：20:27の`ffb_status`を`applied_magnitude=0.15`、`pattern=steady`、`direction=-1`、`output_active=true`で確認する。
- **A/Bの評定**：Aの振動1回/方向なし、Bの0.1/0.15のドドド、0.15の方向なし。評定シートへ。
- **青い経路**：箱を経路内に入れ、真横の前に停止。0.1/0.15で同じ条件。
- **unit tests**：11/26のadapterパッチ後の全テストは未実行。旧frame-packet版ガードは別途。
- **`ffb_follow`の通常走行**：ベンチでは外す。通常は`kobuki_launch.py`。単一writer。

## 7. 次回（2026-11-27）

1. `BENCH_HARDWARE_MAX_MAGNITUDE`を0.20にした状態で、B 0.20を1回。
2. 箱左0.15〜0.2 m、前方1.2〜1.3 m、0.35〜0.4 m/s。青い経路に箱を入れ、CRITICALで停止。
3. 0.20で感じなければ0.25、0.30。短いパルス、車輪浮かせ、e-stop、安全確認者。
4. 0.30でも感じなければ、`ffset`のgain、spring 13,500、autocenterの組み合わせを確認。0.5は最後。
5. 箱左で左が重い、箱右で右が重い。逆なら`constant_direction_sign=-1.0`。
6. 評定を`record_2026-11-26.csv`へ。A/Bのログ比較をまとめる。

## 8. 測定と推測の区別

**測定**

- A r01のrisk/FFB active/pattern/direction/requested/box/corridor。
- ベンチ0.075/0.10/0.15のactive/pattern/direction/requested/cadence reason。
- B continuous 0.1/0.15/19:13/20:27のactive/pattern/direction/requested/corridor/box/z。
- 最初のCRITICAL/最後のUNKNOWN、autocenter 15の`ffset`ログ、ベースラインの軽量化。
- 体感：Aの振動1回/方向なし、ベンチ0.10/0.15のドッドッド、Bの真横ドドド、0.15の方向なし、右が軽い。

**推測・未確認**

- Aのdirection 0/0.25の振動はadapter側direction 0パターンと推定。Aのpublisher patternはsteady。
- ベンチのdirection +1/箱左/`gradient_reason ok`はA config相当と推定。Bの側なら-1。
- 0.15が知覚閾値以下という判断は、左の体感とautocenter 15からの判断。個人差・グリップ・摩耗は未評価。
- `FF_GAIN`/spring 13,500が効くかは未検証。0.20/0.25/0.30/0.5も未検証。
- 20:27の`ffb_status`のapplied 0.15は未確認。11/24 liveの0.05を基準にしている。
- 11/26のadapterパッチ後の全unit testsは未実行。

## 9. 成果物

- [2026-11-26 実験索引](../Experimental_results/2026-11-26/README.md)
- [代表資料](../Experimental_results/2026-11-26/report_assets/README.md)
  - [A r01](../Experimental_results/2026-11-26/report_assets/A_r01_summary.json)
  - [ベンチ0.15](../Experimental_results/2026-11-26/report_assets/bench_r03_summary.json)
  - [B continuous path](../Experimental_results/2026-11-26/report_assets/B_continuous_path_r01_summary.json)
  - [B continuous autocenter](../Experimental_results/2026-11-26/report_assets/B_continuous_autocenter_r01_summary.json)
- [11/26 評定CSV](../Experimental_results/2026-11-26/record_2026-11-26.csv)
- [11/24 手順・RUNBOOK](../Experimental_results/2026-11-24/ffb_policy_comparison_r01/RUNBOOK.md)
- 元archive（Git管理外）：`~/Downloads/ffb_A_r01_20261126_153717_062.tar.xz`、`bench_r01/r02/r03_20261126_*`、`ffb_B_continuous_*`、`ffb_B_continuous_0.15_test_20261126_{191349,202728}.tar.xz`
