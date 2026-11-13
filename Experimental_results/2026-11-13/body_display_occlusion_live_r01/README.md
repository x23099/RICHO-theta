# 車体停止での表示ゲート確認：数値→台座遮蔽で保留→復帰

2026-11-13 JST。前回の[静止全体監査](../body_display_static_live_audit_r01/README.md)は完了。
今回は、実画面で自己遮蔽時の表示棄却を確認する。**機体は走行させず、現地の人がコーンを移動する。**
既存のゲート実装を使い、閾値・校正・操縦・ROS・FFBは変更しない。今回のための新パッチ・再インストールは不要。

**今は手順1〜4の「新pin4点の提出」まで。新参照とload成功を確認する前にコーンの接近試験を始めない。**
旧 `body_guard_static_r01` は終了済みなので、pin361参照を再利用しない。

## 1. 現地の準備

- 車体は従来の停止・駆動抑止の手順で、意図しない動作が起きない状態にする。ペダル・ハンドルの走行操作はしない。映像送信だけでは駆動抑止にはならない。
- カメラ取付後、今回の終了までカメラ・車体を動かさない。カメラを触った／接続をやり直した場合は報告する。
- 赤コーン1本を床に置き、台座の手前辺が見える前方（目安1.5m程度）から始める。元画像の左レンズ中央、これまでのROI中央付近に合わせる。他コーンはROIから外す。
- チェックボード・床テープ・厳密な距離実測は今回の表示切替確認には不要。距離精度の校正試験ではない。
- GPU PCは前回と同じ表示ゲートONのコードを使う。旧受信が残っていれば通常終了し、二重起動しない。

## 2. GPU PC：新保存先で受信

前回と混ざらない保存先を指定する。既にこのr01が存在した場合は削除・上書きせず、表示されたメッセージを共有する。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
if test -e Experimental_results/2026-11-13/driver_body_guard_occlusion_r01 || test -e recordings/2026-11-13/body_guard_occlusion_r01; then
  printf '保存先が存在します。起動せず、別の保存先を確認してください。\n'
else
  export THETA_UI_PYTHON=$(command -v python3)
  bash src/start_theta_receive_rtc.sh --motion-distance \
    --motion-python /home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
    --motion-weights /home/hsr/Downloads/cone_distance_v03.pt \
    --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
    --motion-output-dir Experimental_results/2026-11-13/driver_body_guard_occlusion_r01 \
    --motion-target-roi 270 0 350 720 \
    --motion-experimental-rigid-mount \
    --motion-comparison-dir recordings/2026-11-13/body_guard_occlusion_r01 \
    --motion-body-display-guard
fi
```

まだ参照がないため、元測距ログには数字があっても画面下部の `WITHHELD / display_body_reference_unavailable` は正常。
前回ONが確認済みの実装を使うので、旧パッチの `git apply` を再実行しない。

## 3. matsunuc：映像送信

これまで動作したIP／deviceを優先する。既に同じ送信が稼働中なら二重起動しない。
以下のIP `150.89.169.78` は前回手順のGPU PC宛先。変更された場合は実際のGPU PCのIPを使う。

```bash
cd /home/matunuc/theta_ws
export THETA_RTC_PYTHON=/home/matunuc/theta_ws/theta-env/bin/python3
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

映像と測距欄のframe更新を確認する。UIのL／Sキーで参照取得や保存をしない。

## 4. GPU PCの別端末：pinし、4点だけコピーして提出

赤コーンとカメラ・車体を止め、PNGの準備ができたら1回だけ：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 pin
```

数秒後に確認：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 status
```

`state=pinned`、`pin`内に現在session／frame／image_file、`writer_done=false`、`error=null`を確認。
違う場合はその出力を提出し、pinやloadを連打しない。

コピー対象は次の4点だけ。PNGは加工しない。

| ファイル | GPU PCのコピー元 |
|---|---|
| 現在の `decoded_….png` | `recordings/2026-11-13/body_guard_occlusion_r01/` |
| 同じ名前の `decoded_….json` | 同上 |
| `comparison_status.json` | 同上 |
| `motion_engine_summary.json` | `Experimental_results/2026-11-13/driver_body_guard_occlusion_r01/` |

この新保存先でpinが1回だけなら、次のコマンドで4点を別フォルダへコピーし、圧縮できる。
`mkdir`や`cp`でエラーが出た場合は先へ進まず共有する。元の4点は移動・削除しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
mkdir recordings/2026-11-13/body_guard_occlusion_pin_submit_r01 && \
cp -n recordings/2026-11-13/body_guard_occlusion_r01/decoded_*.png \
  recordings/2026-11-13/body_guard_occlusion_r01/decoded_*.json \
  recordings/2026-11-13/body_guard_occlusion_r01/comparison_status.json \
  Experimental_results/2026-11-13/driver_body_guard_occlusion_r01/motion_engine_summary.json \
  recordings/2026-11-13/body_guard_occlusion_pin_submit_r01/ && \
test ! -e /home/hsr/Downloads/body_guard_occlusion_pin_r01.tar.xz && \
tar -cJf /home/hsr/Downloads/body_guard_occlusion_pin_r01.tar.xz \
  -C recordings/2026-11-13 body_guard_occlusion_pin_submit_r01
```

提出物：`/home/hsr/Downloads/body_guard_occlusion_pin_r01.tar.xz`。
**ここでいったん提出し、受信・送信と車体停止を維持する。更新中の全ログを圧縮する必要はなく、転送のために受信を止めない。**
画面録画もまだ開始不要。こちらで現在画像から参照を作成し、専用のコピー先・SHA・loadコマンドを提示する。
状態が変わった／接続が切れた／保存上限に達した場合は共有し、旧参照のsession書換えで復旧しない。

## 5. 参照作成後：同接続でloadと表示を確認（まだ実施しない）

新参照をこの実行の比較フォルダへ置き、提示されたSHAに一致した場合だけ1回loadする。
専用コマンドは新pin確認後に提示する。まずactive／同session・pin／reference_scope_verifiedと、
画面下部の数値＋`body-review gen 1`を確認する。load失敗ならエラーを共有し、そのまま試験へ進まない。

## 6. load成功確認後：画面録画し、コーンだけを動かす（まだ実施しない）

これまでと同じ方法で画面録画を開始し、録画中表示を確認する。映像と画面下部の距離・理由・session/frameが読める画面を含める。
録画中、車体は停止を維持する。人がコーンを動かす間の映り込みは判定対象にせず、各位置で手を離れて確認する。

| 段階 | 動かすもの・保持 | 確認する表示 |
|---|---|---|
| A：見える | 初期位置のコーンを約5秒保持 | 数値＋body-review gen |
| B：台座を隠す | コーンを床に置いたまま中央方向から少しずつ近づけ、画像で台座の手前辺が天板に隠れた位置を約5秒保持 | `WITHHELD`。可能なら理由も記録 |
| C：戻す | 元の見える位置へ戻し約5秒保持 | 数値＋body-review genへ復帰 |

距離値を頼りに近づけず、実際の車体との間隔と元映像を確認する。接触・押込み・持ち上げ・カメラへの接触はしない。
人が安全に置ける範囲で台座を隠せなければ無理をせず中止し、その状況を報告する。

保留理由が `possible_self_body_occlusion` なら狙った表示棄却の候補。
`no_candidate`／`colour_contour_reaches_roi_edge`／曖昧判定だけの場合もそのまま記録するが、自己遮蔽ゲート成立とはまだ扱わない。
台座が隠れても数値が残る場合は試験を止めて録画とログを残し、閾値変更・再pin・再loadで保留を無理に解除しない。

今回は切替確認であって走行／接触回避／精度の合格判定ではない。数値は操縦・ROS・FFB・自動停止に使わない。

## 7. 終了後の提出（段階A〜C実施後）

録画停止後、受信をこれまでの通常手順で終了し、起動した端末が戻るのを待つ。
比較がclosed／writer_done=true／shutdown_complete=trueになり、主出力に `driver_motion_summary.json` ができてから圧縮する。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 status
```

主summaryと比較statusの確認後だけ：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
test -f Experimental_results/2026-11-13/driver_body_guard_occlusion_r01/driver_motion_summary.json && \
test ! -e /home/hsr/Downloads/body_guard_occlusion_r01_full.tar.xz && \
tar -cJf /home/hsr/Downloads/body_guard_occlusion_r01_full.tar.xz \
  Experimental_results/2026-11-13/driver_body_guard_occlusion_r01 \
  recordings/2026-11-13/body_guard_occlusion_r01
```

提出は **全ログarchive＋今回の画面録画**。録画は別送でよい。画面録画だけ・comparisonフォルダだけでは表示ゲートの元主ログ照合ができない。
主フォルダの `motion_display_reviews.jsonl` もフォルダごと含まれる。
前の試走ログを削除しない。録画の開始・終了と対応frameを根拠に今回の試験区間を切り出す。

## このPCで行った検証の範囲

本手順のBashコードブロックの構文、受信側の実 `add_motion_arguments` によるフラグ解釈、送信側ASTに定義されたフラグを確認した。
さらにコピー・圧縮のブロックを一時ディレクトリ内のダミー4点で検証した。元データ・画素は使っていない。
`tests/test_body_display_occlusion_procedure.py` の4テスト成功。7個のBashブロックは構文確認のみで、受信・送信・pin要求を実行していない。
UI／カメラ／CUDA／ROS・送受信・実機の起動は行っていない。実施結果は次回の提出を待つ。日報・commit/pushは今回未依頼。
