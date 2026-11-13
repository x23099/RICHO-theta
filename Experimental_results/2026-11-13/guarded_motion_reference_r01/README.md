# 11/13 走行確認前の現在pin参照

提出 `1113motionr01.tar.xz` の3点を検証し、元PNGを無加工で確認した。
session `f50fc9ecb85144518676084c4d001ec8`、pin frame516。
コピー時はstate=pinned、latest2708、writer_done=false、error=null。
PNG・復号BGR・同名sidecar・statusのpin情報一致、記録9コードSHAもローカルと一致した。
元主JSONLは未提出なのでpinのsource_log_line_sha256は形式確認のみで、元行との照合は終了後に行う。
保存時の稼働確認であり、現在までの接続継続やwitness残存を保証しない。

## 現在画像の境界

天板と床の局所境界をnative x270〜380で読み直し、中央y451付近をCSVに記録した。
黄色テープで明暗境界が隠れるx311〜339は隣接点間補間とした。読取り幅は目安2px。
過去sessionの書換え転用ではない。参照は自己遮蔽の別比較専用で、床姿勢・高さ・接地や距離精度の校正ではない。
全支持列が参照範囲を超える場合は外挿しない。主表示・操縦・ROS・FFBへの接続変更なし。

## GPU PCへコピーしてload

このフォルダの `reference.json` をGPU PCの次の場所へコピーする。未pushの成果物なのでPullだけでは届かない。

`/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/guarded_motion_r01/reference.json`

受信・送信を同じ接続で維持し、機体とカメラはまだ動かさない。新pin・再起動・Lキー操作は不要。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r01 load
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r01 status
```

まずstatusを提出し、active・参照session/frame516・reference_scope_verified・baseline_reproducedを確認する。
load_rejectedや失効時は走行せず、その出力を共有する。session書換えや無条件の再pinはしない。
比較値は別ログだけなので、読み込んでも主距離表示が変わるとは限らない。

成功確認後の画面録画・短距離低速直進・停止・終了提出は
[走行確認手順](../guarded_motion_live_r01/README.md) の5〜6を使う。
こちらから実機を駆動していない。距離は診断値で、停止判断や自動制御には使わない。

## 再現と証拠

原本3点は `recordings/2026-11-13/guarded_motion_pin_intake_r01/` にバイト一致で保存。
既存のbounded intakeへ明示archive-prefixを追加し、既定のstatic r02と分離して再利用した。
既存reference生成器へaudit/CSV指定を追加しただけで、runtimeは変更していない。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/intake.py \
  --archive /home/robo25/Downloads/1113motionr01.tar.xz --archive-prefix 1113motionr01 \
  --intake-dir recordings/2026-11-13/guarded_motion_pin_intake_r01 \
  --output-dir Experimental_results/2026-11-13/guarded_motion_reference_r01/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/build_reference.py \
  --input-dir recordings/2026-11-13/guarded_motion_pin_intake_r01 \
  --audit Experimental_results/2026-11-13/guarded_motion_reference_r01/results_r01/audit.json \
  --boundary-csv Experimental_results/2026-11-13/guarded_motion_reference_r01/reviewed_boundary.csv \
  --output-dir Experimental_results/2026-11-13/guarded_motion_reference_r01
```

出力は新規パス必須。根拠SHAはresults_r01/audit.jsonとreference_validation.jsonを参照。
現在のremote load・走行結果・物理精度は未確認。日報・commit/pushは今回未依頼。

検証：実提出のintakeと参照生成が成功。関連テストは次の条件で17件成功
（importされた既存static intakeのテストも含む）。環境の既存pytest/anyioプラグイン不整合により
通常起動が収集前に失敗したため、自動プラグイン読込みのみ無効化した。パッケージ変更なし。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_guarded_current_pin_intake.py
```

最初の生成は来歴の相対パス処理で失敗したため、生成器で入力を絶対パス化し、
来歴計算後に参照を書き込む順序へ修正した。自分で生成した未検証の途中JSONだけを削除し、
再生成・検証済みのreference.jsonに置き換えた。提出原本や過去の参照は変更していない。
