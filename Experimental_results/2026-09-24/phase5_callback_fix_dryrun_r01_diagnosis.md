# Phase 5 callback修正後 dry-run r01診断（2026-09-24）

## 判定

**試験全体はFAIL（手順不備）。カメラ・青箱検知・ODOM専用executorはPASS、challenge専用executorは未試験。**

ハンコン接続PCのadapter起動コマンドに`-p freshness_mode:=challenge`がなく、既定の`clock`モードで起動した。このため`/collision/ffb_challenge` publisherが作られず、両PCのbagでchallengeは0件、カメラCSVでもchallenge受信累計は0のままだった。`bird_eye.py`は919/919フレームで`no_recent_receiver_challenge`として指令を送らず、安全側に停止した。これはfail-closedの期待動作であり、今回のデータからchallenge callback修正の成否は判定できない。

この手順不備は、解析前に提示したadapterコマンドから`freshness_mode:=challenge`が抜けていたことによる。

## 入力

| 入力 | SHA-256 |
|---|---|
| `phase5_callback_fix_dryrun_r01_20260924_170947_310.tar.xz` | `34bd6185abdb03dc569ee75d9596f8d8da9b31b964064bc16b34d09558de5922` |
| `phase5_callback_fix_kobuki_r01.tar.xz` | `ab95f13843e5d1fd618edaefe84dbec1568a0754be4f663936231ff5d7f78cc5` |
| `phase5_callback_fix_hsr_r01.tar.xz` | `3332136d9e3f81b6cf3ee211781bfda51675eb5c224241d3bee42beff4621d61` |

## カメラ・検知

| 指標 | 結果 |
|---|---:|
| frame / raw・BEV・detection | 919 / 919・919・919 |
| 実効FPS | 30.011 |
| 有効処理時間p95 | 28.89 ms |
| 青箱検出・観測採用・追跡 | 各919/919（100%） |
| ODOM available | 573/919（62.35%） |
| 0.25 m/s観測 | 103フレーム、録画開始10.732～14.122秒 |
| 最小TTC | 4.60271秒 |
| WARNING / FFB active | 0 / 0 |

単体起動時に青箱を検知したという事前確認どおり、本録画も全フレームで青箱検知・採用・追跡が成立した。前回録画だけに見られた画面全体の青偏りは再発しておらず、HSVしきい値を変更しない判断は妥当だった。

最小TTCはWARNING進入しきい値4.6秒より0.00271秒だけ大きく、リスクは`PATH`104フレーム、`CLEAR`815フレームだった。したがって、challengeを正しく起動していた場合でも今回の配置・0.25 m/sではactive警告は生成されない条件だった。

## ODOM callback修正

録画CSVの`odom_received_count`は4434から4979へ単調増加し、減少0回、録画中の増分545件だった。0.25 m/s送信時はKobuki bagで90件、ハンコン側bagで89件を記録し、カメラCSVでは該当速度を103フレーム連続で利用した。

受信累計が止まった区間は録画開始5.857～10.698秒と13.688～21.253秒で、bag上でも0 m/s publisher停止後から0.25 m/s開始前、および0.25 m/s終了後から0 m/s再開前の手動切替区間に一致した。publisher動作中は約30 Hzで増加しており、前回疑ったアプリ内callback停滞はODOMでは再発していない。

## challenge・FFB

| 指標 | Kobuki PC bag | ハンコン接続PC bag |
|---|---:|---:|
| challenge | 0 | 0 |
| command | 0 | 0 |
| status | 1 | 1 |
| mock ODOM | 2962 | 7771 |
| 0.25 m/s ODOM | 90 | 89 |
| fault | 0 | 0 |
| 最終status | `dry_run`・`shutdown`・inactive | 同左 |

adapterの`dry_run`起動と安全なshutdownは確認できた。しかしchallengeが発行されていないため、カメラ側は全919フレームで送信を見送った。commandが0件なのはネットワーク欠落ではなく、challenge不在に対する送信側の意図した抑止である。

## 再試験前の必須確認

adapterを次のパラメータ付きで起動する。

```bash
ros2 run oit collision_ffb_node --ros-args \
  -p output_mode:=dry_run \
  -p freshness_mode:=challenge \
  -p max_magnitude:=0.05
```

速度・録画を始める前に次を確認する。

```bash
ros2 param get /collision_ffb_node freshness_mode
ros2 topic info /collision/ffb_challenge -v
timeout 5 ros2 topic hz /collision/ffb_challenge
```

`freshness_mode`が`challenge`、challenge publisherが1、周波数が約50 Hzでなければ試験を開始しない。WARNINGも確認するには、青箱を今回より約5 cm近づけて表示距離を約1.10 m以下にするか、停止状態の専用模擬ODOMを0.26 m/sとして約3秒送る。実機`/odom`とhardware modeは使用しない。

## 成果物

- [標準解析](phase5_callback_fix_dryrun_r01_analysis/analysis_report.md)
- `phase5_callback_fix_kobuki_r01_bag_summary.json`
- `phase5_callback_fix_kobuki_r01_events.csv`
- `phase5_callback_fix_hsr_r01_bag_summary.json`
- `phase5_callback_fix_hsr_r01_events.csv`
- [0.25 m/s区間の無編集生画像](report_assets/raw_phase5_callback_fix_dryrun_r01_motion.png)
