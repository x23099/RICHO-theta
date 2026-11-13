# 次の実機確認：比較処理も併用した低速直進

静止r02の確認は完了。同じソフトで、比較処理も稼働した状態の走行時更新・保留・鮮度・負荷を確認する。**まず手順1〜3の送受信・pin提出まで。参照loadの確認前には走行しない。**

前回r02は終了済みなので、新しいsessionと新しい保存先を使う。旧reference.jsonのコピーやsessionの書換え転用、旧パッチ再適用、環境の再インストールはしない。今回新しい測距runtimeの導入はない。

## 0. 条件

- 現地で機体を見て停止できる操縦者・安全確認者がいること。周囲・進行先に人や物がなく、コーンに十分な余裕を残せる平らな場所で行う。条件を満たさなければ走行を始めない。
- 赤コーン1本を前方中央へ。他のコーンは最初から対象範囲外へ置く。試験中に人が前を横切ったり、コーンを手で隠したりしない。
- 電源操作後に固定したカメラを、終了まで取り外さず動かさない。毎回の取付再現・床姿勢は未検証のため、数値は診断用で、走行制御・自動停止・FFBには使わない。距離表示だけを頼りに接近しない。
- 最初は従来使っている最低速設定で短い直進だけ。旋回・段差・接触・意図的遮蔽・後退試験は今回の初回に含めない。安全な停止は従来の機体の停止手順を使い、比較機能のinvalidateや受信終了を停止命令の代わりにしない。

以下のr01が既存なら3フォルダすべてを新しいr02等へ揃える。既存フォルダを削除・再使用しない。

## 1. GPU PC：通常運転UIの環境で受信（端末A）

```bash
cd /home/hsr/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"
bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python /home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  --motion-weights /home/hsr/Downloads/cone_distance_v03.pt \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir Experimental_results/2026-11-13/driver_guarded_motion_r01 \
  --motion-target-roi 270 0 350 720 \
  --motion-experimental-rigid-mount \
  --motion-comparison-dir recordings/2026-11-13/guarded_motion_r01 \
  --motion-withheld-evidence-dir recordings/2026-11-13/guarded_motion_evidence_r01 \
  --motion-withheld-evidence-max-frames 40 \
  --motion-withheld-evidence-max-mib 128 \
  --motion-withheld-evidence-interval-sec 1
```

追加した証拠保存は既存機能で、輪郭がcrop境界に達して保留した場合のnative PNG／同名JSONだけを最大40組・128MiB・1秒間隔で保存する。**数値が出た一時的な大きい値を自動保存する機能ではない。** そのため今回の短い画面録画も併用する。保存画像や保存上限を理由に距離判定は変えない。原画像へ注釈・切抜き等は行わない。

## 2. matunuc：これまでの送信

IP／deviceは今日動いた値を優先し、二重送信しない。

```bash
cd /home/matunuc/theta_ws
export THETA_RTC_PYTHON=/home/matunuc/theta_ws/theta-env/bin/python3
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

## 3. 停止状態のまま、GPU PCの別端末Bでpin・status

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r01 pin
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r01 status
```

state=pinnedと保存画像名を確認する。**ここでPNG・同名JSON・comparison_status.jsonの3点だけを別フォルダへコピーし、コピー先を圧縮して提出する。** 元の更新中ログやフォルダ全体は途中提出に含めない。受信・送信は継続し、機体とカメラを動かさない。

この画像からこちらで現在session用の境界参照を用意する。現在の送受信を維持している間に準備・loadまで進め、途中で再起動しない。失効／接続断があればその状態を共有する。

## 4. 新しい参照を受け取った後にload（今はまだ行わない）

受け取ったreference.jsonを `recordings/2026-11-13/guarded_motion_r01/reference.json` へ置く。

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r01 load
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r01 status
```

出力を共有し、active・同session/frame参照照合を確認する。読込み失敗や入力失効があれば走行を始めず、出力をそのまま送る。主表示は現行の距離で、比較値は別ログだけ。コーンの複数候補、対象範囲外、遮蔽、古い入力等での保留を無理に解除しない。

## 5. load成功を確認してから短い画面録画と直進

普段使っている画面録画方法で、**映像と下部の主距離欄・session/frame番号が一緒に入るように**録画する。キーSなどを画像保存のつもりで押さない（運転UIの操作キーは操縦に関わる）。画面録画が使えない場合は走行前に知らせる。

| 順序 | 行うこと |
|---|---|
| A | 停止状態で約10〜15秒。映像・主距離・比較statusの更新を確認する |
| B | 現地の操縦者が従来操作の最低速で短距離だけ直進し、停止する。コーンへ近づき過ぎない。無理に一定時間走らせる必要はない |
| C | 停止後、約15〜20秒の更新を記録する。これ以上の試行は初回提出を見てから決める |

映像・主距離が止まる／大きく遅れる、急な数値変化が続く、対象を見失う、人が進入する、機体挙動に不安がある場合は、通常の安全な停止操作で中止する。原因を調べるためにそのまま接近しない。距離の増減だけで「走行成功」とせず、録画でA/B/Cの状態を対応させる。

画面録画は場面・表示・frameの対応を助ける証拠で、独立実測距離やnative画素と同等の証拠ではない。取付再現性や動的姿勢補償の未検証条件は残る。比較のhalf-pixel救済が出ない実行でも、更新と棄却・負荷の確認として記録する。

## 6. 機体停止後に送受信を終了し、提出

先に通常の方法で機体を停止する。録画を保存し、受信UI・送信を普段の方法で終了する。ログが閉じてから次を圧縮する。同名archiveがある場合は別名へ変える。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
tar -cJf /home/hsr/Downloads/guarded_motion_r01_full.tar.xz \
  Experimental_results/2026-11-13/driver_guarded_motion_r01 \
  recordings/2026-11-13/guarded_motion_r01 \
  recordings/2026-11-13/guarded_motion_evidence_r01
```

提出するものは上記archiveと短い画面録画。evidence初期化エラー等で3つ目のフォルダが作られていない場合は空フォルダを捏造せず、エラーを共有する。ログや画像を編集・間引き・削除しない。元画面録画も加工せず、走行開始／停止のおおよその録画時刻が分かれば添える。

終了・主bridge対応・比較値／理由・参照失効・load前後・録画A/B/C区間の更新頻度・age・証拠writer負荷を解析する。走行確認の結果と、床接地・物理精度・自動制御への採用は別に判断する。
