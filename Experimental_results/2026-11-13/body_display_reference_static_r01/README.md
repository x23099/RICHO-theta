# 表示ゲートONの停止確認：新pin361参照

## 4ファイルの確認

提出1113body.tar.xzは必要4点が揃っている。
session e011664e9b994ce1b070439efa875b6a、pin361、コピー時latest8944／pinned／writer_done=false／error=null。
PNGは1280×720、元PNG SHA・復号BGR SHA・sidecar/statusのpin情報が一致。
表示ゲートenabled=true・表示棄却専用・元主結果非変更をengine summaryで確認した。
比較の記録9コードSHAに加え、表示ゲート関連7コードSHAが現在ローカルと一致（重複を除くと12ファイル）。
profile/config・記録checkpoint SHAも一致。重み本体は未提出のため再hashしていない。
GPU情報は記録上RTX4070 Laptop／torch2.7.1+cu118、実機ベンチや独立したGPU確認ではない。

既存3ファイルintakeをそのまま呼び、追加のengine summaryだけを別検証した。
参照生成器は全4点のSHAを確認後、auditに指定したpin3点だけを厳密な既存checkへ渡すように拡張した。
runtime・操縦・ROS・FFB・GPU環境の変更はない。既存pin関連19＋新4点関連6の計25テストで検証。

## 現在画像の参照

元PNGを無加工で確認し、局所天板境界x270〜380、中央y455付近を読み直した。
黄色テープで境界が隠れるx311〜339は隣接点補間。読取り幅の目安2pxは物理精度の信頼区間ではない。
過去のr02等と座標が同じ読取りとなったが、現在画像を新規に確認し、現在session/frame361/PNG SHAへ結んだ。
カメラ取付・床高さ・接地・距離精度の校正ではない。
pin画像ではコーンがROI右寄りに見える。最新フレームの配置をこの1枚から断定せず、
load後のno_candidateやROI端保留を参照の故障として無理に解除しない。

## GPU PCでのコピー・SHA照合・load

このフォルダのreference.jsonをGPU PCの次の場所へ置く。未pushの新参照なのでPullだけでは届かない。

`/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/body_guard_static_r01/reference.json`

```bash
cd /home/hsr/yopi_ws/RICHO-theta
sha256sum recordings/2026-11-13/body_guard_static_r01/reference.json
```

正しいSHA：`f93f4bd8e0c40fb4b6ee9e1fa3695520adc241d26c093ffca6e51334727a20d4`

一致時だけ：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_static_r01 load
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_static_r01 status
```

statusと画面下部の表示文言（または画面画像）を共有する。送受信は継続し、機体とカメラをまだ動かさない。
新pin・再起動・Lキー・旧参照転用は不要。load失敗なら繰り返さず出力共有。
active・同session/frame361・reference_scope_verifiedを確認し、現在支持列が境界をクリアしていれば
WITHHELDから数字とbody-review genの表示へ戻ることを確認する。
この4点だけでは実GUIでの表示切替・レビューの連続出力・新機能込み負荷は未確認。
参照witnessが現在まで残っている保証もなく、load時に確認する。物理距離精度の認定とは別。

## 保存・再現

原本4点はrecordings/2026-11-13/body_display_pin_intake_r01へバイト一致保存。
results_r01/audit.json・reference_validation.jsonに入力・コードSHAと検証範囲を記録。
元主JSONL未提出のためpinの元行SHAは終了後に実照合する。カメラ画像の加工はしていない。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/body_display_reference_static_r01/intake.py \
  --archive /home/robo25/Downloads/1113body.tar.xz \
  --intake-dir recordings/2026-11-13/body_display_pin_intake_r01 \
  --output-dir Experimental_results/2026-11-13/body_display_reference_static_r01/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/build_reference.py \
  --input-dir recordings/2026-11-13/body_display_pin_intake_r01 \
  --audit Experimental_results/2026-11-13/body_display_reference_static_r01/results_r01/audit.json \
  --boundary-csv Experimental_results/2026-11-13/body_display_reference_static_r01/reviewed_boundary.csv \
  --output-dir Experimental_results/2026-11-13/body_display_reference_static_r01
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_body_display_pin_intake.py tests/test_guarded_current_pin_intake.py
```

再生成は新規出力パス必須。こちらからremote load・実カメラ・CUDA・機体を起動していない。日報・commit/push未依頼。
