# GPU PC反映後の停止状態確認（まだ未実施）

この手順は新コード一式をGPU PCへ反映した後に使う。今回の変更はまだcommit/pushしていない。
旧パッチ適用やPullだけで反映済みと判断しない。`driver_body_display_guard.py`を含めsrcの5ファイルが必要。
カメラなしの関連テストが成功してから実機段階へ進む。ここでは機体を動かさない。

## カメラ不要の単体確認

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 -m unittest discover -s tests -p test_driver_body_display_guard.py -v
```

19件の合成データ検証で、カメラ・ROS・実YOLO・CUDA・ネットワークを起動しない。
不足するコードや依存関係で失敗した場合はログを共有し、再インストールや実機起動へ進まない。

## 受信：新保存先で停止確認

既存フォルダがある場合は削除・再使用せず、新suffixを全コマンドで揃える。
通常UIのPython環境を使う。独立したGPU Pythonは以下の既知パス。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"
bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python /home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  --motion-weights /home/hsr/Downloads/cone_distance_v03.pt \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir Experimental_results/2026-11-13/driver_body_guard_static_r01 \
  --motion-target-roi 270 0 350 720 \
  --motion-experimental-rigid-mount \
  --motion-comparison-dir recordings/2026-11-13/body_guard_static_r01 \
  --motion-body-display-guard
```

今回の追加は末尾の`--motion-body-display-guard`。
元主結果は数字でも参照がまだないので、表示は`WITHHELD / display_body_reference_unavailable`になる想定。
これは新モードの設計どおりで、未loadのまま故障と判断して旧オプションへ戻さない。

## matunuc送信

本日動作したIP/deviceを優先し、二重送信しない。固定カメラは終了まで取り外さない。

```bash
cd /home/matunuc/theta_ws
export THETA_RTC_PYTHON=/home/matunuc/theta_ws/theta-env/bin/python3
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

## 新pinを提出するところまで

赤コーン1本を遮蔽のない前方へ置き、機体停止状態で映像を確認する。
運転UIのSキーを保存目的で押さない。GPU PCの別端末から：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_static_r01 pin
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_static_r01 status
```

現在のPNG・同名JSON・status3点だけを別フォルダへコピーし、コピーを圧縮して提出する。
送受信は継続し、機体とカメラを動かさない。元主JSONLには数値が出ていても、未loadなら表示は保留のままで正しい。
新画像から参照を用意した後、SHA照合→同接続load→status→正常数値とbody-review genの表示復帰を確認する。
ここでは旧r02参照・frame18497等を使わない。load失敗は照合情報を失効させるため連打せず出力共有。
停止状態の成立を確認するまで、追加の接近・走行・近接遮蔽の撮影は行わない。
