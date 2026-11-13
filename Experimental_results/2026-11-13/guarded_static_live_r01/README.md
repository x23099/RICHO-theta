# 11/13：実カメラの静止確認から再開

前回の保存画像CUDA r04確認は完了。今回は現在の映像で主測距の更新と比較workerの参照・追加負荷を確認する。最初は機体を停止し、走行させない。新たな校正撮影・床マーカー・距離の実測・画面録画は開始条件にしない。

前回r04を実行したGPU PCはruntime反映済み。旧パッチ適用や同じ再生試験の繰返しは不要。ここで新しい測距コードや環境を導入するものではなく、既存の [静止手順](../../2026-11-11/guarded_async_comparison_r01/live_procedure.md) の保存先を本日用に分けた。カメラ取付位置・角度が前回から変わった場合は先に伝える。固定取付のprofileを無条件に転用できるとは扱わない。

## 1. GPU PC：受信開始（端末A）

従来の運転画面が動いたROS／Qt環境の端末で行う。UIとYOLOのPythonは分ける。旧受信器が動いていれば普段の方法で終了し、二重起動しない。前方にコーン1本を置き、車体天板の上端も写る状態にする。

以下の保存先が既にある場合は新しいr02等に変え、端末Bの比較保存先も同じ名前へ揃える。古いフォルダを削除・再使用しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"

bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python /home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  --motion-weights /home/hsr/Downloads/cone_distance_v03.pt \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir Experimental_results/2026-11-13/driver_guarded_static_r01 \
  --motion-target-roi 270 0 350 720 \
  --motion-experimental-rigid-mount \
  --motion-comparison-dir recordings/2026-11-13/guarded_static_r01
```

## 2. matunuc：映像送信

従来動いたROS環境・送信方法を使う。以下のGPU IP／deviceは前回使用した値で、今日の実機で検証した値ではない。異なる場合は実際の値へ変更する。`--diagnostic`ではなく `--motion-native` を使う。

```bash
cd /home/matunuc/theta_ws
export THETA_RTC_PYTHON=/home/matunuc/theta_ws/theta-env/bin/python3

bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

GPU側の通常映像が更新されることを確認する。主距離は条件を満たした時だけ現行の数値欄へ表示される。保留だけで即失敗とは判断しない。比較値はまだ主画面へ表示しない。映像／主測距が大きく遅れる・止まる場合は進めず、画面とログを共有する。操作キーを測距操作のつもりで押さない。

## 3. GPU PC：現在の元画像を1枚pin（別端末B）

映像が届いてから、同じGPU PCの別端末で実行する。端末Aの起動処理は終了しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r01 pin
```

数秒後、次で状態を確認する。

```bash
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r01 status
```

`state=pinned`、`snapshots_saved=1`、`pin.image_file`が表示されれば保存できている。pin_pendingのまま、pin_rejected／disabled／errorの場合は状態とログを共有し、pin要求を繰り返さない。主処理frameが新しく届くことが必要。

**いったんここで提出：** `recordings/2026-11-13/guarded_static_r01/` の次の3ファイル。

- `decoded_...png`：元の1280×720画像。スクリーンショット・加工画像に置き換えない。
- 同名の `decoded_...json`：元画像と主結果の対応情報。
- `comparison_status.json`：pin・workerの状態。

受信・送信は停止／再起動せず、カメラと機体も動かさない。同じ接続を維持する必要がある。接続断・入力が0.5秒を超えて途切れた場合は参照用digestが失効する場合があるので、復帰したらstatusと合わせて知らせる。

## 4. 画像確認後に参照をload（今はまだ行わない）

提出画像から現在の天板境界を読み、こちらで現在sessionに対応したreference.jsonを用意する。古いreferenceのsessionだけを書き換えて流用しない。

受け取ったreference.jsonを `recordings/2026-11-13/guarded_static_r01/reference.json` へ置き、同じ接続で次を実行する。

```bash
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r01 load
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r01 status
```

activeが読込み成功。比較数値はlatest.comparison_distance_available=trueの時だけあり、未検出・複数候補・自己遮蔽・鮮度切れなどでは保留する。

静止20〜30秒の主画面更新・主／比較ログ・保留・鮮度・負荷を確認し、普段の停止／UI終了手順で終了する。その後、主出力フォルダと比較フォルダの全体を提出してもらい、終了・速度・ageを解析する。比較機能の終了は機体停止命令の代わりにはならない。

静止確認の結果を見てから現地監視下の低速走行へ進むか判断する。比較値は主距離・ROS・FFB・自動停止へ接続しておらず、今回の確認で制御用途の採用や物理精度完成を宣言しない。
