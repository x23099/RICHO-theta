# 受信を停止した後の再開：r02でpinし、3ファイルだけコピー

r01の受信は終了済み。元画像は問題なく解析できたが、次の接続にr01のpinを引き継げない。新しい保存先r02を使う。前の送受信プロセスが残っていれば普段の方法で終了し、二重起動しない。機体は停止し、取付後のカメラを動かさない。runtimeの再インストールや旧パッチの適用は不要。

カメラは電源操作のため毎回取り外すという条件が分かった。以下の距離は、既存profileの取付仮定を含む診断値であり、現在の距離精度・床姿勢の再現を保証しない。今回のpinは現在画像の自己遮蔽参照を得るためのもの。

## 1. GPU PCで受信（端末A）

従来の運転画面が動いたROS／Qt環境で実行する。r02が既存ならr03など新しい名前へ揃えて変更し、既存フォルダを削除しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"
bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python /home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  --motion-weights /home/hsr/Downloads/cone_distance_v03.pt \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir Experimental_results/2026-11-13/driver_guarded_static_r02 \
  --motion-target-roi 270 0 350 720 \
  --motion-experimental-rigid-mount \
  --motion-comparison-dir recordings/2026-11-13/guarded_static_r02
```

## 2. matunucで送信

IPとdeviceは前回値。今日動いた値が異なる場合はそちらを優先する。

```bash
cd /home/matunuc/theta_ws
export THETA_RTC_PYTHON=/home/matunuc/theta_ws/theta-env/bin/python3
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

## 3. 映像が更新されたらGPU PCの別端末Bでpin

```bash
cd /home/hsr/yopi_ws/RICHO-theta
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r02 pin
```

数秒後に確認する。

```bash
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r02 status
```

state=pinned、snapshots_saved=1と保存画像名があれば、次へ進む。error／pin_rejected／invalidated等が出る場合はその状態を共有し、無条件にpinを繰り返さない。

## 4. 受信を止めず、3ファイルを別フォルダへコピー

ファイルマネージャーで `/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/guarded_static_r02/` を開く。

1. `decoded_...png`、同名 `decoded_...json`、`comparison_status.json` の3点だけを選ぶ。
2. Downloads等に作った新しい別フォルダへコピーする。移動・削除ではなくコピーする。
3. **コピー先のフォルダ**を圧縮して提出する。元の受信／送信はそのまま継続する。

PNGと同名JSONはpin後に変わらない。statusのコピーはその時点の状態で、元ファイルが後で更新されてもコピーには反映されない。元フォルダ全体、更新中のcomparison_frames.jsonl、request.jsonは含めなくてよい。

受信・送信・カメラはそのままにする。まだloadや走行、Lキー操作はしない。画像確認後にこちらで新sessionに対応する参照を用意し、同接続でloadする。もし接続を切った場合はその旨を知らせる。
