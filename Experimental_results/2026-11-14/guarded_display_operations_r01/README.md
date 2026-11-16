# 11/14作業：確認済み走行診断表示の運用条件・再開手順

このフォルダは**ユーザー指定の11/14作業扱い**で作成した。11/13の実験日時や実時計は変更していない。
11/13分は日報・監査・代表4点をcommit `0ecfad2` としてorigin/mainへpush済み。その完了後のローカル作業をここへ分離した。

**本資料と新pack_submission.pyは現時点ではローカル未commit／未push。GPU PCで使用する前に別途反映が必要。今すぐの実機操作・追加撮影は不要。**

## 確認済みの構成と採用範囲

[11/13の実機根拠](../../2026-11-13/body_display_occlusion_live_audit_r01/README.md)で、固定取付・平面床仮定・赤コーン・前方native ROIにおける「走行中の数値→自己遮蔽保留→復帰」を確認済み。
同じ確認を繰り返すための撮影や再学習はしない。新helperは提出作業だけを補助し、測距／表示ゲート／ROS／操縦／FFBの実行コードを変更しない。

| 状態 | 診断表示の扱い | 運用上の注意 |
|---|---|---|
| 現在支持列が確認した天板境界より上 | 元主値をそのまま許可 | カメラ直下基準の水平距離。接触距離ではない |
| 台座の支持列が天板境界へ達する | WITHHELD／possible_self_body_occlusion | 近い数値が元ログにあっても表示へ戻さない |
| 元検出が曖昧／ROI端／候補なし | 元保留を維持 | 自己遮蔽の成功件数に混ぜず、理由を記録 |
| 参照未load・失効・古い入力 | WITHHELD | 古い数値を表示保持しない。statusを確認 |

既定OFF。使うときだけ `--motion-body-display-guard` を付ける。数値を停止判断・FFB・操縦へ使用しない。
取付再現・物理誤差・床傾斜補償・床接地の認定は別課題である。

## 新しい日に再開する場合

前回受信は終了済みなので、旧pin17327のsession書換え転用はしない。現在カメラの取付後、初回は機体停止・対象1本で始める。
カメラや車体の位置を固定し、意図しない駆動を抑止する従来の手順を維持する。

以下は**将来のGPU PCでの例**。既存r01がある場合は削除せず、主／比較両方を同じ新suffixへ変更する。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
if test -e Experimental_results/2026-11-14/driver_body_guard_live_r01 || test -e recordings/2026-11-14/body_guard_live_r01; then
  printf '保存先が存在します。削除せず、新しいrun名を選んでください。\n'
else
  export THETA_UI_PYTHON=$(command -v python3)
  bash src/start_theta_receive_rtc.sh --motion-distance \
    --motion-python /home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
    --motion-weights /home/hsr/Downloads/cone_distance_v03.pt \
    --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
    --motion-output-dir Experimental_results/2026-11-14/driver_body_guard_live_r01 \
    --motion-target-roi 270 0 350 720 \
    --motion-experimental-rigid-mount \
    --motion-comparison-dir recordings/2026-11-14/body_guard_live_r01 \
    --motion-body-display-guard
fi
```

matunuc送信は従来のnative経路を使い、二重送信しない。IP／deviceはその日の実際の接続先を確認する。
前回例は以下だが、固定IPの現時点の到達性をこちらで確認したものではない。

```bash
cd /home/matunuc/theta_ws
export THETA_RTC_PYTHON=/home/matunuc/theta_ws/theta-env/bin/python3
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

## 現在pinの4点を提出：途中で受信を止めない

GPU PCの別端末でpin1回→数秒後status：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-14/body_guard_live_r01 pin
```

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-14/body_guard_live_r01 status
```

pinned・error=null・writer_done=false、最新理由comparison_pin_requestedを確認する。
古いpinが同じフォルダに残っていても、**ワイルドカードで全PNGを集めない**。
新helperをGPUへ反映した後だけ：

```bash
./yolo-env/bin/python3 Experimental_results/2026-11-14/guarded_display_operations_r01/pack_submission.py pin \
  --primary-dir Experimental_results/2026-11-14/driver_body_guard_live_r01 \
  --comparison-dir recordings/2026-11-14/body_guard_live_r01 \
  --output /home/hsr/Downloads/body_guard_pin_20261114_r01.tar.xz
```

最新statusが指すPNG／同名JSON／statusの原バイト／engine summaryの4点だけを選ぶ。
pinとJSON・PNG SHA・native寸法・非制御flags・主出力と比較保存先の結合を確認する。
GPU PC自身のmonotonic clockでstatusと入力の鮮度を確認するため、別PCへコピー済みの古いstatusをこのhelperで再包装しない。
内部PNG復号BGR SHAや完全主元行SHAの照合は後続の解析側で行う。helperだけで実画素や物理精度を認定しない。

作成archiveをこのPCへ提出する。受信・送信と停止状態を維持し、現在画像用の新reference.jsonを受け取るまでloadしない。
archive内prefixは `body_guard_pin_submit`。解析側の4点intakeで `--archive-prefix body_guard_pin_submit` を指定する。

## 新参照のコピー・SHA照合・load

現在pinに結んだ参照ファイルをGPUの現在比較フォルダへコピーし、**その新参照について提示されたSHA**と照合する。
旧pin17327のSHAを使ったり、reference.jsonのsession／frameを手で書換えたりしない。

```bash
sha256sum recordings/2026-11-14/body_guard_live_r01/reference.json
```

新参照のSHA一致後だけ1回load：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-14/body_guard_live_r01 load
```

数秒後、上と同じstatusコマンドでactive／現在session・pin／scope=trueを確認し、画面下部の数値＋body-review genを確認する。
別比較のstatusだけで主画面に数値が出たと判定しない。
この再開確認は新接続の参照結合のためであり、11/13に成立した走行・遮蔽・復帰試験全体の再撮影を必須にするものではない。

## 終了・全ログの提出

試験や記録を実施した場合は必要な画面録画を停止し、受信を通常終了して端末が戻るまで待つ。
主summary・比較statusの正常終了がそろってから、新helperを使う。

```bash
./yolo-env/bin/python3 Experimental_results/2026-11-14/guarded_display_operations_r01/pack_submission.py closed \
  --primary-dir Experimental_results/2026-11-14/driver_body_guard_live_r01 \
  --comparison-dir recordings/2026-11-14/body_guard_live_r01 \
  --output /home/hsr/Downloads/body_guard_full_20261114_r01.tar.xz
```

更新中のwriter／終了未完・エラーがあれば圧縮しない。主・表示レビュー・bridge・比較・pin群・参照などを元ディレクトリ名で収める。
全体提出では過去pinも含むrun全体を保持し、画面録画は別送でよい。recordingsや元ファイルを消さない。
archiveが同名で存在した場合は**出力名だけ**をr02等へ変え、元の主／比較フォルダ名は変えない。受信のやり直し・再pinも不要。

## 困ったときの扱い

| 状況 | 次の操作 |
|---|---|
| mkdir／archiveが既に存在 | 元データは削除しない。新runなら両保存先、再圧縮なら出力名だけ変更 |
| pin中にinput_gap／stale等 | pinned表示だけで継続を断定せずstatus共有。pin／loadを連打しない |
| load_rejected | エラーを共有。既存witnessを失効させ得るので繰返しloadしない |
| missing file／pin JSON・SHA不一致 | helperの検査を削除せず、エラーとstatusを共有 |
| closed圧縮が「まだ稼働中」と拒否 | 通常終了の完了を確認。killやログ削除で強行しない |
| 新接続・カメラ再取付 | 現在pinと新参照へ。旧sessionを手で書換えない |

## この作業枠での実施範囲

helperは標準ライブラリだけで動き、カメラ・ROS・モデルをimportせず、pin／load要求も送らない。明示指定したarchive以外へ提出物を書かず、元ファイルを変更しない。
読取りはregular file・件数・サイズ・symlinkを制限し、圧縮中のファイル変化も検知する。出力は一時コピー完成後の非上書きatomic publicationで、同名の既存archiveを置き換えない。
前回の実験データを使った新しい実機試験ではなく、ダミーのメタデータとバイトによるオフライン検証。実カメラ・CUDA・ROS・matunuc・GPU PCはこの作業枠では起動していない。
検証記録はchecks_r01へ保存する。今回11/14分は終業依頼を受けておらず、日報・commit・pushはまだ行わない。
