# 走行再試行r02：現在pin参照とload

ユーザーはr01で走行したが画面録画を忘れたと申告。r01は削除せず残し、
新接続・新保存先r02で画面録画も含めて短距離低速直進を再試行する。
今回提出は `1113motionr02.tar.xz` のpin原本3点だけで、走行結果の提出ではない。

## 確認結果

- session `24aad0a8d31d46eeb33ef252b0d18475`、pin frame1062。
- コピー時はpinned、latest2926、writer_done=false、error=null。
- PNGは1280×720の原画角。PNG SHA、復号BGR SHA、sidecarとstatusのpin情報が一致。
- 記録9コードSHAはローカルと一致。主JSONLが未提出のためpin元行SHAの照合は終了後。
- 保存時点の主距離は約1.396m。独立実測や走行結果・物理精度の確認ではない。
- comparison latest_slot_overwrites=1、tap_busy_drops=0。単一statusのみで全体負荷は判定しない。
- 現在までの接続継続やloadまでのwitness残存は未保証。

現在画像を無加工で確認し、局所天板境界x270〜380、中央y455付近を新規に読んだ。
r01より中央で約4px下に見えるが、カメラ姿勢変化量や床姿勢を断定しない。
黄色テープ部分x311〜339は隣接点間補間。読取りの目安2pxは物理精度の信頼区間ではない。
旧sessionを書換え転用しない。境界は自己遮蔽の別比較用で、床接地・高さ・取付再現や距離精度を認定しない。

## GPU PCへコピーしてload

このフォルダの `reference.json` を次の場所へコピーする。
まだpushしていないので、PullだけではGPU PCへ届かない。

`/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/guarded_motion_r02/reference.json`

受信・送信を継続し、まだ機体・カメラを動かさない。新pin・再起動・Lキーは不要。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r02 load
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r02 status
```

出力を共有し、active・同session/frame1062・reference_scope_verified・baseline_reproducedを確認してから走行へ進む。
失効やload_rejectedなら走行せず出力を共有する。比較はログ専用で、主表示・ROS・FFBを変更しない。

## 成功確認後の再試行と提出

画面録画開始と録画中表示を確認し、映像＋主距離欄session/frameを記録する。
現地監視・従来最低速・平坦な空間で停止10〜15秒→短距離直進→停止15〜20秒。
旋回・後退・意図的遮蔽は不要。距離を制御・停止判断には使わず十分な余裕を残す。
映像停止・遅延や数値急変が続く場合は通常の操作で停止して中止する。
運転UIのSキーを画像保存目的で押さない。bounded evidenceはcolour_contour_reaches_roi_edge保留専用で、
数値の一時的変動を自動保存しないため画面録画の代替ではない。

機体を通常操作で停止し、録画を保存して送受信を終了してから圧縮する。同名archiveを上書きしない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
tar -cJf /home/hsr/Downloads/guarded_motion_r02_full.tar.xz \
  Experimental_results/2026-11-13/driver_guarded_motion_r02 \
  recordings/2026-11-13/guarded_motion_r02 \
  recordings/2026-11-13/guarded_motion_evidence_r02
```

3フォルダのarchiveと画面録画を提出。evidenceフォルダ不在なら空フォルダを捏造せずエラー共有。
走行開始・停止のおおよその録画時刻があると対応確認に役立つ。

## 再現

原本3点は `recordings/2026-11-13/guarded_motion_pin_intake_r02/` へバイト一致保存。
既存検証・参照生成スクリプトは変更せず再利用した。関連17テストの成功済み検証を再利用する。
今回の実提出intake・参照生成は個別に実行して検証した。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/intake.py \
  --archive /home/robo25/Downloads/1113motionr02.tar.xz --archive-prefix 1113motionr02 \
  --intake-dir recordings/2026-11-13/guarded_motion_pin_intake_r02 \
  --output-dir Experimental_results/2026-11-13/guarded_motion_reference_r02/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/build_reference.py \
  --input-dir recordings/2026-11-13/guarded_motion_pin_intake_r02 \
  --audit Experimental_results/2026-11-13/guarded_motion_reference_r02/results_r01/audit.json \
  --boundary-csv Experimental_results/2026-11-13/guarded_motion_reference_r02/reviewed_boundary.csv \
  --output-dir Experimental_results/2026-11-13/guarded_motion_reference_r02
```

出力は新規パス必須。SHA来歴はresults_r01/audit.json・reference_validation.jsonを参照。
こちらでremote load・実機操作・走行・CUDAは実行していない。日報・commit/pushは今回未依頼。
