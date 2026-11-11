# GPU PCへの反映と、実カメラの静止確認

> **最新更新**：[GPU r04の実CUDA負荷確認まで完了](../guarded_cuda_gpu_audit_r04/README.md)。比較ONの主処理P95は23.91ms・28.96件/秒で、保存画像の負荷対策を一区切りとした。r04実行PCは `2cca269`（1111v5）まで反映済み。パッチ再適用・同じ再生・Pullのやり直しは不要で、カメラが使える日に手順1から進める。本日はmatunucが使用不可のため、まだ実行を求めない。静止実映像の遅延は未確認。

2026-11-11。保存データによる実装試験は完了。**ここから現在sessionのカメラ画像が必要になる。** まず静止状態で、主測距と別の比較ログを確認する。走行・画面録画・チェックボード／L字・距離の測り直しは今回不要。

## 0. 更新を反映する

**今回r04を実行したGPU PCでは完了済み。この手順を飛ばして手順1へ進む。** 以前のasync／compute_reuse／compact／domainパッチはどれも再適用しない。測距runtimeは `2cca269`（1111v5）でGitに反映済みで、提出コードSHAも一致した。

別PCを新規に準備する場合だけ、普段のVSCode等で同じリポジトリをPullする。別作業の削除・未追跡ファイルや独自変更を保持し、競合時にreset・強制上書きしない。更新は受信UIを終了し機体を停止した状態で行う。送信側は今回変更しておらず、これまで動いた `--motion-native` を使う。

## 1. GPU PCで受信を開始（端末A）

**普段の運転UIで使うROS／Qt環境**で実行する。UIとYOLOのPythonは別指定。以下は初回用の新規`r01`で、既に存在すれば両フォルダ名を`r02`等へ揃えて変える。既存フォルダを削除・再使用しない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"

bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python "$THETA_DISTANCE_PYTHON" \
  --motion-weights "$HOME/Downloads/cone_distance_v03.pt" \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir Experimental_results/2026-11-11/driver_guarded_live_r01 \
  --motion-target-roi 270 0 350 720 \
  --motion-experimental-rigid-mount \
  --motion-comparison-dir recordings/2026-11-11/guarded_live_r01
```

主画面の距離表示は今までどおり。比較値を主画面へ表示する変更はしていない。操作キーを測距操作のつもりで押さない。

## 2. matunucで、昨日動いた送信を開始

通常のROS環境・既存の送信手順を使う。以下のIP／deviceは前日の例なので、昨日実際に動いた値を優先する。二重送信／二重受信せず、`--diagnostic`ではなく`--motion-native`。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

機体は停止状態を維持する。遠隔作業だけなら走行させない。通常映像と主距離の更新が大きく遅れる／止まる場合は比較確認を中断し、従来の手順で停止・終了する。比較機能の終了を機体停止の代わりにしない。

## 3. 現在のnative画像を1枚pin（GPU PCの別端末B）

カメラが映り、車体天板の上端が見える状態で行う。コーンも映っていると後の比較がしやすいが、参照1枚を作るだけなら天板境界が読めればよい。

別端末なので端末Aの変数は引き継がれない。以下も同じ`r01`を指定する：

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
"$THETA_DISTANCE_PYTHON" src/manage_guarded_comparison.py \
  --directory recordings/2026-11-11/guarded_live_r01 pin
```

数秒後に状態を確認：

```bash
"$THETA_DISTANCE_PYTHON" src/manage_guarded_comparison.py \
  --directory recordings/2026-11-11/guarded_live_r01 status
```

`state=pinned`、`snapshots_saved=1`、`pin.image_file`にPNG名が出れば保存できている。`pin_pending`のままなら新しい主測距frameが届いていない。`pin_rejected`／`disabled`なら`detail`／`error`を共有し、何度もpinを押し直さない。

**この時点で提出してほしいもの：** 同フォルダの`decoded_...png`と同名`.json`、`comparison_status.json`。フォルダごとコピーでもよい。加工・トリミング・スクリーンショットに置き換えず、元PNGを送る。

**受信UIと接続は、そのまま継続する。** ここで止める／再起動すると同sessionのpinをloadできなくなる。入力が途切れて0.5秒超でも参照用digestが失効する場合があるため、長時間入力が止まったら状態と合わせて相談する。

## 4. 参照を用意した後にload（画像確認後の段階）

提出画像から現在の天板境界を読み、対応する`reference.json`をこちらで用意する。過去の参照JSONのsessionを書き換えて流用しない。今回の画像を確認する前にloadを試す必要はない。

受け取った`reference.json`を`recordings/2026-11-11/guarded_live_r01/reference.json`へ置き、同じ接続のまま：

```bash
"$THETA_DISTANCE_PYTHON" src/manage_guarded_comparison.py \
  --directory recordings/2026-11-11/guarded_live_r01 load
"$THETA_DISTANCE_PYTHON" src/manage_guarded_comparison.py \
  --directory recordings/2026-11-11/guarded_live_r01 status
```

`state=active`が読込み成功。`latest.comparison_distance_available=true`の時だけ比較数値がある。コーン未検出、複数候補、自己遮蔽等では正常に保留するため、数値が出ないことだけで読込み失敗と判断しない。

静止状態で20～30秒程度、主画面の更新と別ログの継続を確認する。負荷測定用には同じ実行の主ログ・engine/profile/bridge summaryと比較フォルダが必要。終了時は普段の停止・UI終了手順を使い、`writer_done=true`／`shutdown_complete=true`を確認する。画面録画や走行はこの最初の確認には不要。

比較だけを無効化する端末要求は`invalidate`。これも機体停止命令ではない。

## カメラがまだ使えない場合のGPU PC確認（任意）

**r04を提出済みのGPU PCでは以下も完了済みの履歴。繰り返さなくてよい。** 未変更コードでの実行を、カメラを待つ間の必須作業とはしない。

新しい環境で保存データの再生だけを試せる。これは実カメラ確認の代替ではなく、ローカルでは既に同じ8画像で成功済み。元17:12フォルダが前日と同じ保存先にある場合：

```bash
"$THETA_DISTANCE_PYTHON" \
  Experimental_results/2026-11-11/guarded_async_comparison_r01/replay.py \
  --input-dir Experimental_results/2026-11-10/driver_motion_live_20261110_171250 \
  --evidence-dir recordings/2026-11-10/motion_withheld_20261110_171250 \
  --comparison-dir recordings/2026-11-11/guarded_gpu_cached_r01 \
  --output-dir Experimental_results/2026-11-11/guarded_gpu_cached_r01
```

最後に`state=pass`、`primary_off_on_equal_images=8`となれば再生経路は一致。保存枠による検証専用モードなので、新規YOLO推論・カメラ・操縦は起動しない。元フォルダが別の場所なら実パスへ置き換え、新たに撮り直す必要はない。
