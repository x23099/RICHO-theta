# 11/16再開：現在pin5186の車体境界参照

提出 `body_guard_pin_20261116_r01.tar.xz` の4点を既存intakeで検証し、今回の元画像から局所天板境界を読み、新しい `reference.json` を作成した。旧sessionの参照流用ではない。

## 次の現地操作

機体停止・カメラ固定・送受信継続。新pin・再起動・Lキー・走行・録画はまだ不要。
本フォルダの [reference.json](reference.json) をGPU PCの次の場所へファイルコピーする。今回の新規成果物は未commit／未pushなので、Pullだけでは届かない。

`/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-16/body_guard_live_r01/reference.json`

```bash
cd /home/hsr/yopi_ws/RICHO-theta
sha256sum recordings/2026-11-16/body_guard_live_r01/reference.json
```

一致すべきSHA256：`60ebc44adee96cf21195fefb61dc4d988033e157971c764025e8a783f8d3edde`

一致した場合だけ1回loadする。

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-16/body_guard_live_r01 load
```

数秒後に次のstatusと画面下部を共有する。

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-16/body_guard_live_r01 status
```

`state=active`、同session、`latest.reference_frame=5186`、`latest.reference_scope_verified=true`を確認する。初回loadならgeneration=1を想定するが、世代番号だけで有効とは判定しない。実loadまでのwitness保持はこのPCでは保証できない。失敗時は連打せず理由を共有し、sessionを書き換えない。

**保存画像の赤コーンは画像左寄りで、前方ROI x270〜350をほぼ外れている。** コピー時latestでも元距離が unavailable だった。参照のactive化と距離数値の有無を分けて確認する。load後も候補なし等で保留なら、機体・カメラは動かさず、コーン台座が左円の画像x310付近に入るよう位置を調整してから再確認する。物理左右と画像左右を同一視しない。ROIや閾値を緩めたり、保留を強制解除したりしない。現在画像以降のコーン位置は未確認。

## 照合結果

| 項目 | 結果 |
|---|---|
| session | e52bb32f03d6488ebf37d769f46ec37a |
| pin frame／コピー時latest | 5186／9191 |
| state／latest.reason | pinned／comparison_pin_requested |
| 原本 | PNG・同名JSON・comparison_status.json・motion_engine_summary.jsonの4点 |
| 元PNG | 無加工1280×720、PNG SHAと復号BGR SHAがpin記録に一致 |
| 表示ゲート | enabled=true、元主結果非変更、表示棄却専用 |
| コード | 比較9＋表示7の記録SHA一致（重複除く12ファイル） |
| profile/config・記録重みSHA | ローカル設定と一致。checkpoint本体は未提出のため独立再hashなし |
| 比較保存先 | recordings/2026-11-16/body_guard_live_r01と一致 |
| コピー時状態 | error=null、writer_done=false、pin後約133.478秒、継続不確実フラグfalse |

原本は `recordings/2026-11-16/body_display_pin_intake_r01` にバイト一致保存。根拠は [audit.json](results_r01/audit.json) と [reference_validation.json](reference_validation.json)。主JSONLは未提出なのでpinの完全元行SHAは終了後の全ログで照合する。現在までの稼働・実GUI・load成功は未確認。

## 今回の境界読取り

今回の元PNGを新規に目視確認し、[reviewed_boundary.csv](reviewed_boundary.csv) にx270〜380の9点を記録。中央はy448付近。黄色テープ部分x310〜350の間は見えている隣接点から補間する。別日の境界座標を移植していない。
[boundary_readings.csv](boundary_readings.csv) は各xの周囲5画素のグレー平均（整数丸め）で、床から暗い天板へ遷移する上下の補助読取り18点。実画素と全点一致を確認した。これは自動境界検出・物理測量・精度保証ではない。
読取り目安2pxは信頼区間ではなく、参照は画像空間の自己遮蔽棄却専用。床法線・高さ・メートル換算を再校正していない。

## 再現と検証

既存の4点intake・参照生成器を無変更で再利用。再実行時は新しい出力先を使う。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/body_display_reference_static_r01/intake.py \
  --archive /home/robo25/Downloads/body_guard_pin_20261116_r01.tar.xz \
  --archive-prefix body_guard_pin_submit \
  --intake-dir recordings/2026-11-16/body_display_pin_intake_r02 \
  --output-dir Experimental_results/2026-11-16/body_display_reference_r02/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/build_reference.py \
  --input-dir recordings/2026-11-16/body_display_pin_intake_r02 \
  --audit Experimental_results/2026-11-16/body_display_reference_r02/results_r01/audit.json \
  --boundary-csv Experimental_results/2026-11-16/body_display_reference_r01/reviewed_boundary.csv \
  --output-dir Experimental_results/2026-11-16/body_display_reference_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_body_display_pin_intake.py tests/test_guarded_current_pin_intake.py
```

最初のpytestは外部anyioプラグインとシステムpytestの不整合（`_pytest.scope`なし）で収集前に終了。環境を変更せず外部プラグイン自動読込みを無効化して再実行する。結果は [verification.json](verification.json) に記録。
測距runtime・閾値・校正・GPU環境変更なし。このPCからカメラ・CUDA・ROS・車体は起動していない。非制御／非ROS／非FFBと物理精度未検証を維持する。11/13の走行・遮蔽・復帰試験を再撮影必須に戻すものではない。日報・commit/pushは今回未依頼。
