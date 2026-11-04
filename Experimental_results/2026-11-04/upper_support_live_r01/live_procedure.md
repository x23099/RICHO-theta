# 次回：上端候補を別ログで同時記録する手順

静止・映像診断だけを行う。走行・TTC・FFBは起動しない。
今すぐ実施する必要はない。日付が変わったら、以下コマンド内の出力先2か所の日付を実施日に揃える。

## 1. Git共有と旧プロセスの通常終了

Git反映はユーザーの操作。必要なruntime変更は既存
`src/cone_distance_worker.py`、`src/run_cone_distance_live.py` と、新規
`src/cone_upper_support_candidate.py`、`src/cone_upper_support_live.py`。
対応テスト2ファイルと資料も必要に応じ共有する。別作業をまとめてstageしない。
今回こちらではcommit/pushしていない。

GPU PCで取得する。pullが失敗した場合はreset/上書きせずログを確認する。

```bash
cd ~/yopi_ws/RICHO-theta
git pull --ff-only
```

既存受信をGPU PCの画面でQ、既存送信をmatunucのターミナルでCtrl+Cにより終了する。
カメラ・車体の固定は維持する。旧結果・旧モデルは削除しない。

## 2. GPU PCで新しい受信を先に起動

出力先は未使用でなければならない。先にmkdirしない。
同名がある場合は `upper_support_capture_r01` を**2か所とも**同じ未使用番号に変える。
今回の資料フォルダ `upper_support_live_r01` は既存なので、受信出力先にしてはいけない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
./start_cone_distance.sh receive --weights "$HOME/Downloads/cone_distance_v03.pt" --target-roi 270 0 350 720 --colour-support-shadow --support-completion-shadow --frame-evidence --upper-support-shadow --fixed-floor-reload-file Experimental_results/2026-11-04/upper_support_capture_r01/prepared_floor.json --output-dir Experimental_results/2026-11-04/upper_support_capture_r01
```

旧コマンドとの主要な違いは `--upper-support-shadow` と未使用出力先。
`--fixed-floor-support-source` は既定のsupport_completion_shadowを維持する。
受信だけでは黒画面のため次の送信も必要。

## 3. カメラ/Kobuki PC（matunuc）で送信

GPU PCのIPが150.89.169.78、キャプチャが/dev/video0の例。
違う場合はGPU PCの `hostname -I`、matunucの `v4l2-ctl --list-devices` で実際の値を確認する。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --diagnostic --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

他の送信・bird_eye.pyで同じカメラを同時使用しない。
GPU PCの映像が実際に更新することを確認する。

## 4. 新接続の床PNGを1枚保存

1. 従来の剛性板を床へ平置きし、左円内で白紙の四隅が見えるようにする。
2. GPU PCの映像ウィンドウでSを1回押す。
3. 新しい `decoded_<session>_f<frame>.png` を提出する。
4. 受信・送信は起動したまま維持する。この時点ではLをまだ押さない。

既知条件は紙296×210mm、板厚概算15mm、レンズ床上高さ59cm。
違う板や固定状態なら申告する。新しいPNGを確認してから同sessionモデルを準備する。
旧prepared_floorのsessionを書き換えたり、旧画像の角座標を無条件転用したりしない。

## 5. モデル準備後にL、コーン約1mで静止

新prepared_floorを起動時指定のパスへ配置した後にLを1回押し、loader activeを確認する。
その後、板は片付けてよい。カメラ・車体・接続は維持する。
コーンだけを正面約1mへ置き、今回と同じ測定基準で実距離をメモし、30秒ほど静止する。
通常画面は旧比較のままなので、見た目に改善がなくても新ログの有無を確認する。

保留frameのPNGは自動で最大20試行・1秒以上間隔で保存する。
全frameを保存しているわけではなく、古い値を表示し続ける機能でもない。

## 6. 保存・提出

GPU PCの映像ウィンドウでQを押し、終了を待つ。その後matunucの送信をCtrl+Cで停止する。
GPU PCで専用reportを生成できる。

```bash
cd ~/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/cone_upper_support_live.py --input-dir Experimental_results/2026-11-04/upper_support_capture_r01 --output-dir Experimental_results/2026-11-04/upper_support_capture_report_r01
```

提出は受信出力フォルダ全体を圧縮したものが確実。画像・モデル・events・旧/新ログ・終了summaryを一緒に保つ。

```bash
tar -cJf ~/Downloads/upper_support_capture_r01.tar.xz -C Experimental_results/2026-11-04 upper_support_capture_r01
```

Gitにraw録画やPNG一式を追加しない。圧縮元も削除しない。
確認項目は、旧/新候補の算出率、元候補が変わっていないか、追加PNGの同frame対応、
3回確認、世代/鮮度拒否、追加処理の時間、正常終了である。
これは画像上の候補改善試験であり、距離精度・走行・FFBの合格ではない。
